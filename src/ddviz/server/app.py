"""UI server: serves the page, runs plot tasks in workers, and answers hovers.

This process never imports polars; it only reads the files the workers
write. The routes live in `ddviz.server.api_source` (the columns),
`ddviz.server.api_plot` (drawing and hovers) and `ddviz.server.api_selection`
(the selection and its table). Every request needs the token of the run
(`ddviz.server.auth`).
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ddviz.server.api_history import history_router
from ddviz.server.api_memory import memory_router
from ddviz.server.api_plot import plot_router
from ddviz.server.api_selection import selection_router
from ddviz.server.api_source import source_router
from ddviz.server.auth import TokenAuth
from ddviz.server.broker import TaskBroker
from ddviz.server.history import SearchHistory, history_file
from ddviz.server.memory import FrontendPids, MemoryMeter
from ddviz.server.results import Results
from ddviz.server.settings import Settings
from ddviz.server.source import Source
from ddviz.workers.jobs import WorkerJob, physical_memory

STATIC = Path(__file__).parents[1] / "static"


def create_app(
    data_paths: list[str],
    recursive: bool,
    root: Path,
    cache_root: Path,
    history_root: Path,
    settings: Settings,
    token: str,
    frontend_pids: FrontendPids | None = None,
) -> FastAPI:
    """Create the UI server for a Parquet file, a folder of them or several files.

    Parameters
    ----------
    data_paths : list of str
        Parquet file, folder of Parquet files, or several Parquet files, to
        plot (`ddviz.server.source.Source`).
    recursive : bool
        For a folder, also read the files in its subfolders.
    root : pathlib.Path
        Empty directory for task outputs and the worker log; removed on shutdown.
    cache_root : pathlib.Path
        Directory of the column cache; kept across runs.
    history_root : pathlib.Path
        Directory of the column list's search histories, one file per input
        (`ddviz.server.history`); kept across runs.
    settings : Settings
        The settings (`ddviz.server.settings`).
    token : str
        Secret of this run; requests without it are refused with 403.
    frontend_pids : callable or None
        Returns the ids of the window's WebView2 processes for the memory in
        the footer (`ddviz.server.memory`); None in a browser.

    Returns
    -------
    fastapi.FastAPI
        The application.
    """
    broker = TaskBroker(root)
    source = Source(data_paths, recursive, cache_root, settings, broker)
    results = Results()
    meter = MemoryMeter(frontend_pids)
    history = SearchHistory(
        history_file(history_root, source.paths),
        source.paths,
        settings.columns.max_history,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        total = physical_memory()
        job = WorkerJob(total // 2 if total else None)
        log = open(root / "workers.log", "ab")  # noqa: ASYNC230, SIM115 - kept open while serving
        broker.start(job, log)
        meter.job = job
        try:
            yield
        finally:
            meter.job = None
            broker.close()
            job.close()
            results.close()
            log.close()
            shutil.rmtree(root, ignore_errors=True)

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(TokenAuth, token=token)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/settings")
    async def page_settings() -> dict:
        """Return the settings the page draws with: the opacity of the legend's inactive series."""
        return {"inactive_opacity": settings.plot.legend.inactive_opacity}

    app.include_router(source_router(source, settings.columns.max_listed))
    app.include_router(history_router(history))
    app.include_router(memory_router(meter))
    app.include_router(
        plot_router(
            source,
            results,
            broker,
            settings.plot.max_levels,
            settings.plot.max_axis_levels,
            settings.hover.max_temp_bytes,
        )
    )
    app.include_router(selection_router(source, results, broker))
    return app
