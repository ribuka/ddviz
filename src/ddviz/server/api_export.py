"""Routes that write the plot's data to a file and hand it to the page.

``POST /api/plot-data/{task}`` writes the rows of the overview (the whole
plot whatever the zoom), ``POST /api/plot-data/selection`` the selected
rows, and ``POST /api/plot-data/join-rows`` the rows of both tables of the
last dry run of a join (`ddviz.compute.joinrows`), as a CSV or Parquet file
in a worker of the table's pool (`ddviz.compute.tasks.plotdata`), whose progress goes to ``/api/events``
with the page's ``export``; the page then fetches the file once from
``/api/plot-data/file/{id}``. A file not fetched is removed when the next
one is written. While it is written, the table's pages are refused
(`ddviz.server.exporting.Exporting`); ``POST /api/plot-data/cancel`` cancels
it and leaves no file.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from ddviz.server.broker import TaskBroker, TaskEnd
from ddviz.server.errors import ensure_done
from ddviz.server.exporting import Exporting
from ddviz.server.models import (
    ExportCancel,
    JoinRowsRequest,
    PlotDataRequest,
    SelectionDataRequest,
)
from ddviz.server.plotdata import FORMATS, JOIN_ROWS, SELECTED, file_name
from ddviz.server.results import Results
from ddviz.server.source import Source
from ddviz.shared.manifest import read_manifest
from ddviz.shared.tasks import JoinRowsTask, PlotDataTask, SourceFiles, Task

# Makes the task of the columns of a file, their parts and their source files.
TaskOf = Callable[[list[str], dict[str, list[str]], SourceFiles], PlotDataTask]


def export_router(  # noqa: C901, PLR0915
    source: Source, results: Results, broker: TaskBroker, exporting: Exporting
) -> APIRouter:
    """Return the routes that write the plot's data to a file and hand it to the page.

    Parameters
    ----------
    source : Source
        The file plotted.
    results : Results
        The drawn results, whose overview or selection the file holds.
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

    async def plot_task(columns: str, drawn: dict[str, list[str]], task_of: TaskOf) -> PlotDataTask:
        """Return the task of a file of the plot's data: ``"all"`` the columns of the input, else those of `drawn`, the plot's."""
        names = [c["name"] for c in await source.schema()]
        chosen = names if columns == "all" else [c for c in names if c in drawn]
        missing = await asyncio.to_thread(source.missing, chosen)
        parts = {c: source.parts(c) for c in chosen if c not in missing}
        files = source.source_files([c for c in chosen if c not in parts])
        return task_of(chosen, parts, files)

    async def export(
        request: PlotDataRequest | SelectionDataRequest | JoinRowsRequest,
        held: AbstractContextManager,
        make: Callable[[], Awaitable[Task]],
        kind: str,
    ) -> dict | JSONResponse:
        """Write a file of rows in the table's pool and return its id and name (`ddviz.server.plotdata.file_name`, with `kind`).

        `make` returns the task, after the first await; `held` is entered
        from then until the worker has read what it reads. A file not
        fetched is removed when the next one is written. While it is
        written, the table's pages are refused (`Exporting`); an export
        cancelled by ``POST /api/plot-data/cancel`` answers 409
        ``{"cancelled": true}`` and leaves no file.
        """
        exporting.begin(request.export)
        try:
            with held:
                data = await make()
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
        now = datetime.now().astimezone()
        name = file_name(source.paths, request.format, now, kind)
        key = uuid.uuid4().hex
        exports[key] = (end, name)
        return {"file": key, "name": name}

    # Before ``/api/plot-data/{task}``, which would take its path.
    @router.post("/api/plot-data/cancel", status_code=204)
    async def plot_data_cancel(request: ExportCancel) -> None:
        """Cancel the export of the page's token: kill its task, or stop it before it reaches the pool; nothing for another token."""
        if exporting.cancel(request.export):
            await broker.cancel("table")

    # Before ``/api/plot-data/{task}`` too.
    @router.post("/api/plot-data/selection", response_model=None)
    async def selection_data(request: SelectionDataRequest) -> dict | JSONResponse:
        """Write the selected rows as a CSV or Parquet file and return its id and name; 409 ``no selection`` without a selection.

        The rows are those the selection layer's spec picks when asked, as
        the table's pages read them. The task carries the spec and reads
        nothing of the layer's directory: a selection cleared or changed, or
        a layer made again, while the file is written leaves the file as
        asked. Otherwise as ``POST /api/plot-data/{task}``.
        """
        layer = results.layer
        if layer is None:
            raise HTTPException(409, "no selection")
        spec = layer.spec

        def task_of(
            columns: list[str], parts: dict[str, list[str]], files: SourceFiles
        ) -> PlotDataTask:
            """Return the task writing the selected rows of the columns."""
            return PlotDataTask(
                str(layer.out),
                request.format,
                "selected",
                columns,
                parts,
                files,
                request.export,
                spec,
            )

        return await export(
            request,
            contextlib.nullcontext(),
            lambda: plot_task(request.columns, spec.files, task_of),
            SELECTED,
        )

    # Before ``/api/plot-data/{task}`` too.
    @router.post("/api/plot-data/join-rows", response_model=None)
    async def join_rows(request: JoinRowsRequest) -> dict | JSONResponse:
        """Write the rows of both tables of the last dry run of a join (`ddviz.compute.joinrows`) as a CSV or Parquet file and return its id and name.

        409 ``no join check`` without a dry run, ``already joined`` after
        the join (`ddviz.server.source.Source.join_rows_task`). Otherwise
        as ``POST /api/plot-data/{task}``.
        """

        async def make() -> JoinRowsTask:
            """Return the task writing the rows."""
            return await source.join_rows_task(request.format, request.columns, request.export)

        return await export(request, contextlib.nullcontext(), make, JOIN_ROWS)

    @router.post("/api/plot-data/{task}", response_model=None)
    async def plot_data(task: int, request: PlotDataRequest) -> dict | JSONResponse:
        """Write the rows of the overview as a CSV or Parquet file (`ddviz.compute.tasks.plotdata`) and return its id and name.

        The overview, not the view: the file holds the whole plot whatever
        the zoom. A worker of the table's pool writes it, sending its progress
        to ``/api/events`` with the page's ``export``; the page then fetches
        it from ``/api/plot-data/file/{id}``.
        """
        index = results.overview
        if index is None or index.out.name != str(task):
            raise HTTPException(404, "stale")

        def task_of(
            columns: list[str], parts: dict[str, list[str]], files: SourceFiles
        ) -> PlotDataTask:
            """Return the task writing the overview's rows of the columns."""
            return PlotDataTask(
                str(index.out),
                request.format,
                request.rows,
                columns,
                parts,
                files,
                request.export,
            )

        # A newer overview may replace it from the first await until the
        # worker has read it: keep its directory.
        return await export(
            request,
            results.hold(index),
            lambda: plot_task(request.columns, index.manifest.spec.files, task_of),
            "",
        )

    @router.get("/api/plot-data/file/{key}")
    async def plot_data_file(key: str) -> FileResponse:
        """Return a file of the plot's data written by ``POST /api/plot-data/{task}`` or ``/selection``, once; its name comes in ``Content-Disposition``."""
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
