"""E2E: the left margin grows to show the y tick labels whole, and shrinks back for short ones."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import (
    PAINTED_PIXEL,
    SCROLL_AND_SETTLE,
    SETTLED,
    drop_at,
    place,
    watch_errors,
)

pytestmark = pytest.mark.e2e

ROWS = 2_000
FULL = "document.getElementById('plot')._fullLayout"
# The requests that aggregate a result.
AGGREGATING = re.compile(r"/api/(plot|view|overview)\b")
LONG_NAME = "category_name_0_" + "x" * 30

# The y tick labels shown on the left of the figure: plotly's of a grid that
# fits (the text of each y axis's ``y<n>tick`` groups), or the left strip's of
# one that scrolls, with their boxes and the left edge of the figure (or of
# the strip) they must stay right of.
Y_LABELS = r"""() => {
  const gd = document.getElementById("plot");
  const strip = document.querySelector(".sticky-labels:not([hidden]) .sticky-strip.left");
  const els = strip
    ? [...strip.querySelectorAll(".tick.y")]
    : [...gd.querySelectorAll("g > text")].filter((t) => /^y\d*tick$/.test(t.parentNode.getAttribute("class")));
  const edge = (strip ?? gd).getBoundingClientRect();
  return {
    margin: gd._fullLayout.margin.l,
    scroll: Boolean(strip),
    edge: { left: edge.left, right: edge.right, top: edge.top, bottom: edge.bottom },
    labels: els
      .map((e) => {
        const r = e.getBoundingClientRect();
        return { text: e.textContent, left: r.left, right: r.right, top: r.top, bottom: r.bottom };
      })
      .filter((l) => l.right > l.left),
  };
}"""


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write repayments of about 94,000 to 106,000, long negatives, times and facets (overrides the shared data)."""
    rng = np.random.default_rng(104)
    n = np.arange(ROWS)
    start = datetime(2024, 1, 1, 12)  # noqa: DTZ001
    path = tmp_path / "repay.parquet"
    pl.DataFrame(
        {
            "n": n,
            "pay": 94_000 + 12_000 * rng.random(ROWS),
            # Ticks of many digits (1.00020e+5), wider than 50 pixels in any font.
            "fine": 100_000 + 40 * rng.random(ROWS),
            "interest": -1_234_567.891 - 0.002 * rng.random(ROWS),
            "small": rng.random(ROWS),
            "when": [start + timedelta(milliseconds=int(i)) for i in n],
            "name": [f"category_name_{i % 5}_" + "x" * 30 for i in n],
            "facet": [f"f{i % 12:02d}" for i in n],
            "g": [f"g{i % 8}" for i in n],
        }
    ).write_parquet(path)
    return path


def y_labels(page: Page) -> dict:
    """Return the y tick labels on the left of the figure, the margin and whether the grid scrolls."""
    return page.evaluate(Y_LABELS)


def assert_whole(shown: dict) -> None:
    """Check that every y label lies right of the figure's (or the strip's) left edge, 2 pixels or more."""
    assert shown["labels"]
    for label in shown["labels"]:
        assert label["left"] >= shown["edge"]["left"] + 2 - 0.5, (label, shown["edge"])
        if shown["scroll"]:
            assert label["right"] <= shown["edge"]["right"], (label, shown["edge"])


def settle(page: Page) -> None:
    """Wait for the results of the margin's requests: the status settled and the margin stays."""
    for _ in range(20):
        page.wait_for_timeout(600)
        page.wait_for_function(SETTLED)
        before = y_labels(page)["margin"]
        page.wait_for_timeout(600)
        page.wait_for_function(SETTLED)
        if y_labels(page)["margin"] == before:
            return
    raise AssertionError("the margin did not settle")


def record(page: Page) -> list[str]:
    """Record the URLs of the requests that aggregate a result from now on."""
    urls: list[str] = []
    page.on(
        "request",
        lambda request: AGGREGATING.search(request.url) and urls.append(request.url),
    )
    return urls


def x_labels(page: Page) -> list[str]:
    """Return the texts of plotly's x tick labels, of any x axis (``x<n>tick``)."""
    return page.evaluate(
        r"""() => [...document.querySelectorAll("#plot g > text")]
          .filter((t) => /^x\d*tick$/.test(t.parentNode.getAttribute("class")))
          .map((t) => t.textContent)"""
    )


