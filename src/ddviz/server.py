"""UI server: serves the page, runs plot tasks in workers, and answers hovers.

This process never imports polars; it only reads the files the workers write.
Columns a plot uses for the first time are converted into the column cache
before the plot task, and the plot reads them from there.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ddviz.cache import ColumnCache, evict
from ddviz.figure import build_figure
from ddviz.hover import HoverIndex
from ddviz.jobs import WorkerJob, physical_memory
from ddviz.manifest import read_manifest
from ddviz.palette import DEFAULT_COLORS
from ddviz.runner import WorkerPool
from ddviz.settings import Settings
from ddviz.spec import PlotSpec

STATIC = Path(__file__).parent / "static"


class PlotRequest(BaseModel):
    """Body of ``POST /api/plot``."""

    x: str
    y: str
    color: str | None = None
    row: str | None = None
    col: str | None = None
    width: int
    height: int


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
    hover: HoverIndex | None = None
    hover_task: int | None = None
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
            if state.hover is not None:
                state.hover.close()
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

    @app.post("/api/plot")
    async def plot(request: PlotRequest) -> JSONResponse:
        names = [c["name"] for c in (await schema())]
        hover = [
            c
            for c in (request.x, request.y, request.color, request.row, request.col)
            if c is not None
        ]
        missing = [c for c in hover if c not in names]
        if missing:
            raise HTTPException(400, f"unknown columns: {missing}")
        # The page refuses edits while converting; a plot now would kill the conversion.
        if state.converting:
            raise HTTPException(409, "converting")
        started = time.perf_counter()
        await convert(hover)
        convert_seconds = time.perf_counter() - started
        spec = PlotSpec(
            files={c: str(state.cache.file(c)) for c in hover},
            hover=hover,
            colors=DEFAULT_COLORS,
            **request.model_dump(),
        )
        started = time.perf_counter()
        task_id, end = await run({"kind": "plot", "spec": spec.to_dict()})
        if end["type"] == "cancelled":
            return JSONResponse({"cancelled": True}, status_code=409)
        if end["type"] == "error":
            raise HTTPException(500, end["message"])
        task_seconds = time.perf_counter() - started
        await asyncio.to_thread(state.cache.touch, hover)
        out = root / "tasks" / str(task_id)
        index = await asyncio.to_thread(HoverIndex, out)
        old, state.hover, state.hover_task = state.hover, index, task_id
        if old is not None:
            old.close()
            shutil.rmtree(old.out, ignore_errors=True)

        def source(name: str) -> str:
            return (
                "data:image/png;base64,"
                + base64.b64encode((out / name).read_bytes()).decode()
            )

        result = build_figure(index.manifest, source)
        result["meta"]["task"] = task_id
        result["meta"]["task_seconds"] = task_seconds
        result["meta"]["convert_seconds"] = convert_seconds
        return JSONResponse(result)

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
        if state.hover is None or task != state.hover_task:
            return {"stale": True}
        series = [int(s) for s in order.split(",") if s]
        return {"hit": state.hover.lookup(panel, fx, fy, sx, sy, series)}

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
