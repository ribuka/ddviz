"""JS: the window's own pages, the chooser and the loading pages, in a page of their own (Issue #376).

The window's API is stood in for (`window.pywebview.api`), so no OS dialog
opens. Synthetic drag events do not go through the OS's drag and drop: they
check only whether the page highlights.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

import pytest
from playwright.sync_api import Browser, Page, Route, expect

from ddviz.desktop.window import _CHOOSER, _CLOSING, _LOADING

pytestmark = pytest.mark.js

ORIGIN = "http://desktop.test"
# The caption's geometry the window hands the title bar, and its API, which
# records the calls.
STUBS = """
window.ddvizCaption = [219, 33];
window.desktopCalls = [];
window.pywebview = { api: {} };
for (const name of ["choose", "forget_draw", "forget_join", "new", "quit", "version"]) {
  window.pywebview.api[name] = async (...args) => { window.desktopCalls.push([name, ...args]); };
}
"""
# Anything but ASCII and the ellipsis.
NOT_ENGLISH = re.compile(r"[^\x00-\x7f\u2026]")


@pytest.fixture
def open_page(browser: Browser) -> Iterator:
    """Return what opens one of the window's pages in a page of its own."""
    pages: list[Page] = []

    def open_html(html: str) -> Page:
        page = browser.new_page()
        pages.append(page)
        page.route(f"{ORIGIN}/**", lambda route: _fulfill(route, html))
        page.add_init_script(STUBS)
        page.goto(f"{ORIGIN}/")
        expect(page.locator("#titlebar")).to_be_visible()
        return page

    yield open_html
    for page in pages:
        page.close()


def _fulfill(route: Route, html: str) -> None:
    route.fulfill(body=html, content_type="text/html")


def _drag_enter(page: Page) -> bool:
    """Send `dragenter` with files to `#drop`; return whether it is highlighted, then end the drag."""
    return page.evaluate(
        """() => {
          const drop = document.getElementById("drop");
          const dataTransfer = new DataTransfer();
          dataTransfer.items.add(new File(["x"], "data.parquet"));
          drop.dispatchEvent(new DragEvent("dragenter", { bubbles: true, dataTransfer }));
          const highlighted = drop.classList.contains("dragging");
          document.dispatchEvent(new DragEvent("drop", { bubbles: true, dataTransfer }));
          return highlighted;
        }"""
    )


def test_the_chooser_lists_its_parts_in_order(open_page: Callable) -> None:
    """Heading, buttons, the subfolders' checkbox right below them, then the two notes; no drag and drop note, no cancel."""
    page = open_page(_CHOOSER)
    children = page.evaluate(
        """() => [...document.querySelector("main").children].slice(0, 5).map((e) => [
          e.tagName, e.id, e.innerText.trim(),
        ])"""
    )
    assert children == [
        ["H1", "", "Open Parquet data"],
        ["DIV", "", "Open files…\nOpen folder…"],
        ["LABEL", "", "Include subfolders when opening a folder"],
        ["P", "", "You can select several files; they are stacked into one table."],
        ["P", "", "Opening drawing settings (.json) opens their data with the same settings."],
    ]
    assert page.evaluate("document.querySelector('main').children[1].querySelector('#file') !== null")
    assert page.evaluate("document.querySelector('main').children[2].querySelector('#recursive') !== null")
    expect(page.locator("#cancel")).to_have_count(0)
    text = page.locator("body").inner_text()
    assert "drag" not in text.lower()
    assert "ドラッグ" not in text
    assert page.locator("html").get_attribute("lang") == "en"


def test_the_buttons_still_call_the_window(open_page: Callable) -> None:
    """`Open files…` and `Open folder…` (with the checkbox) call `choose`."""
    page = open_page(_CHOOSER)
    page.locator("#file").click()
    page.locator("#recursive").check()
    page.locator("#folder").click()
    page.wait_for_function("window.desktopCalls.length === 2")
    assert page.evaluate("window.desktopCalls") == [["choose", "file", False], ["choose", "folder", True]]


