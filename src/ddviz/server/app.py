"""UI server: serves the page, runs plot tasks in workers, and answers hovers.

This process never imports polars; it only reads the files the workers
write. The routes live in `ddviz.server.api_source` (the columns),
`ddviz.server.api_plot` (drawing and hovers), `ddviz.server.api_export` (the
plot's data), `ddviz.server.api_events` (the progress events),
`ddviz.server.api_selection` (the selection and its table) and, in the
window, `ddviz.server.api_saves` (the saved files). Every request needs the
token of the run
(`ddviz.server.auth`).
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ddviz.server.api_events import events_router
from ddviz.server.api_export import export_router
from ddviz.server.api_history import history_router
from ddviz.server.api_memory import memory_router
from ddviz.server.api_plot import plot_router
from ddviz.server.api_saves import SaveActions, saves_router
from ddviz.server.api_selection import selection_router
from ddviz.server.api_source import source_router
from ddviz.server.auth import TokenAuth
from ddviz.server.broker import TaskBroker
from ddviz.server.exporting import Exporting
from ddviz.server.history import SearchHistory, history_file
from ddviz.server.memory import FrontendPids, MemoryMeter
from ddviz.server.page import index_page
from ddviz.server.results import Results
from ddviz.server.settings import Settings
from ddviz.server.source import Source
from ddviz.shared.inputs import input_label
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
    desktop: bool = False,
    saves: SaveActions | None = None,
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
    desktop : bool
        Serving the desktop window: the page draws its title bar
        (`ddviz.server.page.index_page`).
    saves : SaveActions or None
        The window's saves of the plot's data, which the page opens, shows
        in their folder or cancels (`ddviz.server.api_saves`); None in a
        browser, which has no such routes.

    Returns
    -------
    fastapi.FastAPI
        The application.
    """
    broker = TaskBroker(root)
    source = Source(
        data_paths, recursive, cache_root, root / "level-index", settings, broker
    )
    results = Results()
    exporting = Exporting()
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

    title = f"ddviz - {input_label(data_paths)}" if desktop else None

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(index_page(STATIC / "index.html", title))

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
    app.include_router(export_router(source, results, broker, exporting))
    app.include_router(events_router(broker))
    app.include_router(selection_router(source, results, broker, exporting))
    if saves is not None:
        app.include_router(saves_router(saves))
    return app