def place_second_y(page: Page, column: str) -> None:
    """Drop a column below the Y zone's first axis column: a second panel row."""
    zone = page.locator('.zone[data-role="y"]').bounding_box()
    drop_at(page, column, "y", zone["width"] / 2, zone["height"] * 0.95)


def assert_aligned(page: Page, painted: bool = True) -> None:
    """Check that the plot area starts at the margin and the images paint inside it."""
    full = page.evaluate(
        f"() => {{ const f = {FULL}; return {{ l: f.margin.l, offset: f.xaxis._offset }}; }}"
    )
    assert full["offset"] == full["l"]
    if not painted:
        return
    pixel = page.evaluate(PAINTED_PIXEL)
    assert pixel is not None
    left = page.locator("#plot").bounding_box()["x"] + full["l"]
    assert pixel["x"] >= left


def test_long_y_labels_of_two_rows_show_whole(app_page: Page) -> None:
    """Amounts of 1.06e+5 and long negatives on two Y rows show from their first character, in a wider margin."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x", plots=False)
    place(page, "pay", "y")
    place_second_y(page, "interest")
    settle(page)
    shown = y_labels(page)
    assert shown["margin"] > 50
    texts = [label["text"] for label in shown["labels"]]
    assert "1.06e+5" in texts, texts
    assert any(t.startswith("−") and len(t) > 10 for t in texts), texts
    assert_whole(shown)
    assert_aligned(page)
    assert not errors


def test_short_labels_keep_50_grow_when_zoomed_and_shrink_back(app_page: Page) -> None:
    """Short labels keep 50 pixels with no request for the margin; long ones of a zoom widen it, and the overview narrows it again."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x", plots=False)
    place(page, "small", "y")
    settle(page)
    assert y_labels(page)["margin"] == 50
    urls = record(page)

    # A zoom of x keeps the margin: one view, nothing for the margin.
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [100, 500]})")
    settle(page)
    assert y_labels(page)["margin"] == 50
    assert len(urls) == 1 and "/api/view" in urls[0], urls

    # A deep zoom of y has long labels: the margin grows to them.
    page.evaluate("Plotly.relayout('plot', {'yaxis.range': [0.12345671, 0.12345679]})")
    settle(page)
    shown = y_labels(page)
    assert shown["margin"] > 60
    assert_whole(shown)
    # No row lies in the zoomed range of y.
    assert_aligned(page, painted=False)

    # Back to the overview: short labels, the margin of 50 again.
    page.evaluate(
        "Plotly.relayout('plot', {'xaxis.autorange': true, 'yaxis.autorange': true})"
    )
    page.wait_for_function(f"() => {FULL}.margin.l === 50")
    settle(page)
    shown = y_labels(page)
    assert shown["margin"] == 50
    # The overview kept is drawn at its margin: nothing is aggregated again.
    assert not [u for u in urls if "/api/overview" in u], urls
    assert_whole(shown)
    assert not errors


