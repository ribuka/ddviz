"""E2E: a window shrunk until the plot area cannot be drawn raises nothing, and a wider one draws again (Issue #302)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.test_scatter import (
    drawn_task,
    new_result,
    place,
    wait_idle,
    watch_errors,
)

pytestmark = pytest.mark.e2e

# Longer than `RESIZE_SETTLE_MS` (300ms in app.js) after the last resize.
PAST_SETTLE_MS = 800
NARROW = {"width": 360, "height": 420}

# The size of the plot area, and the size the figure is laid out at.
SIZES = """() => {
  const stage = document.getElementById("stage");
  const full = document.getElementById("plot")._fullLayout;
  return {
    stage: [Math.floor(stage.clientWidth), Math.floor(stage.clientHeight)],
    figure: [full.width, full.height],
  };
}"""


def shrink(page: Page, errors: list[str]) -> None:
    """Shrink the window until the plot area is 0 wide, past the resize's settling, and check that nothing was raised."""
    page.set_viewport_size(NARROW)
    page.wait_for_timeout(PAST_SETTLE_MS)
    assert page.evaluate(SIZES)["stage"][0] == 0
    assert errors == []


def test_a_narrow_window_raises_nothing_and_draws_again(app_page: Page) -> None:
    """Shrunk to 360x420, the plot area too small to draw, no error comes; back at 1280x800 the overview is asked for at that size and laid out at it; at 1200x760 a new result is drawn; still with no error."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1280, "height": 800})
    place(page, "x", "x")
    place(page, "y", "y")
    before = page.evaluate(SIZES)
    task = drawn_task(page)

    shrink(page, errors)

    # Back at the size drawn: the server gives the drawn result back (the
    # same task), but the size is relaid out and asked for again.
    with page.expect_request("**/api/overview") as overview:
        page.set_viewport_size({"width": 1280, "height": 800})
    wait_idle(page)
    body = overview.value.post_data_json
    sizes = page.evaluate(SIZES)
    assert sizes["stage"] == before["stage"]
    assert [body["width"], body["height"]] == sizes["stage"]
    assert sizes["figure"] == sizes["stage"]
    assert errors == []

    shrink(page, errors)

    page.set_viewport_size({"width": 1200, "height": 760})
    new_result(page, task)
    wait_idle(page)
    sizes = page.evaluate(SIZES)
    assert sizes["figure"] == sizes["stage"]
    assert errors == []
