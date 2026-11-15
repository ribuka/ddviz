"""Routes of the desktop window's saves of the plot's data: open the file, show it in its folder, cancel its transfer (Issue #194).

The window saves the plot's data to Downloads itself
(`ddviz.desktop.downloads`), and only it knows where each file went. The
page asks for these by HTTP, never through the window's JS API, so that the
window stays out of the page ("窓への依存の閉じ込め" in ``docs/spec.md``):
the window gives the server its `SaveActions` (`ddviz.server.app.create_app`),
and a browser (``--port``) has none of these routes. A save is known by the
id of its file (``/api/plot-data/file/{id}``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from fastapi import APIRouter, HTTPException


class SaveActions(Protocol):
    """What the window does with a save, by the id of its file.

    Each raises `KeyError` for an id it did not save, and `open` and
    `reveal` raise `FileNotFoundError` when the file is no longer where it
    was saved, and `OSError` when the OS cannot do it.
    """

    def open(self, file: str) -> None:
        """Open the saved file with its app."""

    def reveal(self, file: str) -> None:
        """Show the saved file selected in its folder."""

    def cancel(self, file: str) -> None:
        """Cancel the file's transfer; nothing once it has ended."""


def saves_router(saves: SaveActions) -> APIRouter:
    """Return the routes of the window's saves.

    Parameters
    ----------
    saves : SaveActions
        The window's saves.

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()

    async def act(action: Callable[[str], None], file: str) -> None:
        try:
            await asyncio.to_thread(action, file)
        except KeyError:
            raise HTTPException(404, "unknown") from None
        except FileNotFoundError:
            raise HTTPException(404, "missing") from None
        except OSError as error:
            raise HTTPException(500, error.strerror or str(error)) from None

    @router.post("/api/saves/{file}/open", status_code=204)
    async def open_file(file: str) -> None:
        """Open a saved file with its app: 404 ``missing`` when it is gone."""
        await act(saves.open, file)

    @router.post("/api/saves/{file}/reveal", status_code=204)
    async def reveal_file(file: str) -> None:
        """Show a saved file selected in its folder: 404 ``missing`` when it is gone."""
        await act(saves.reveal, file)

    @router.post("/api/saves/{file}/cancel", status_code=204)
    async def cancel_file(file: str) -> None:
        """Cancel a file's transfer to Downloads."""
        await act(saves.cancel, file)

    return router
