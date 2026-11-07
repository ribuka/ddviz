"""Routes of the column list's search history (`ddviz.server.history`)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ddviz.server.history import SearchHistory


class HistoryWord(BaseModel):
    """Body of ``POST /api/search-history``: the keyword of the search box."""

    model_config = ConfigDict(extra="forbid")

    word: str


def history_router(history: SearchHistory) -> APIRouter:
    """Return the routes of the search history of the input.

    Each answers ``{"words": [...]}``, the keywords newest first.

    Parameters
    ----------
    history : SearchHistory
        The history of the input.

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()

    @router.get("/api/search-history")
    async def words() -> dict:
        """Return the keywords."""
        return {"words": history.words()}

    @router.post("/api/search-history")
    async def add(request: HistoryWord) -> dict:
        """Put the keyword first, as when a column it found is placed."""
        return {"words": history.add(request.word)}

    @router.delete("/api/search-history")
    async def remove(word: str | None = None) -> dict:
        """Remove `word`, or every keyword without it."""
        return {"words": history.clear() if word is None else history.remove(word)}

    return router
