"""UI server: serves the page, runs plot tasks in workers, and answers hovers.

This process never imports polars; it only reads the files the workers
write. The routes live in `ddviz.server.api_source` (the columns),
`ddviz.server.api_plot` (drawing and hovers) and `ddviz.server.api_selection`
(the selection and its table).
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ddviz.server.api_plot import plot_router
from ddviz.server.api_selection import selection_router
from ddviz.server.api_source import source_router
from ddviz.server.broker import TaskBroker
from ddviz.server.results import Results
from ddviz.server.settings import Settings
from ddviz.server.source import Source
from ddviz.workers.jobs import WorkerJob, physical_memory

STATIC = Path(__file__).parents[1] / "static"


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
    broker = TaskBroker(root)
    source = Source(data_path, cache_root, settings, broker)
    results = Results()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        total = physical_memory()
        job = WorkerJob(total // 2 if total else None)
        log = open(root / "workers.log", "ab")  # noqa: ASYNC230, SIM115 - kept open while serving
        broker.start(job, log)
        try:
            yield
        finally:
            broker.close()
            job.close()
            results.close()
            log.close()
            shutil.rmtree(root, ignore_errors=True)

    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.include_router(source_router(source))
    app.include_router(plot_router(source, results, broker))
    app.include_router(selection_router(source, results, broker))
    return app
