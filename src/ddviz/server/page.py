"""The main page as the server returns it: in the window, with its title bar."""

from __future__ import annotations

import html
from pathlib import Path


def index_page(template: Path, title: str | None) -> str:
    """Return the main page, marked for the desktop window's title bar when `title` is given.

    Parameters
    ----------
    template : pathlib.Path
        ``static/index.html``.
    title : str or None
        The window's title (``ddviz - <input>``) when the server serves the
        desktop window: the page then carries ``<html class="desktop">``, so
        `js/titlebar.js` draws the title bar from the first paint, and this
        title. None in a browser (``--port``): the page as it is.

    Returns
    -------
    str
        The HTML.
    """
    page = template.read_text(encoding="utf-8")
    if title is None:
        return page
    page = page.replace('<html lang="ja"', '<html lang="ja" class="desktop"', 1)
    return page.replace(
        "<title>ddviz</title>", f"<title>{html.escape(title)}</title>", 1
    )
