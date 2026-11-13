"""JS: memory.js writes the memory in its units and fetches it about once a second, one request at a time."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

BOTH = {"backend_bytes": 440401920, "frontend_bytes": 1342177280}

# Starts a MemoryMeter on two new spans with `fetch` replaced: each request
# waits in `window.held` until the test answers it (`ANSWER`).
START = """async () => {
  const { MemoryMeter } = await import("/static/js/memory.js");
  window.spans = [document.createElement("span"), document.createElement("span")];
  window.held = [];
  window.fetch = () => new Promise((resolve) => window.held.push(resolve));
  new MemoryMeter(...window.spans).fetch();
}"""

# Answers the request `index` with `body` (a failure when null), lets its
# handling run and returns the two texts.
ANSWER = """async ({ index, body }) => {
  const ok = body !== null;
  window.held[index]({ ok, json: async () => body });
  for (let i = 0; i < 10; i++) await Promise.resolve();
  return window.spans.map((s) => s.textContent);
}"""


def test_both_sides_show_in_their_units(js_page: Page) -> None:
    """Under 1 GiB in whole MiB (never 1024), from 1 GiB in GiB with two decimals, unknown as "—"."""
    texts = js_page.evaluate(
        """async () => {
          const { memoryText } = await import("/static/js/memory.js");
          return [0, 1048575, 1073741823, 1073741824, 440401920, 1342177280,
                  null, undefined, -1, NaN, Infinity, "1"].map(memoryText);
        }"""
    )
    assert texts == [
        "0 MiB", "1 MiB", "1023 MiB", "1.00 GiB", "420 MiB", "1.25 GiB",
        "—", "—", "—", "—", "—", "—",
    ]


def test_a_failed_fetch_shows_dashes_and_the_next_one_recovers(clock_page: Page) -> None:
    """A failed request shows both as "—"; the next good answer, a second later, shows the values."""
    page = clock_page
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    page.evaluate(START)
    assert page.evaluate(ANSWER, {"index": 0, "body": None}) == ["—", "—"]
    page.evaluate("() => { window.held[0] = null; }")
    page.clock.run_for(999)
    assert page.evaluate("window.held.length") == 1
    page.clock.run_for(1)
    assert page.evaluate("window.held.length") == 2
    assert page.evaluate(ANSWER, {"index": 1, "body": BOTH}) == ["420 MiB", "1.25 GiB"]


def test_no_request_starts_while_one_is_pending(clock_page: Page) -> None:
    """A slow request holds the next; once it ends, one request follows at once, not a backlog, then one a second."""
    page = clock_page
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    page.evaluate(START)
    page.clock.run_for(3500)
    assert page.evaluate("window.held.length") == 1
    assert page.evaluate(ANSWER, {"index": 0, "body": BOTH}) == ["420 MiB", "1.25 GiB"]
    # Its second had passed: the next starts at once.
    page.clock.run_for(0)
    assert page.evaluate("window.held.length") == 2
    page.evaluate(ANSWER, {"index": 1, "body": BOTH})
    page.clock.run_for(1500)
    assert page.evaluate("window.held.length") == 3
