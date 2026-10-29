"""Routes of the selection: a box drawn on a panel selects rows, and the table lists them.

A worker aggregates the selected rows as a layer over the drawn result. The
table's tasks run in a pool of their own, so that reading a page never kills
an aggregation.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ddviz.server.broker import TaskBroker
from ddviz.server.derive import box_selection, selection_spec
from ddviz.server.errors import ensure_done
from ddviz.server.models import SelectionRequest
from ddviz.server.results import Layer, Results
from ddviz.server.source import Source
from ddviz.shared.manifest import read_manifest

# Rows of a page of the selection table.
TABLE_PAGE = 100
# Most columns of the selection table read at once.
TABLE_MAX_COLUMNS = 200


def selection_router(source: Source, results: Results, broker: TaskBroker) -> APIRouter:
    """Return the routes of the selection and its table.

    Parameters
    ----------
    source : Source
        The file plotted.
    results : Results
        The drawn results and the selection over them.
    broker : TaskBroker
        Runs the selection and table tasks.

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()

    @router.post("/api/selection")
    async def select(request: SelectionRequest) -> dict:
        """Aggregate the selected rows as a layer over a drawn result."""
        index = results.opened(request.task)
        if index is None:
            raise HTTPException(409, "stale")
        manifest = index.manifest
        if request.panel is not None:
            try:
                selection = box_selection(
                    manifest, request.panel, request.x_range, request.y_range
                )
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
        elif results.selection is not None:
            selection = results.selection
        else:
            raise HTTPException(409, "no selection")
        spec = selection_spec(manifest, selection)
        plot_id = results.plot_id
        started = time.perf_counter()
        end = await broker.run({"kind": "selection", "spec": spec.to_dict()})
        if end.type == "cancelled" or results.plot_id != plot_id:
            end.discard()
            raise HTTPException(409, "cancelled")
        ensure_done(end)
        layer = read_manifest(end.out)
        results.set_layer(
            Layer(end.out, spec, layer["images"], layer["rows"]), selection
        )
        return {
            "task": end.task_id,
            "base": request.task,
            "images": layer["images"],
            "rows": layer["rows"],
            "selection": asdict(selection),
            "task_seconds": time.perf_counter() - started,
        }

    @router.delete("/api/selection")
    async def deselect() -> dict:
        """Forget the selection."""
        results.clear_selection()
        return {}

    @router.get("/api/table")
    async def table(offset: int = 0, col_offset: int = 0, col_limit: int = 50) -> dict:
        """Return a page of the selected rows, the columns of a window of the table.

        The table shows the plot's columns first, then the others in the
        source's order.
        """
        layer = results.layer
        if layer is None:
            raise HTTPException(409, "no selection")
        first = list(dict.fromkeys(layer.spec.hover))
        order = first + [
            c["name"] for c in await source.schema() if c["name"] not in first
        ]
        window = order[col_offset : col_offset + min(col_limit, TABLE_MAX_COLUMNS)]
        missing = set(await asyncio.to_thread(source.cache.missing, window))
        files = {c: source.path if c in missing else source.file(c) for c in window}
        end = await broker.run(
            {
                "kind": "table",
                "spec": layer.spec.to_dict(),
                "offset": offset,
                "limit": TABLE_PAGE,
                "files": files,
            },
            "table",
        )
        ensure_done(end)
        page = end.take()
        if results.layer is not layer:
            raise HTTPException(409, "stale")
        return {
            "rows": layer.rows,
            "offset": offset,
            "page_size": TABLE_PAGE,
            "index": page["index"],
            "total_columns": len(order),
            "col_offset": col_offset,
            "columns": page["columns"],
            "plot_columns": len(first),
        }

    return router
