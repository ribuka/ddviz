"""Routes of the file's columns: the schema, the column search, the filter pane's summaries and the search of a column's levels."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ddviz.server.columns import search_columns
from ddviz.server.source import Source


def source_router(source: Source, max_listed: int) -> APIRouter:
    """Return the routes of the file's columns.

    Parameters
    ----------
    source : Source
        The file plotted.
    max_listed : int
        Most matching columns the search returns (``columns.max_listed`` of
        the settings).

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
            "paths": source.paths,
            "files": len(source.files),
            "rows": sum(source.rows),
            "casts": source.casts,
        }

    @router.get("/api/columns")
    async def columns(
        q: str = "",
        kind: str | None = None,
        min_share: float | None = None,
        order: str = "file",
    ) -> dict:
        """Return the first `max_listed` columns whose names hold every word of `q` (`ddviz.server.columns`).

        ``"shares"`` tells whether the non-null values are counted
        yet: ``"pending"``, ``"done"`` or ``"failed"``.
        """
        try:
            found = search_columns(
                await source.schema(),
                q,
                kind,
                max_listed,
                source.nonnull,
                min_share,
                order,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {**found, "shares": source.shares_state}

    @router.get("/api/summary")
    async def summary(column: str) -> dict:
        """Return what the filter pane shows of a column (`ddviz.compute.summary`), over every row."""
        return await source.summary(column)

    @router.get("/api/filter-levels")
    async def filter_levels(column: str, q: str = "", order: str = "name") -> dict:
        """Return the first 100 levels of a categorical column that hold every word of `q`, by name or count (`ddviz.compute.levelindex`).

        ``"levels"`` is None for a column with too many levels to search;
        ``"n_levels"`` is then exact or an estimate.
        """
        return await source.filter_levels(column, q, order)

    return router
