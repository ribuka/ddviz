"""Routes of the join of another table to the input (`ddviz.server.source.Source.join`): read the table, search its columns, join."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from ddviz.server.columns import search_columns
from ddviz.server.models import JoinRequest, JoinSourceRequest
from ddviz.server.source import Source

# What the search of the joined table's columns returns of each.
COLUMN_KEYS = ("name", "dtype", "numeric", "temporal")


def join_router(source: Source, max_listed: Callable[[], int]) -> APIRouter:
    """Return the routes of the join.

    Parameters
    ----------
    source : Source
        The input.
    max_listed : callable
        Returns the most matching columns a search returns
        (``columns.max_listed`` of the settings in effect).

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()

    @router.post("/api/join/source")
    async def join_source(request: JoinSourceRequest) -> dict:
        """Read the table to join, in place of one read before (`ddviz.server.source.Source.load_join_source`)."""
        return await source.load_join_source(request.paths, request.recursive)

    @router.get("/api/join/columns")
    async def join_columns(q: str = "") -> dict:
        """Return the first `max_listed` columns of the table to join whose names hold every word of `q`, as ``/api/columns`` matches them."""
        right = source.join_source
        if right is None:
            raise HTTPException(409, "no join source")
        found = search_columns(await right.schema(), q, None, max_listed())
        return {
            "total": found["total"],
            "matched": found["matched"],
            "columns": [{k: c[k] for k in COLUMN_KEYS} for c in found["columns"]],
        }

    @router.post("/api/join")
    async def join(request: JoinRequest) -> dict:
        """Join the table read to the input, by keys or by rows, once (`ddviz.server.source.Source.join`)."""
        keys = [{"left": k.left, "right": k.right} for k in request.keys]
        return await source.join(request.kind, keys)

    return router