@pytest.mark.parametrize("join", [False, True], ids=["data", "join"])
def test_the_chooser_shows_english_alone(open_page: Callable, join: bool) -> None:
    """What the chooser shows, with the error and the message that asks for data (and its links), is English."""
    page = open_page(_CHOOSER)
    page.evaluate(
        """(join) => {
          window.ddvizDropError("Drop only .parquet files.");
          window.ddvizPendingDraw(
            'Data for the drawing settings "graph.json" was not found: C:\\\\data\\\\a.parquet. Choose the data.',
            join,
          );
        }""",
        join,
    )
    expect(page.locator("#pending")).to_be_visible()
    expect(page.locator("#forget-join")).to_be_visible(visible=join)
    shown = page.locator("#drop").inner_text()
    assert "Don't use the drawing settings" in shown
    assert ("Open without the join" in shown) is join
    assert NOT_ENGLISH.findall(shown) == []
    # The cover's text is English too, though hidden until an input opens.
    assert NOT_ENGLISH.findall(page.locator("#opening").text_content()) == []


@pytest.mark.parametrize(("html", "text"), [(_LOADING, "Starting…"), (_CLOSING, "Closing the previous data…")], ids=["starting", "closing"]
)
def test_the_loading_pages_show_a_spinner_above_english(open_page: Callable, html: str, text: str) -> None:
    """While starting and while `New` closes the data, a turning spinner is above the English text."""
    page = open_page(html)
    main = page.locator("main")
    assert main.inner_text().strip() == text
    assert NOT_ENGLISH.findall(main.inner_text()) == []
    spinner = main.locator(".spinner")
    expect(spinner).to_be_visible()
    assert spinner.evaluate("(e) => getComputedStyle(e).animationName") != "none"
    below = main.locator("span").bounding_box()
    above = spinner.bounding_box()
    assert above["y"] + above["height"] <= below["y"]


def test_opening_covers_the_chooser_and_stops_it(open_page: Callable) -> None:
    """Before `ddvizOpening` the page works and highlights dragged files; after it, the cover with the spinner and `Opening…` is there, and nothing works or highlights."""
    page = open_page(_CHOOSER)
    expect(page.locator("#opening")).to_be_hidden()
    assert _drag_enter(page)

    page.evaluate("window.ddvizOpening()")
    cover = page.locator("#opening")
    expect(cover).to_be_visible()
    expect(cover.get_by_role("status")).to_have_text("Opening…")
    spinner = cover.locator(".spinner")
    expect(spinner).to_be_visible()
    assert spinner.evaluate("(e) => getComputedStyle(e).animationName") != "none"
    assert cover.evaluate("(e) => getComputedStyle(e).backgroundColor") == "rgba(246, 246, 246, 0.8)"
    # The cover is over all of `#drop` (inside its border of 3 px), below the title bar.
    box, drop = cover.bounding_box(), page.locator("#drop").bounding_box()
    assert [box[k] for k in ("x", "y")] == [drop[k] + 3 for k in ("x", "y")]
    assert [box[k] for k in ("width", "height")] == [drop[k] - 6 for k in ("width", "height")]
    assert box["y"] >= page.locator("#titlebar").bounding_box()["height"]
    assert page.evaluate("document.querySelector('main').inert")
    # Clicks reach nothing in `main`, even through the cover: it is inert.
    cover.evaluate("(e) => { e.style.pointerEvents = 'none'; }")
    page.evaluate("window.ddvizPendingDraw('x')")
    for target in ("#file", "#folder", "#recursive", "#forget"):
        box = page.locator(target).bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(100)
    assert page.evaluate("window.desktopCalls") == []
    assert not page.locator("#recursive").is_checked()
    assert not _drag_enter(page)
