"""JS: notice.js keeps at most three toasts and stops their time while the window is hidden."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# Shows `texts` as toasts in a new container (`window.box`).
SHOW = """async (texts) => {
  const { Toasts } = await import("/static/js/notice.js");
  window.box = document.createElement("div");
  document.body.append(window.box);
  const toasts = new Toasts(window.box);
  for (const text of texts) toasts.show(text);
}"""

# Returns the texts of the toasts in the container, and of those not leaving.
TEXTS = """() => [
  [...window.box.querySelectorAll(".toast")].map((t) => t.dataset.text),
  [...window.box.querySelectorAll(".toast:not(.toast-leaving)")].map((t) => t.dataset.text),
]"""

HIDE = """(hidden) => {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event("visibilitychange"));
}"""


def test_a_toast_waits_while_the_window_is_hidden(clock_page: Page) -> None:
    """The toast's 10 s stop while the window is hidden (`document.hidden`) and go on with the time left."""
    page = clock_page
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    page.evaluate(SHOW, ["a"])
    page.clock.run_for(4000)
    page.evaluate(HIDE, True)
    page.clock.run_for(15000)
    assert page.evaluate(TEXTS)[1] == ["a"]
    page.evaluate(HIDE, False)
    page.clock.run_for(5900)
    assert page.evaluate(TEXTS)[1] == ["a"]
    page.clock.run_for(200)
    assert page.evaluate(TEXTS)[1] == []
    # It leaves the DOM after its exit.
    page.clock.run_for(150)
    assert page.evaluate(TEXTS)[0] == []


def test_leaving_toasts_are_not_counted(clock_page: Page) -> None:
    """A fourth toast closes the oldest, and the same text again replaces its toast; the leaving ones go after their exit."""
    page = clock_page
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    page.evaluate(SHOW, ["a", "b", "c", "d", "b"])
    everything, shown = page.evaluate(TEXTS)
    assert shown == ["c", "d", "b"]
    assert everything == ["a", "b", "c", "d", "b"]
    page.clock.run_for(150)
    assert page.evaluate(TEXTS) == [["c", "d", "b"], ["c", "d", "b"]]
