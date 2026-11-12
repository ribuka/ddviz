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


def test_a_toast_waits_while_the_window_is_hidden(app_page: Page) -> None:
    """The toast's 10 s stop while the window is hidden (`document.hidden`)."""
    page = app_page
    page.clock.install()
    page.mouse.move(5, 300)
    show_error(page)
    toast = page.locator("#toasts .toast")

    hide = """hidden => {
      Object.defineProperty(document, "hidden", {configurable: true, get: () => hidden});
      document.dispatchEvent(new Event("visibilitychange"));
    }"""
    page.evaluate(hide, True)
    page.clock.run_for(15000)
    expect(toast).to_have_count(1)

    page.evaluate(hide, False)
    page.clock.run_for(11000)
    expect(toast).to_have_count(0)


TOASTS = """async texts => {
  const { Toasts } = await import("/static/js/notice.js");
  const toasts = new Toasts(document.getElementById("toasts"));
  for (const text of texts) toasts.show(text);
}"""


def test_leaving_toasts_are_not_counted(app_page: Page) -> None:
    """A fourth toast closes the oldest, and the same text again replaces its toast."""
    page = app_page
    page.evaluate(TOASTS, ["a", "b", "c", "d", "b"])
    shown = page.locator("#toasts .toast:not(.toast-leaving)")
    expect(shown).to_have_count(3)
    assert [t.get_attribute("data-text") for t in shown.all()] == ["c", "d", "b"]
    expect(page.locator("#toasts .toast")).to_have_count(3)


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
