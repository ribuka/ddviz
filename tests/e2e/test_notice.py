"""E2E: an error in the status bar has its icon and a toast at the top right."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.test_scatter import place

pytestmark = pytest.mark.e2e


def fail(route: Route) -> None:
    """Answer a plot request as a failed task does (FastAPI's error body)."""
    route.fulfill(
        status=500,
        content_type="application/json",
        body=json.dumps({"detail": "集約に失敗した"}),
    )


def drop(page: Page, column: str, role: str) -> None:
    """Drag a column onto a role's zone, without waiting for the chip: a failed plot takes it back."""
    source = page.locator("#columns .column").filter(
        has=page.get_by_text(column, exact=True)
    )
    source.drag_to(page.locator(f'.zone[data-role="{role}"]'))


def test_an_error_shows_its_icon_and_a_toast(app_page: Page) -> None:
    """A failed plot marks the status as an error and opens a toast, and takes its drop back; the next plot clears the mark."""
    page = app_page
    page.route("**/api/plot", fail)
    place(page, "x", "x")
    drop(page, "y", "y")

    status = page.locator("#status")
    expect(status).to_have_text("エラー: 集約に失敗した")
    expect(status).to_have_class("notice-error")
    # The first plot failed: back to the graph before the drop, without a figure.
    expect(page.locator('.zone[data-role="y"] .chip')).to_have_count(0)
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text("x")
    expect(page.locator("#empty")).to_be_visible()
    icon = status.evaluate("e => getComputedStyle(e, '::before').content")
    assert "!" in icon

    toast = page.locator("#toasts .toast")
    expect(toast).to_have_count(1)  # the same error again replaces its toast
    expect(toast).to_have_text("エラー: 集約に失敗した×")
    expect(toast).to_have_attribute("role", "alert")
    box = toast.bounding_box()
    viewport = page.viewport_size
    assert box is not None and viewport is not None
    assert box["y"] < 50
    assert box["x"] + box["width"] > viewport["width"] - 50

    toast.get_by_role("button", name="閉じる").click()
    expect(toast).to_have_count(0)

    page.unroute("**/api/plot")
    place(page, "y", "y")
    expect(status).not_to_have_class("notice-error")
    expect(page.locator("#toasts .toast")).to_have_count(0)


def show_error(page: Page) -> None:
    """Fail a plot so that an error toast opens."""
    page.route("**/api/plot", fail)
    place(page, "x", "x")
    drop(page, "y", "y")
    expect(page.locator("#toasts .toast")).to_have_count(1)


def test_a_toast_waits_while_hovered(app_page: Page) -> None:
    """The toast's 10 s stop while the pointer is on it, and go on with the time left."""
    page = app_page
    page.clock.install()
    show_error(page)
    toast = page.locator("#toasts .toast")

    toast.hover()
    page.clock.run_for(15000)
    expect(toast).to_have_count(1)

    page.mouse.move(5, 300)
    page.clock.run_for(5000)
    expect(toast).to_have_count(1)
    page.clock.run_for(6000)
    expect(toast).to_have_count(0)


MOVES = """async () => {
  const { Toasts } = await import("/static/js/notice.js");
  const toasts = new Toasts(document.getElementById("toasts"));
  toasts.show("a");
  const toast = document.querySelector("#toasts .toast");
  const transitions = () => toast.getAnimations().map(a => a.transitionProperty).sort();
  const entering = transitions();
  for (const animation of toast.getAnimations()) animation.finish();
  toast.querySelector(".toast-close").click();
  return [entering, transitions()];
}"""


def test_a_toast_moves_only_without_reduced_motion(app_page: Page) -> None:
    """Toasts slide in and out, but only fade when the OS turns animation effects off."""
    page = app_page
    for motion, expected in [
        ("no-preference", ["opacity", "transform"]),
        ("reduce", ["opacity"]),
    ]:
        page.emulate_media(reduced_motion=motion)  # type: ignore[arg-type]
        entering, leaving = page.evaluate(MOVES)
        assert entering == expected, motion
        assert leaving == expected, motion
        expect(page.locator("#toasts .toast")).to_have_count(0)


# Shows the desktop window's toast of a save alone, lets it come in, and returns
# the gaps of the toast to the page's right edge and to what is above it: the
# title bar's bottom in the window, the page's top in a browser.
GAPS = """() => {
  document.getElementById("toasts").replaceChildren();
  window.ddvizSaved({ saved: "a.csv" });
  const toast = document.querySelector("#toasts .toast");
  for (const animation of toast.getAnimations()) animation.finish();
  const box = toast.getBoundingClientRect();
  const bar = document.getElementById("titlebar");
  const above = bar && getComputedStyle(bar).display !== "none" ? bar.getBoundingClientRect().bottom : 0;
  return [document.documentElement.clientWidth - box.right, box.top - above];
}"""


def test_a_toast_is_12_px_from_the_top_right_in_a_browser(app_page: Page) -> None:
    """In a browser (`--port`), the toast is 12 CSS px from the page's top and right."""
    page = app_page
    expect(page.locator("#titlebar")).to_have_count(0)
    right, top = page.evaluate(GAPS)
    assert right == pytest.approx(12, abs=0.5)
    assert top == pytest.approx(12, abs=0.5)
    expect(page.locator("#toasts .toast")).to_have_text("ダウンロードに保存しました（a.csv）×")


@pytest.mark.parametrize("desktop", [True])
def test_a_toast_is_12_px_below_the_title_bar_in_the_window(app_page: Page) -> None:
    """In the window, the toast is 12 CSS px below the title bar, also when the row's height changes (maximized, another scale)."""
    page = app_page
    bar = page.locator("#titlebar")
    expect(bar).to_be_visible()
    for row in [30, 45, 22]:
        page.evaluate(
            "(row) => { window.ddvizCaption = [138, row]; window.ddvizCaptionChanged(); }", row
        )
        assert bar.evaluate("e => e.getBoundingClientRect().height") == pytest.approx(row)
        right, top = page.evaluate(GAPS)
        assert right == pytest.approx(12, abs=0.5), row
        assert top == pytest.approx(12, abs=0.5), row