def test_a_scrolled_grid_keeps_the_labels_in_its_strip(app_page: Page) -> None:
    """A grid that scrolls both ways has the long labels of every row whole in the left strip, and its strip opens the axis menu."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 900, "height": 700})
    place(page, "n", "x", plots=False)
    place(page, "fine", "y")
    place(page, "facet", "row")
    place(page, "g", "col")
    settle(page)
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    shown = y_labels(page)
    assert shown["scroll"]
    assert shown["margin"] > 50
    # The strip has plotly's text, with the exponent.
    assert all("e+5" in label["text"] for label in shown["labels"])
    assert_whole(shown)
    scroller = page.locator("#scroller")
    scroller.evaluate(SCROLL_AND_SETTLE, 10_000)
    scroller.evaluate(
        "async (s) => { s.scrollTop = 10000; s.dispatchEvent(new Event('scroll'));"
        " for (let i = 0; i < 2; i++) await new Promise((r) => requestAnimationFrame(r)); }"
    )
    assert scroller.evaluate("(s) => s.scrollLeft") > 0
    assert scroller.evaluate("(s) => s.scrollTop") > 0
    shown = y_labels(page)
    in_sight = [
        label
        for label in shown["labels"]
        if shown["edge"]["top"] <= label["top"] <= shown["edge"]["bottom"]
    ]
    assert in_sight
    assert_whole(shown)

    tick = in_sight[len(in_sight) // 2]
    page.mouse.click(
        (tick["left"] + tick["right"]) / 2,
        (tick["top"] + tick["bottom"]) / 2,
        button="right",
    )
    menu = page.locator(".axis-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text("Y 軸: fine")
    page.keyboard.press("Escape")
    assert not errors


def test_times_and_a_log_axis_show_whole(app_page: Page) -> None:
    """Labels of milliseconds and of a log axis show whole."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x", plots=False)
    place(page, "when", "y")
    settle(page)
    shown = y_labels(page)
    assert any(":" in label["text"] for label in shown["labels"])
    assert_whole(shown)

    place(page, "fine", "y")
    settle(page)
    ticks = page.locator("#plot .ytick text")
    box = ticks.nth(ticks.count() // 2).bounding_box()
    page.mouse.click(
        box["x"] + box["width"] - 6, box["y"] + box["height"] / 2, button="right"
    )
    page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    page.wait_for_function(f"() => {FULL}.yaxis.type === 'log'")
    settle(page)
    shown = y_labels(page)
    assert shown["margin"] > 50
    assert_whole(shown)
    assert not errors


def test_a_categorical_y_keeps_its_cut_labels_beside_a_numeric_one(
    app_page: Page,
) -> None:
    """A categorical Y keeps its labels cut to 44 pixels, and the margin is the numeric Y's; X's labels stay."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x", plots=False)
    place(page, "name", "y")
    settle(page)
    assert y_labels(page)["margin"] == 50
    texts = [label["text"] for label in y_labels(page)["labels"]]
    assert texts and all(t.endswith("…") for t in texts), texts
    x_before = x_labels(page)

    place_second_y(page, "interest")
    settle(page)
    shown = y_labels(page)
    assert shown["margin"] > 50
    numeric = [label for label in shown["labels"] if label["text"].startswith("−")]
    assert numeric
    for label in numeric:
        assert label["left"] >= shown["edge"]["left"] + 2 - 0.5
    cut = [label for label in shown["labels"] if label["text"].endswith("…")]
    assert cut
    for label in cut:
        assert LONG_NAME.startswith(label["text"].removesuffix("…")[:10])
        assert label["right"] - label["left"] <= 44 + 1
    assert x_labels(page) == x_before
    assert not errors


def test_a_wider_margin_that_scrolls_keeps_the_drawing_aligned(
    app_page: Page,
) -> None:
    """A margin that no longer lets the panels fit makes the grid scroll; the frames, the images and the hover stay together, and back to short labels it fits again."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x", plots=False)
    place(page, "small", "y")
    place(page, "g", "col")
    settle(page)
    # The area holds the 8 panels at their smallest with the margin of 50,
    # and 4 pixels to spare.
    stage = page.locator("#stage").evaluate("(s) => s.clientWidth")
    fits = 50 + 30 + 8 * 160 + 7 + 4
    page.set_viewport_size({"width": 1200 + fits - stage, "height": 800})
    page.wait_for_function(
        f"() => document.getElementById('stage').clientWidth === {fits}"
    )
    settle(page)
    assert not y_labels(page)["scroll"]
    assert y_labels(page)["margin"] == 50

    # Amounts need a wider margin: the panels no longer fit, and scroll.
    place(page, "fine", "y")
    settle(page)
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    shown = y_labels(page)
    assert shown["scroll"]
    assert shown["margin"] > 54
    assert_whole(shown)
    assert_aligned(page)
    pixel = page.evaluate(PAINTED_PIXEL)
    page.mouse.move(pixel["x"], pixel["y"])
    label = page.locator("#hover-label")
    expect(label).to_be_visible()
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    assert 100_000 <= float(lines["fine"]) <= 100_040

    # Short labels again: the grid fits at 50.
    place(page, "small", "y")
    settle(page)
    expect(page.locator("#stage")).not_to_have_class(re.compile(r"\bscrolls\b"))
    shown = y_labels(page)
    assert shown["margin"] == 50
    assert_whole(shown)
    assert_aligned(page)
    assert not errors
