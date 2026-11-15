"""JS: dragresize.js starts a drag on a press of the primary button only, and ends it on pointerup or pointercancel."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# Places a fixed handle of 100 x 100 px at (0, 0) as `window.handle`, and
# attaches a drag whose calls count in `window.counts`; `window.pointerId` is
# the pointer of the last press.
ATTACH = """async () => {
  const { attachDrag } = await import("/static/js/dragresize.js");
  window.counts = { start: 0, move: 0, end: 0 };
  window.handle = document.createElement("div");
  window.handle.style.cssText = "position: fixed; left: 0; top: 0; width: 100px; height: 100px";
  document.body.append(window.handle);
  attachDrag(window.handle, (event) => {
    window.counts.start += 1;
    window.pointerId = event.pointerId;
    return { move: () => { window.counts.move += 1; }, end: () => { window.counts.end += 1; } };
  });
}"""

COUNTS = "() => window.counts"


@pytest.fixture
def page(js_page: Page) -> Iterator[Page]:
    """Return the page with the handle, removed at the end."""
    js_page.evaluate(ATTACH)
    js_page.mouse.move(50, 50)
    yield js_page
    js_page.mouse.up()
    js_page.evaluate("() => window.handle.remove()")


def test_a_drag_moves_until_pointerup(page: Page) -> None:
    """A press of the left button and moves call `move`; pointerup calls `end` once, and later moves call nothing."""
    page.mouse.down()
    page.mouse.move(50, 30)
    page.mouse.move(50, 10)
    counts = page.evaluate(COUNTS)
    assert counts["start"] == 1
    assert counts["move"] >= 1
    assert counts["end"] == 0
    page.mouse.up()
    moved = page.evaluate(COUNTS)["move"]
    assert page.evaluate(COUNTS)["end"] == 1
    page.mouse.move(50, 60)
    assert page.evaluate(COUNTS) == {"start": 1, "move": moved, "end": 1}


def test_the_right_button_starts_no_drag(page: Page) -> None:
    """A press of the right button does not call `start`."""
    page.mouse.down(button="right")
    page.mouse.move(50, 30)
    assert page.evaluate(COUNTS) == {"start": 0, "move": 0, "end": 0}
    page.mouse.up(button="right")


def test_pointercancel_ends_the_drag(page: Page) -> None:
    """A pointercancel after a press and moves calls `end` once, and later moves call nothing."""
    page.mouse.down()
    page.mouse.move(50, 30)
    page.evaluate(
        """() => window.handle.dispatchEvent(
          new PointerEvent("pointercancel", { pointerId: window.pointerId }))"""
    )
    counts = page.evaluate(COUNTS)
    assert counts["end"] == 1
    assert counts["move"] >= 1
    page.mouse.move(50, 10)
    assert page.evaluate(COUNTS) == counts
