"""Tests of the main page as the server returns it, in the window or a browser."""

from __future__ import annotations

from ddviz.server.app import STATIC
from ddviz.server.page import index_page

TEMPLATE = STATIC / "index.html"


def test_a_browser_gets_the_page_as_it_is() -> None:
    """Without a title (``--port``), the page has no mark for the title bar."""
    page = index_page(TEMPLATE, None)
    assert page == TEMPLATE.read_text(encoding="utf-8")
    assert 'class="desktop"' not in page


def test_the_window_gets_the_title_bar_and_its_title() -> None:
    """In the window, the page is marked for the title bar and titled, with the title escaped."""
    page = index_page(TEMPLATE, "ddviz - a&b <1>.parquet")
    assert '<html lang="ja" class="desktop" data-screen="graph">' in page
    assert "<title>ddviz - a&amp;b &lt;1&gt;.parquet</title>" in page
    assert '<script src="/static/js/titlebar.js"></script>' in page
