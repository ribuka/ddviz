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


# Tells `results` as the desktop window does (`showSaveResult`), in a new
# container (`window.box`).
SAVED = """async (results) => {
  const { Toasts, showSaveResult } = await import("/static/js/notice.js");
  window.box = document.createElement("div");
  document.body.append(window.box);
  const toasts = new Toasts(window.box);
  for (const result of results) showSaveResult(toasts, result);
}"""

# The text, role and classes of each toast that is not leaving.
LOOKS = """() => [...window.box.querySelectorAll(".toast:not(.toast-leaving)")].map((t) => [
  t.querySelector(".toast-text").textContent, t.getAttribute("role"), t.className,
])"""

POINTER = """(type) => window.box.querySelector(".toast").dispatchEvent(new MouseEvent(type))"""


def test_a_save_tells_its_name_or_its_error(js_page: Page) -> None:
    """A save shows its name as a plain status; a failed one shows why as an error alert."""
    js_page.evaluate(SAVED, [{"saved": "a (1).csv"}, {"error": "ディスクの空きが足りません。"}])
    assert js_page.evaluate(LOOKS) == [
        ["ダウンロードに保存しました（a (1).csv）", "status", "toast toast-success"],
        ["保存できませんでした：ディスクの空きが足りません。", "alert", "toast notice-error"],
    ]


def test_a_success_leaves_after_7_s_and_an_error_after_10_s(clock_page: Page) -> None:
    """The success's toast starts leaving at 7,000 ms, the error's at 10,000 ms."""
    page = clock_page
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    page.evaluate(SAVED, [{"saved": "a.csv"}])
    page.clock.run_for(6999)
    assert len(page.evaluate(LOOKS)) == 1
    page.clock.run_for(1)
    assert page.evaluate(LOOKS) == []

    page.evaluate(SAVED, [{"error": "x"}])
    page.clock.run_for(9999)
    assert len(page.evaluate(LOOKS)) == 1
    page.clock.run_for(1)
    assert page.evaluate(LOOKS) == []


def test_a_success_waits_while_hovered_or_hidden(clock_page: Page) -> None:
    """The success's 7 s stop while the pointer is on it or the window is hidden, and go on with the time left once both end."""
    page = clock_page
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    page.evaluate(SAVED, [{"saved": "a.csv"}])
    page.clock.run_for(2000)
    page.evaluate(POINTER, "mouseenter")
    page.clock.run_for(20000)
    page.evaluate(HIDE, True)
    page.evaluate(POINTER, "mouseleave")
    page.clock.run_for(20000)  # still hidden
    assert len(page.evaluate(LOOKS)) == 1
    page.evaluate(HIDE, False)
    page.clock.run_for(4999)
    assert len(page.evaluate(LOOKS)) == 1
    page.clock.run_for(1)
    assert page.evaluate(LOOKS) == []


def test_a_success_closes_by_its_button(js_page: Page) -> None:
    """The close button takes the success's toast away at once."""
    js_page.evaluate(SAVED, [{"saved": "a.csv"}])
    js_page.evaluate("() => window.box.querySelector('.toast-success .toast-close').click()")
    assert js_page.evaluate(LOOKS) == []
