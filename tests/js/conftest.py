"""JS fixtures: a blank page whose `/static/` serves `src/ddviz/static` without the app.

A test calls a module's functions with
`page.evaluate("async (args) => { const m = await import('/static/js/<file>.js'); ... }", args)`.
A test that makes elements makes them itself and removes them at its end.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Route

ORIGIN = "http://ddviz.test"
STATIC = Path(__file__).parents[2] / "src" / "ddviz" / "static"
BLANK = '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>'
# Set explicitly: on Windows the registry may map .js to text/plain, which a
# module script refuses.
TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}


def serve(route: Route) -> None:
    """Answer `/` with a blank page and `/static/<path>` with the file; anything else is 404."""
    path = route.request.url.removeprefix(ORIGIN).split("?")[0]
    if path == "/":
        route.fulfill(body=BLANK, content_type="text/html")
        return
    file = (STATIC / path.removeprefix("/static/")).resolve()
    if not path.startswith("/static/") or not file.is_relative_to(STATIC) or not file.is_file():
        route.fulfill(status=404)
        return
    route.fulfill(
        path=file, content_type=TYPES.get(file.suffix, "application/octet-stream")
    )


def open_blank(page: Page) -> Page:
    """Route the origin to the static files and open its blank page."""
    page.route(f"{ORIGIN}/**", serve)
    page.goto(f"{ORIGIN}/")
    return page


@pytest.fixture(scope="session")
def js_page(browser: Browser) -> Iterator[Page]:
    """Return the blank page the tests of a session share."""
    page = open_blank(browser.new_page())
    yield page
    page.close()


@pytest.fixture
def clock_page(browser: Browser) -> Iterator[Page]:
    """Return a page of its own, whose `page.clock` a test may install without touching `js_page`."""
    page = open_blank(browser.new_page())
    yield page
    page.close()
