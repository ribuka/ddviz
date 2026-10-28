"""UI server: serves the page, runs plot tasks in workers, and answers hovers.

This process never imports polars; it only reads the files the workers write.
Columns a plot uses for the first time are converted into the column cache
before the plot task, and the plot reads them from there.

A plot first aggregates its overview (the whole data range). Zooming and
panning aggregate the view again in a worker; the overview's result is kept
so that going back to it needs no worker. A new size of the plot area
aggregates the overview or the view again at that size, reusing the
overview's levels and ranges.

A box drawn on a panel selects rows; a worker aggregates them as a layer
over the drawn result, and the table lists them a page at a time. The
table's tasks run in a pool of their own, so that reading a page never kills
an aggregation.

Every plot, view and overview request carries the conditions of the local
filter (`ddviz.plan.parse_filters`); the result's spec keeps them, so the
selection and the table of a result follow its filter. The filter pane's
summary of a column runs in a third pool, once per column.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ddviz.cache import ColumnCache, evict
from ddviz.columns import search_columns
from ddviz.encoding import Encoding
from ddviz.figure import build_figure
from ddviz.hover import HoverIndex
from ddviz.jobs import WorkerJob, physical_memory
from ddviz.layout import AxisGrid, grid_layout
from ddviz.manifest import IMAGES, read_manifest
from ddviz.palette import DEFAULT_COLORS
from ddviz.plan import drawn_columns, parse_filters, scatter_spec, undrawn
from ddviz.runner import WorkerPool
from ddviz.scatter import Filter, ScatterSpec, Selection
from ddviz.settings import Settings

STATIC = Path(__file__).parent / "static"
# Rows of a page of the selection table.
TABLE_PAGE = 100
# Most columns of the selection table read at once.
TABLE_MAX_COLUMNS = 200


class PlotRequest(BaseModel):
    """Body of ``POST /api/plot``: the graph (`ddviz.encoding.Encoding.to_dict`) and the plot area size."""

    encoding: dict
    width: int
    height: int
    filters: list[dict] = []


class SizeRequest(BaseModel):
    """Body of ``POST /api/overview``: the size of the plot area in pixels and the local filter."""

    width: int
    height: int
    filters: list[dict] = []


class SelectionRequest(BaseModel):
    """Body of ``POST /api/selection``.

    The box drawn on a panel of the drawn result `task`; without a panel,
    the current selection again, for a new result of the same plot.
    """

    task: int
    panel: int | None = None
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None


class ViewRequest(SizeRequest):
    """Body of ``POST /api/view``: the data range of each x and y column of the zoomed view and the plot area size."""

    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]


@dataclass
class _State:
    """Mutable state of the server."""

    data_path: str
    root: Path
    cache_root: Path
    settings: Settings
    pool: WorkerPool | None = None
    table_pool: WorkerPool | None = None
    summary_pool: WorkerPool | None = None
    job: WorkerJob | None = None
    log: object = None
    waiting: dict[tuple[str, int], asyncio.Future] = field(default_factory=dict)
    ended: dict[tuple[str, int], dict] = field(default_factory=dict)
    listeners: set[asyncio.Queue] = field(default_factory=set)
    overview: HoverIndex | None = None
    # Bumped by every new plot, so that a view or a resized overview of an
    # older plot is dropped.
    plot_id: int = 0
    view: HoverIndex | None = None
    schema: list | None = None
    cache: ColumnCache | None = None
    converting: bool = False
    # The selected rows (`Selection`) and their layer over the drawn result:
    # its directory, manifest, spec and the columns the table shows first.
    selection: Selection | None = None
    layer: dict | None = None
    # The filter pane's summary of each column (`ddviz.summary`).
    summaries: dict[str, dict] = field(default_factory=dict)


def create_app(
    data_path: str, root: Path, cache_root: Path, settings: Settings
) -> FastAPI:
    """Create the UI server for one Parquet file.

    Parameters
    ----------
    data_path : str
        Parquet file to plot.
    root : pathlib.Path
        Empty directory for task outputs and the worker log; removed on shutdown.
    cache_root : pathlib.Path
        Directory of the column cache; kept across runs.
    settings : Settings
        Limits of the column cache.

    Returns
    -------
    fastapi.FastAPI
        The application.
    """
    state = _State(
        data_path=data_path, root=root, cache_root=cache_root, settings=settings
    )

    def on_event(pool: str) -> Callable[[int, dict], None]:
        """Return the handler of a pool's worker messages (called from reader threads)."""
        return lambda task_id, message: loop.call_soon_threadsafe(
            deliver, pool, task_id, message
        )

    def deliver(pool: str, task_id: int, message: dict) -> None:
        """Resolve the request waiting on a task and notify the progress listeners of plots."""
        if pool == "plot":
            for queue in state.listeners:
                queue.put_nowait({"task": task_id, **message})
        if message["type"] not in ("done", "error", "cancelled"):
            return
        future = state.waiting.get((pool, task_id))
        if future is None:
            state.ended[pool, task_id] = message
        elif not future.done():
            future.set_result(message)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal loop
        loop = asyncio.get_running_loop()
        total = physical_memory()
        state.job = WorkerJob(total // 2 if total else None)
        state.log = open(root / "workers.log", "ab")  # noqa: ASYNC230, SIM115 - kept open while serving
        state.pool = WorkerPool(root / "tasks", on_event("plot"), state.job, state.log)
        state.table_pool = WorkerPool(
            root / "table", on_event("table"), state.job, state.log
        )
        state.summary_pool = WorkerPool(
            root / "summary", on_event("summary"), state.job, state.log
        )
        try:
            yield
        finally:
            state.pool.close()
            state.table_pool.close()
            state.summary_pool.close()
            state.job.close()
            for index in (state.overview, state.view):
                if index is not None:
                    index.close()
            state.log.close()
            shutil.rmtree(root, ignore_errors=True)

    loop: asyncio.AbstractEventLoop | None = None
    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    async def run(task: dict, pool: str = "plot") -> tuple[int, dict]:
        """Submit a task to a pool (``"plot"``, ``"table"`` or ``"summary"``) and wait for its end."""
        workers = {
            "plot": state.pool,
            "table": state.table_pool,
            "summary": state.summary_pool,
        }[pool]
        task_id = await asyncio.to_thread(workers.submit, task)
        # The task may have ended before its future was registered.
        if (pool, task_id) in state.ended:
            return task_id, state.ended.pop((pool, task_id))
        future = loop.create_future()
        state.waiting[pool, task_id] = future
        try:
            return task_id, await future
        finally:
            state.waiting.pop((pool, task_id), None)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    def evict_cache(keep: list[Path]) -> None:
        """Remove old column files, keeping the given ones."""
        limits = state.settings.cache
        evict(state.cache_root, limits.max_bytes, limits.max_unused_days, keep)

    @app.get("/api/schema")
    async def schema() -> list:
        if state.schema is None:
            task_id, end = await run({"kind": "schema", "path": state.data_path})
            if end["type"] != "done":
                raise HTTPException(500, end.get("message", end["type"]))
            out = root / "tasks" / str(task_id)
            columns = read_manifest(out)["columns"]
            shutil.rmtree(out, ignore_errors=True)
            state.cache = await asyncio.to_thread(
                ColumnCache,
                state.cache_root,
                Path(state.data_path),
                [c["name"] for c in columns],
            )
            await asyncio.to_thread(evict_cache, [])
            state.schema = columns
        return state.schema

    @app.get("/api/columns")
    async def columns(q: str = "", kind: str | None = None, limit: int = 200) -> dict:
        """Return the columns whose names hold every word of `q` (`ddviz.columns`)."""
        try:
            return search_columns(await schema(), q, kind, limit)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    async def convert(columns: list[str]) -> None:
        """Convert the columns not in the cache yet; plots are refused meanwhile."""
        missing = state.cache.missing(columns)
        if not missing:
            return
        state.converting = True
        try:
            task_id, end = await run(
                {
                    "kind": "convert",
                    "path": state.data_path,
                    "files": {c: str(state.cache.file(c)) for c in missing},
                }
            )
        finally:
            state.converting = False
        shutil.rmtree(root / "tasks" / str(task_id), ignore_errors=True)
        if end["type"] != "done":
            raise HTTPException(500, end.get("message", end["type"]))
        await asyncio.to_thread(evict_cache, [state.cache.file(c) for c in columns])

    def drop(index: HoverIndex | None) -> None:
        """Close a result's hover files and remove its directory."""
        if index is not None:
            index.close()
            shutil.rmtree(index.out, ignore_errors=True)

    async def run_plot(spec: ScatterSpec) -> tuple[HoverIndex | None, dict]:
        """Run a plot task; return its opened result, or None when a newer task killed it."""
        started = time.perf_counter()
        task_id, end = await run({"kind": "plot", "spec": spec.to_dict()})
        if end["type"] == "cancelled":
            return None, {}
        if end["type"] == "error":
            raise HTTPException(500, end["message"])
        timing = {"task_seconds": time.perf_counter() - started}
        await asyncio.to_thread(state.cache.touch, spec.hover)
        index = await asyncio.to_thread(HoverIndex, root / "tasks" / str(task_id))
        return index, timing

    def figure(index: HoverIndex, timing: dict) -> JSONResponse:
        """Return the figure of a result; the page fetches its images on their own."""
        result = build_figure(index.manifest)
        result["meta"]["task"] = int(index.out.name)
        result["meta"]["filters"] = index.manifest["spec"]["filters"]
        result["meta"].update(timing)
        return JSONResponse(result)

    async def filters_of(raw: list[dict]) -> list[Filter]:
        """Return the checked conditions of the local filter of a request."""
        numeric = {c["name"]: c["numeric"] for c in (await schema())}
        try:
            return parse_filters(raw, numeric)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/plot")
    async def plot(request: PlotRequest) -> JSONResponse:
        try:
            encoding = Encoding.from_dict(request.encoding)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        filters = await filters_of(request.filters)
        numeric = {c["name"]: c["numeric"] for c in (await schema())}
        missing = [c for c in encoding.columns() if c not in numeric]
        if missing:
            raise HTTPException(400, f"unknown columns: {missing}")
        if not encoding.x or not encoding.y:
            raise HTTPException(400, "x and y need a column")
        text = [c for c in (*encoding.x, *encoding.y) if not numeric[c]]
        if text:
            raise HTTPException(400, f"x and y need numeric columns: {text}")
        # The page refuses edits while converting; a plot now would kill the conversion.
        if state.converting:
            raise HTTPException(409, "converting")
        started = time.perf_counter()
        columns = drawn_columns(encoding)
        columns += [f.column for f in filters if f.column not in columns]
        await convert(columns)
        convert_seconds = time.perf_counter() - started
        spec = scatter_spec(
            encoding,
            {c: str(state.cache.file(c)) for c in columns},
            request.width,
            request.height,
            DEFAULT_COLORS,
            filters,
        )
        state.plot_id += 1
        index, timing = await run_plot(spec)
        if index is None:
            return JSONResponse({"cancelled": True}, status_code=409)
        # Open the new result before closing the old ones, whose files are
        # memory-mapped and cannot be removed while open on Windows.
        old = (state.overview, state.view)
        state.overview, state.view = index, None
        for o in old:
            drop(o)
        clear_selection()
        return figure(
            index,
            {
                **timing,
                "convert_seconds": convert_seconds,
                "encoding": encoding.to_dict(),
                "undrawn": undrawn(encoding),
            },
        )

    def again(
        request: SizeRequest, filters: list[Filter], x_ranges: list, y_ranges: list
    ) -> ScatterSpec:
        """Return the overview's spec for other ranges, size or filter, reusing its levels."""
        overview = state.overview.manifest
        if len(x_ranges) != len(overview["spec"]["x"]) or len(y_ranges) != len(
            overview["spec"]["y"]
        ):
            raise HTTPException(400, "one range per x and y column")
        return ScatterSpec.from_dict(
            {
                **overview["spec"],
                "files": {
                    **overview["spec"]["files"],
                    **{f.column: str(state.cache.file(f.column)) for f in filters},
                },
                "filters": [asdict(f) for f in filters],
                "width": request.width,
                "height": request.height,
                "view": {
                    "x_ranges": [list(r) for r in x_ranges],
                    "y_ranges": [list(r) for r in y_ranges],
                    "levels": overview["levels"],
                },
            }
        )

    def unchanged(index: HoverIndex | None, spec: ScatterSpec) -> bool:
        """Whether a result already has the panels, ranges and filter of `spec`.

        A new size often keeps the layout: a grid that scrolls in both
        directions keeps its panels at their smallest size.
        """
        if index is None:
            return False
        manifest = index.manifest
        old = manifest["layout"]
        axes = AxisGrid(**manifest["axes"])
        layout = grid_layout(spec.width, spec.height, axes.rows, axes.cols, *axes.gaps)
        return (
            asdict(layout) == old
            and [list(r) for r in manifest["x_ranges"]] == spec.view.x_ranges
            and [list(r) for r in manifest["y_ranges"]] == spec.view.y_ranges
            and manifest["spec"]["filters"] == [asdict(f) for f in spec.filters]
        )

    async def run_again(spec: ScatterSpec) -> tuple[HoverIndex | None, dict]:
        """Run a plot task of the current plot; None when it was cancelled or the plot changed."""
        plot_id = state.plot_id
        index, timing = await run_plot(spec)
        if index is None or state.plot_id != plot_id:
            drop(index)
            return None, {}
        return index, timing

    @app.post("/api/view")
    async def view(request: ViewRequest) -> JSONResponse:
        if state.overview is None:
            raise HTTPException(409, "no plot")
        if state.converting:
            raise HTTPException(409, "converting")
        filters = await filters_of(request.filters)
        await convert([f.column for f in filters])
        spec = again(request, filters, request.x_ranges, request.y_ranges)
        if unchanged(state.view, spec):
            # A task for another size must not replace the result drawn now.
            await asyncio.to_thread(state.pool.cancel)
            return figure(state.view, {"task_seconds": 0.0})
        index, timing = await run_again(spec)
        if index is None:
            return JSONResponse({"cancelled": True}, status_code=409)
        old, state.view = state.view, index
        drop(old)
        return figure(index, timing)

    @app.post("/api/overview")
    async def overview(request: SizeRequest) -> JSONResponse:
        """Aggregate the overview again at another size of the plot area."""
        if state.overview is None:
            raise HTTPException(409, "no plot")
        if state.converting:
            raise HTTPException(409, "converting")
        filters = await filters_of(request.filters)
        await convert([f.column for f in filters])
        # The padded data ranges hold every row, so this is the overview.
        manifest = state.overview.manifest
        spec = again(request, filters, manifest["x_ranges"], manifest["y_ranges"])
        if unchanged(state.overview, spec):
            await asyncio.to_thread(state.pool.cancel)
            return figure(state.overview, {"task_seconds": 0.0})
        index, timing = await run_again(spec)
        if index is None:
            return JSONResponse({"cancelled": True}, status_code=409)
        old, state.overview = state.overview, index
        drop(old)
        return figure(index, timing)

    def opened(task: int) -> HoverIndex | None:
        """Return the open result (the overview or the view) of a task, if any."""
        return next(
            (
                i
                for i in (state.view, state.overview)
                if i is not None and i.out.name == str(task)
            ),
            None,
        )

    @app.get("/api/images/{task}")
    async def images(task: int) -> FileResponse:
        """Return the PNGs of a result or a selection layer one after another (its ``images`` slices it)."""
        index = opened(task)
        if index is not None:
            out = index.out
        elif state.layer is not None and state.layer["out"].name == str(task):
            out = state.layer["out"]
        else:
            raise HTTPException(404, "stale")
        return FileResponse(out / IMAGES, media_type="application/octet-stream")

    def clear_selection() -> None:
        """Forget the selection and remove its layer."""
        state.selection = None
        drop_layer(state.layer)
        state.layer = None

    def drop_layer(layer: dict | None) -> None:
        if layer is not None:
            shutil.rmtree(layer["out"], ignore_errors=True)

    def selection_of(manifest: dict, request: SelectionRequest) -> Selection:
        """Return the rows the box of a request selects in a result."""
        spec, levels = manifest["spec"], manifest["levels"]
        axes = AxisGrid(**manifest["axes"])
        if not 0 <= request.panel < axes.rows * axes.cols:
            raise HTTPException(400, "no such panel")
        if request.x_range is None or request.y_range is None:
            raise HTTPException(400, "a box needs x_range and y_range")
        xi, yj = axes.axes(request.panel)
        prow, pcol = divmod(request.panel, axes.cols)
        return Selection(
            x=spec["x"][xi],
            y=spec["y"][yj],
            x_range=sorted(request.x_range),
            y_range=sorted(request.y_range),
            row=levels["row"][prow // axes.ny] if spec["row"] else None,
            col=levels["col"][pcol // axes.nx] if spec["col"] else None,
        )

    @app.post("/api/selection")
    async def select(request: SelectionRequest) -> dict:
        """Aggregate the selected rows as a layer over a drawn result."""
        index = opened(request.task)
        if index is None:
            raise HTTPException(409, "stale")
        manifest = index.manifest
        if request.panel is not None:
            selection = selection_of(manifest, request)
        elif state.selection is not None:
            selection = state.selection
        else:
            raise HTTPException(409, "no selection")
        spec = ScatterSpec.from_dict(
            {
                **manifest["spec"],
                "view": {
                    "x_ranges": manifest["x_ranges"],
                    "y_ranges": manifest["y_ranges"],
                    "levels": manifest["levels"],
                },
                "selection": asdict(selection),
            }
        )
        plot_id = state.plot_id
        started = time.perf_counter()
        task_id, end = await run({"kind": "selection", "spec": spec.to_dict()})
        out = root / "tasks" / str(task_id)
        if end["type"] == "cancelled" or state.plot_id != plot_id:
            shutil.rmtree(out, ignore_errors=True)
            raise HTTPException(409, "cancelled")
        if end["type"] == "error":
            raise HTTPException(500, end["message"])
        layer = read_manifest(out)
        old, state.layer = state.layer, {"out": out, "spec": spec, **layer}
        state.selection = selection
        drop_layer(old)
        return {
            "task": task_id,
            "base": request.task,
            "images": layer["images"],
            "rows": layer["rows"],
            "selection": asdict(selection),
            "task_seconds": time.perf_counter() - started,
        }

    @app.delete("/api/selection")
    async def deselect() -> dict:
        clear_selection()
        return {}

    @app.get("/api/table")
    async def table(offset: int = 0, col_offset: int = 0, col_limit: int = 50) -> dict:
        """Return a page of the selected rows, the columns of a window of the table.

        The table shows the plot's columns first, then the others in the
        source's order.
        """
        layer = state.layer
        if layer is None:
            raise HTTPException(409, "no selection")
        spec = layer["spec"]
        first = list(dict.fromkeys(spec.hover))
        order = first + [c["name"] for c in await schema() if c["name"] not in first]
        window = order[col_offset : col_offset + min(col_limit, TABLE_MAX_COLUMNS)]
        missing = set(await asyncio.to_thread(state.cache.missing, window))
        files = {
            c: state.data_path if c in missing else str(state.cache.file(c))
            for c in window
        }
        task_id, end = await run(
            {
                "kind": "table",
                "spec": spec.to_dict(),
                "offset": offset,
                "limit": TABLE_PAGE,
                "files": files,
            },
            "table",
        )
        out = root / "table" / str(task_id)
        if end["type"] == "cancelled":
            raise HTTPException(409, "cancelled")
        if end["type"] == "error":
            raise HTTPException(500, end["message"])
        page = read_manifest(out)
        shutil.rmtree(out, ignore_errors=True)
        if state.layer is not layer:
            raise HTTPException(409, "stale")
        return {
            "rows": layer["rows"],
            "offset": offset,
            "page_size": TABLE_PAGE,
            "index": page["index"],
            "total_columns": len(order),
            "col_offset": col_offset,
            "columns": page["columns"],
            "plot_columns": len(first),
        }

    @app.get("/api/summary")
    async def summary(column: str) -> dict:
        """Return what the filter pane shows of a column (`ddviz.summary`), over every row."""
        if column not in {c["name"] for c in await schema()}:
            raise HTTPException(400, f"unknown column: {column}")
        # One at a time: a new task in the pool kills the running one.
        async with summary_lock:
            if column not in state.summaries:
                await summarize(column)
        return state.summaries[column]

    summary_lock = asyncio.Lock()

    async def summarize(column: str) -> None:
        """Run the summary task of a column and keep its result."""
        # A column not converted yet is read from the source: converting
        # it here could race the plot's conversion of the same column.
        missing = await asyncio.to_thread(state.cache.missing, [column])
        file = state.data_path if missing else str(state.cache.file(column))
        task_id, end = await run(
            {"kind": "summary", "file": file, "column": column}, "summary"
        )
        out = root / "summary" / str(task_id)
        if end["type"] == "cancelled":
            raise HTTPException(409, "cancelled")
        if end["type"] == "error":
            raise HTTPException(500, end["message"])
        state.summaries[column] = read_manifest(out)
        shutil.rmtree(out, ignore_errors=True)

    @app.get("/api/hover")
    async def hover(
        task: int,
        panel: int,
        fx: float,
        fy: float,
        sx: float,
        sy: float,
        order: str = "",
    ) -> dict:
        index = opened(task)
        if index is None:
            return {"stale": True}
        series = [int(s) for s in order.split(",") if s]
        return {"hit": index.lookup(panel, fx, fy, sx, sy, series)}

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        queue: asyncio.Queue = asyncio.Queue()
        state.listeners.add(queue)

        async def stream() -> AsyncIterator[str]:
            try:
                while True:
                    message = await queue.get()
                    yield f"data: {json.dumps(message)}\n\n"
            finally:
                state.listeners.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
