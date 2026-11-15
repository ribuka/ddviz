"""Routes that write the plot's data to a file and hand it to the page.

``POST /api/plot-data/{task}`` writes the rows of the overview (the whole
plot whatever the zoom) as a CSV or Parquet file in a worker of the table's
pool (`ddviz.compute.tasks.plotdata`), whose progress goes to
``/api/events`` with the page's ``export``; the page then fetches the file
once from ``/api/plot-data/file/{id}``. A file not fetched is removed when
the next one is written. While it is written, the table's pages are refused
(`ddviz.server.exporting.Exporting`); ``POST /api/plot-data/cancel`` cancels
it and leaves no file.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from ddviz.server.broker import TaskBroker, TaskEnd
from ddviz.server.errors import ensure_done
from ddviz.server.exporting import Exporting
from ddviz.server.models import ExportCancel, PlotDataRequest
from ddviz.server.plotdata import FORMATS, file_name
from ddviz.server.results import Results
from ddviz.server.source import Source
from ddviz.shared.manifest import read_manifest
from ddviz.shared.tasks import PlotDataTask


def export_router(
    source: Source, results: Results, broker: TaskBroker, exporting: Exporting
) -> APIRouter:
    """Return the routes that write the plot's data to a file and hand it to the page.

    Parameters
    ----------
    source : Source
        The file plotted.
    results : Results
        The drawn results, whose overview the file holds.
    broker : TaskBroker
        Runs the export tasks in the table's pool.
    exporting : Exporting
        The export of the plot's data running, which the page may cancel.

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()

    # Files of the plot's data written and not fetched yet, by their id.
    exports: dict[str, tuple[TaskEnd, str]] = {}

    # Before ``/api/plot-data/{task}``, which would take its path.
    @router.post("/api/plot-data/cancel", status_code=204)
    async def plot_data_cancel(request: ExportCancel) -> None:
        """Cancel the export of the page's token: kill its task, or stop it before it reaches the pool; nothing for another token."""
        if exporting.cancel(request.export):
            await broker.cancel("table")

    @router.post("/api/plot-data/{task}", response_model=None)
    async def plot_data(task: int, request: PlotDataRequest) -> dict | JSONResponse:
        """Write the rows of the overview as a CSV or Parquet file (`ddviz.compute.tasks.plotdata`) and return its id and name.

        The overview, not the view: the file holds the whole plot whatever
        the zoom. A worker of the table's pool writes it, sending its progress
        to ``/api/events`` with the page's ``export``; the page then fetches
        it from ``/api/plot-data/file/{id}``. A file not fetched is removed
        when the next one is written. While it is written, the table's pages
        are refused (`Exporting`); an export cancelled by
        ``POST /api/plot-data/cancel`` answers 409 ``{"cancelled": true}``
        and leaves no file.
        """
        index = results.overview
        if index is None or index.out.name != str(task):
            raise HTTPException(404, "stale")
        exporting.begin(request.export)
        try:
            # A newer overview may replace it from the first await until the
            # worker has read it: keep its directory from here.
            with results.hold(index):
                spec = index.manifest.spec
                names = [c["name"] for c in await source.schema()]
                if request.columns == "all":
                    columns = names
                else:
                    columns = [c for c in names if c in spec.files]
                missing = await asyncio.to_thread(source.missing, columns)
                parts = {c: source.parts(c) for c in columns if c not in missing}
                data = PlotDataTask(
                    str(index.out),
                    request.format,
                    request.rows,
                    columns,
                    parts,
                    source.source_files([c for c in columns if c not in parts]),
                    request.export,
                )
                for end, _ in exports.values():
                    end.discard()
                exports.clear()
                if exporting.cancelled:
                    return JSONResponse({"cancelled": True}, status_code=409)
                exporting.submitted = True
                end = await broker.run(data, "table")
            if exporting.cancelled:
                end.discard()
                return JSONResponse({"cancelled": True}, status_code=409)
        finally:
            exporting.end()
        ensure_done(end)
        name = file_name(source.paths, request.format, datetime.now().astimezone())
        key = uuid.uuid4().hex
        exports[key] = (end, name)
        return {"file": key, "name": name}

    @router.get("/api/plot-data/file/{key}")
    async def plot_data_file(key: str) -> FileResponse:
        """Return a file of the plot's data written by ``POST /api/plot-data/{task}``, once; its name comes in ``Content-Disposition``."""
        found = exports.pop(key, None)
        if found is None:
            raise HTTPException(404, "unknown file")
        end, name = found
        file = end.out / read_manifest(end.out)["file"]
        return FileResponse(
            file,
            media_type=FORMATS[file.suffix.removeprefix(".")],
            filename=name,
            background=BackgroundTask(end.discard),
        )

    return router
