"""UI server: serves the page, runs plot tasks in workers, and answers hovers.

This process never imports polars; it only reads the files the workers write.
Columns a plot uses for the first time are converted into the column cache
before the plot task, and the plot reads them from there.

A plot first aggregates its overview (the whole data range). Zooming and
panning aggregate the view again in a worker; the overview's result is kept
so that going back to it needs no worker. A new size of the plot area
aggregates the overview or the view again at that size, reusing the
overview's levels and ranges.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import AsyncIterator
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
from ddviz.layout import grid_layout
from ddviz.manifest import IMAGES, read_manifest
from ddviz.palette import DEFAULT_COLORS
from ddviz.plan import drawn_columns, scatter_spec, undrawn
from ddviz.runner import WorkerPool
from ddviz.scatter import ScatterSpec
from ddviz.settings import Settings

STATIC = Path(__file__).parent / "static"


class PlotRequest(BaseModel):
    """Body of ``POST /api/plot``: the graph (`ddviz.encoding.Encoding.to_dict`) and the plot area size."""

    encoding: dict
    width: int
    height: int


class SizeRequest(BaseModel):
    """Body of ``POST /api/overview``: the size of the plot area in pixels."""

    width: int
    height: int


class ViewRequest(SizeRequest):
    """Body of ``POST /api/view``: the data ranges of the zoomed view and the plot area size."""

    x_range: tuple[float, float]
    y_range: tuple[float, float]


@dataclass
class _State:
    """Mutable state of the server."""

    data_path: str
    root: Path
    cache_root: Path
    settings: Settings
    pool: WorkerPool | None = None
    job: WorkerJob | None = None
    log: object = None
    waiting: dict[int, asyncio.Future] = field(default_factory=dict)
    ended: dict[int, dict] = field(default_factory=dict)
    listeners: set[asyncio.Queue] = field(default_factory=set)
    overview: HoverIndex | None = None
    # Bumped by every new plot, so that a view or a resized overview of an
    # older plot is dropped.
    plot_id: int = 0
    view: HoverIndex | None = None
    schema: list | None = None
    cache: ColumnCache | None = None
    converting: bool = False


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

    def on_event(task_id: int, message: dict) -> None:
        """Hand a worker message to the event loop (called from reader threads)."""
        loop.call_soon_threadsafe(deliver, task_id, message)

    def deliver(task_id: int, message: dict) -> None:
        """Resolve the request waiting on a task and notify the progress listeners."""
        for queue in state.listeners:
            queue.put_nowait({"task": task_id, **message})
        if message["type"] not in ("done", "error", "cancelled"):
            return
        future = state.waiting.get(task_id)
        if future is None:
            state.ended[task_id] = message
        elif not future.done():
            future.set_result(message)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal loop
        loop = asyncio.get_running_loop()
        total = physical_memory()
        state.job = WorkerJob(total // 2 if total else None)
        state.log = open(root / "workers.log", "ab")  # noqa: ASYNC230, SIM115 - kept open while serving
        state.pool = WorkerPool(root / "tasks", on_event, state.job, state.log)
        try:
            yield
        finally:
            state.pool.close()
            state.job.close()
            for index in (state.overview, state.view):
                if index is not None:
                    index.close()
            state.log.close()
            shutil.rmtree(root, ignore_errors=True)

    loop: asyncio.AbstractEventLoop | None = None
    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    async def run(task: dict) -> tuple[int, dict]:
        """Submit a task and wait for its end."""
        task_id = await asyncio.to_thread(state.pool.submit, task)
        # The task may have ended before its future was registered.
        if task_id in state.ended:
            return task_id, state.ended.pop(task_id)
        future = loop.create_future()
        state.waiting[task_id] = future
        try:
            return task_id, await future
        finally:
            state.waiting.pop(task_id, None)

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
        result["meta"].update(timing)
        return JSONResponse(result)

    @app.post("/api/plot")
    async def plot(request: PlotRequest) -> JSONResponse:
        try:
            encoding = Encoding.from_dict(request.encoding)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
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
        await convert(columns)
        convert_seconds = time.perf_counter() - started
        spec = scatter_spec(
            encoding,
            {c: str(state.cache.file(c)) for c in columns},
            request.width,
            request.height,
            DEFAULT_COLORS,
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
        return figure(
            index,
            {
                **timing,
                "convert_seconds": convert_seconds,
                "encoding": encoding.to_dict(),
                "undrawn": undrawn(encoding),
            },
        )

    def again(request: SizeRequest, x_range: list, y_range: list) -> ScatterSpec:
        """Return the overview's spec for other ranges or another size, reusing its levels."""
        overview = state.overview.manifest
        return ScatterSpec.from_dict(
            {
                **overview["spec"],
                "width": request.width,
                "height": request.height,
                "view": {
                    "x_range": x_range,
                    "y_range": y_range,
                    "levels": overview["levels"],
                },
            }
        )

    def unchanged(index: HoverIndex | None, spec: ScatterSpec) -> bool:
        """Whether a result already has the panels and ranges of `spec`.

        A new size often keeps the layout: a grid that scrolls in both
        directions keeps its panels at their smallest size.
        """
        if index is None:
            return False
        manifest = index.manifest
        old = manifest["layout"]
        layout = grid_layout(spec.width, spec.height, old["nrow"], old["ncol"])
        return (
            asdict(layout) == old
            and list(manifest["x_range"]) == spec.view.x_range
            and list(manifest["y_range"]) == spec.view.y_range
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
        spec = again(request, list(request.x_range), list(request.y_range))
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
        # The padded data ranges hold every row, so this is the overview.
        manifest = state.overview.manifest
        spec = again(request, manifest["x_range"], manifest["y_range"])
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
        """Return the PNGs of a result one after another (the meta's ``images`` slices it)."""
        index = opened(task)
        if index is None:
            raise HTTPException(404, "stale")
        return FileResponse(index.out / IMAGES, media_type="application/octet-stream")

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
