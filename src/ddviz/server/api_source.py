"""Routes of the file's columns: the schema, the column search and the filter pane's summaries."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ddviz.server.columns import search_columns
from ddviz.server.source import Source


def source_router(source: Source) -> APIRouter:
    """Return the routes of the file's columns.

    Parameters
    ----------
    source : Source
        The file plotted.

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()

    @router.get("/api/schema")
    async def schema() -> list:
        """Return the columns of the file, reading them on the first request (Load)."""
        return await source.schema()

    @router.get("/api/source")
    async def input_files() -> dict:
        """Return the input after Load: its files, rows and the columns cast to a common type.

        ``"casts"`` lists the columns whose type differs between the files,
        with their types and the type they are read as; the page tells them
        once after Load.
        """
        await source.schema()
        return {
            "path": source.path,
            "files": len(source.files),
            "rows": sum(source.rows),
            "casts": source.casts,
        }

    @router.get("/api/columns")
    async def columns(
        q: str = "",
        kind: str | None = None,
        limit: int = 200,
        min_share: float | None = None,
        order: str = "file",
    ) -> dict:
        """Return the columns whose names hold every word of `q` (`ddviz.server.columns`).

        ``"shares"`` tells whether the share of non-null values is known
        yet: ``"pending"``, ``"done"`` or ``"failed"``.
        """
        try:
            found = search_columns(
                await source.schema(), q, kind, limit, source.shares, min_share, order
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {**found, "shares": source.shares_state}

    @router.get("/api/summary")
    async def summary(column: str) -> dict:
        """Return what the filter pane shows of a column (`ddviz.compute.summary`), over every row."""
        return await source.summary(column)

    return router
