"""E2E: the chips of several X and Y columns stand at the middle of their drawn axes, and drops follow the axes.

The checks compare positions measured on the page (the chips' boxes and
plotly's axes), never a width of text, so that they hold with the fonts of
any runner.
"""

from __future__ import annotations

import re

import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import (
    SETTLED,
    drawn_task,
    drop_at,
    new_result,
    place,
    watch_errors,
)

pytestmark = pytest.mark.e2e

# A name longer than any region a chip can take.
LONG = "long_" + "n" * 300

# Returns the spans along the axis (client coordinates) of the first `n`
# axes of a role in the figure, in order: X's of the leftmost panels, Y's of
# the top ones (distinct positions; matching panels below or right of them
# repeat them), and the spans of the role's chips; null without a figure.
SPANS = r"""([role, n]) => {
  const gd = document.getElementById("plot");
  const full = gd._fullLayout;
  if (!full) return null;
  const origin = gd.getBoundingClientRect();
  const x = role === "x";
  const at = new Map();
  for (const [key, axis] of Object.entries(full)) {
    if (!new RegExp(`^${role}axis\\d*$`).test(key) || !axis?._length) continue;
    at.set(Math.round(axis._offset), axis);
  }
  const base = x ? origin.left : origin.top;
  const axes = [...at.values()]
    .sort((a, b) => a._offset - b._offset)
    .slice(0, n)
    .map((a) => [base + a._offset, base + a._offset + a._length]);
  const chips = [...document.querySelectorAll(`.zone[data-role="${role}"] .chip`)].map((c) => {
    const r = c.getBoundingClientRect();
    return x ? [r.left, r.right] : [r.top, r.bottom];
  });
  return { axes, chips };
}"""

# The largest distance between the middle of a chip and the middle of its
# axis, or null while they do not pair up.
DEVIATION = (
    """([role, n]) => {
  const spans = ("""
    + SPANS
    + """)([role, n]);
  if (!spans || spans.axes.length !== n || spans.chips.length !== n) return null;
  const mid = ([s, e]) => (s + e) / 2;
  return Math.max(...spans.chips.map((c, i) => Math.abs(mid(c) - mid(spans.axes[i]))));
}"""
)

# The largest distance between the middle of a chip and the middle of its
# equal region of the zone.
EQUAL_DEVIATION = """(role) => {
  const zone = document.querySelector(`.zone[data-role="${role}"]`);
  const r = zone.getBoundingClientRect();
  const x = role === "x";
  const [start, end] = x ? [r.left, r.right] : [r.top, r.bottom];
  const chips = [...zone.querySelectorAll(".chip")];
  const size = (end - start) / chips.length;
  return Math.max(...chips.map((c, i) => {
    const b = c.getBoundingClientRect();
    const mid = x ? (b.left + b.right) / 2 : (b.top + b.bottom) / 2;
    return Math.abs(mid - (start + (i + 0.5) * size));
  }));
}"""


@pytest.fixture
def scatter_frame(scatter_frame: pl.DataFrame) -> pl.DataFrame:
    """Return the shared frame with a numeric column of a long name."""
    return scatter_frame.with_columns(pl.col("y").alias(LONG))


def wait_aligned(page: Page, role: str, n: int) -> None:
    """Wait until the role's `n` chips stand at the middle of their axes, within 2 CSS px."""
    page.wait_for_function(
        f"(arg) => {{ const d = ({DEVIATION})(arg); return d !== null && d <= 2; }}",
        arg=[role, n],
    )


def spans(page: Page, role: str, n: int) -> dict:
    """Return the spans of the role's first `n` axes and of its chips."""
    return page.evaluate(SPANS, [role, n])


def new_plot(page: Page, task: str) -> None:
    """Wait for a plot after the result of `task` (`drawn_task`)."""
    new_result(page, task)
    page.wait_for_function(SETTLED)


def two_by_two(page: Page) -> None:
    """Place x and facet on X, and x and y on Y (top to bottom)."""
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    x_box = page.locator('.zone[data-role="x"]').bounding_box()
    drop_at(page, "facet", "x", x_box["width"] - 5, x_box["height"] / 2)
    y_box = page.locator('.zone[data-role="y"]').bounding_box()
    drop_at(page, "x", "y", y_box["width"] / 2, 5)
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text(["x", "facet"])
    expect(page.locator('.zone[data-role="y"] .chip-name')).to_have_text(["x", "y"])


def test_chips_stand_at_the_middle_of_their_axes(app_page: Page) -> None:
    """Two X and two Y columns put each chip at the middle of its axis, after a reorder and a resize too."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1280, "height": 800})
    two_by_two(page)
    wait_aligned(page, "x", 2)
    wait_aligned(page, "y", 2)
    # The chips of the names of other lengths share no middle: they follow their own axes.
    x_spans = spans(page, "x", 2)
    assert x_spans["axes"][0][1] < x_spans["axes"][1][0] + 2

    # A reorder: the first chip dropped on the middle of the second swaps them.
    task = drawn_task(page)
    x_chips = page.locator('.zone[data-role="x"] .chip')
    x_chips.nth(0).drag_to(x_chips.nth(1))
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text(["facet", "x"])
    new_plot(page, task)
    wait_aligned(page, "x", 2)
    wait_aligned(page, "y", 2)

    # A resize draws the figure again at the new size.
    before = spans(page, "x", 2)["axes"]
    page.set_viewport_size({"width": 1100, "height": 700})
    page.wait_for_function(
        f"(b) => {{ const s = ({SPANS})(['x', 2]); return s && Math.abs(s.axes[1][1] - b[1][1]) > 20; }}",
        arg=before,
    )
    page.wait_for_function(SETTLED)
    wait_aligned(page, "x", 2)
    wait_aligned(page, "y", 2)
    assert errors == []


def test_chips_follow_the_first_facet_and_the_filter(app_page: Page) -> None:
    """With Group X and Group Y of two levels, each column keeps one chip at the leftmost (top) facet's axis; a filter that drops that facet moves the chips to the next."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1280, "height": 800})
    two_by_two(page)
    place(page, "facet", "col")
    place(page, "facet", "row")
    expect(page.locator('.zone[data-role="x"] .chip')).to_have_count(2)
    expect(page.locator('.zone[data-role="y"] .chip')).to_have_count(2)
    wait_aligned(page, "x", 2)
    wait_aligned(page, "y", 2)
    first = spans(page, "x", 2)["axes"]
    # The axes of the second facet column lie right of the chips.
    x_zone = page.locator('.zone[data-role="x"]').bounding_box()
    assert first[1][1] < x_zone["x"] + x_zone["width"] * 0.6

    # Keep only the second level: its panels are the first ones now.
    task = drawn_task(page)
    page.locator("#columns .column").filter(
        has=page.get_by_text("facet", exact=True)
    ).drag_to(page.locator("#filters"))
    levels = page.locator(".filter-card .filter-level")
    levels.filter(has=page.get_by_text("q", exact=True)).locator("input").check()
    new_plot(page, task)
    page.wait_for_function(
        f"(b) => {{ const s = ({SPANS})(['x', 2]); return s && Math.abs(s.axes[1][1] - b[1][1]) > 20; }}",
        arg=first,
    )
    wait_aligned(page, "x", 2)
    wait_aligned(page, "y", 2)
    expect(page.locator('.zone[data-role="x"] .chip')).to_have_count(2)
    assert errors == []


def test_a_direction_that_scrolls_spreads_its_chips_evenly(app_page: Page) -> None:
    """When only X scrolls, its chips stand at the middles of equal regions and stay there on a scroll; Y's follow their axes; X takes the drops of equal regions."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 900, "height": 800})
    two_by_two(page)
    place(page, "facet", "col")
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    scroller = page.locator("#scroller")
    assert scroller.evaluate("(s) => s.scrollWidth > s.clientWidth")
    assert scroller.evaluate("(s) => s.scrollHeight <= s.clientHeight")
    wait_aligned(page, "y", 2)
    page.wait_for_function(f"() => ({EQUAL_DEVIATION})('x') <= 2")
    chips = page.locator('.zone[data-role="x"] .chip')
    before = [chips.nth(i).bounding_box() for i in range(2)]
    scroller.evaluate("(s) => { s.scrollLeft = s.scrollWidth; }")
    page.wait_for_timeout(200)
    assert [chips.nth(i).bounding_box() for i in range(2)] == before
    wait_aligned(page, "y", 2)

    # The middle of the second equal region replaces the second column.
    zone = page.locator('.zone[data-role="x"]').bounding_box()
    drop_at(page, "color", "x", zone["width"] * 0.75, zone["height"] / 2)
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text(["x", "color"])
    assert errors == []


def test_drops_on_aligned_axes_follow_the_axes(app_page: Page) -> None:
    """Over drawn axes, the middle of an axis replaces its column, the gap between two goes in between, and the room before the first and after the last goes in first and last; the tip, the outline and the line agree."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1280, "height": 800})
    two_by_two(page)
    place(page, "facet", "col")
    wait_aligned(page, "x", 2)
    wait_aligned(page, "y", 2)
    x_zone = page.locator('.zone[data-role="x"]')
    zone = x_zone.bounding_box()
    middle = zone["y"] + zone["height"] / 2
    axes = spans(page, "x", 2)["axes"]
    chips = spans(page, "x", 2)["chips"]
    tip = page.locator("#drop-tip")
    line = page.locator("#drop-line")
    source = page.locator("#columns .column").filter(
        has=page.get_by_text("color", exact=True)
    )
    data = page.evaluate_handle("() => new DataTransfer()")
    source.dispatch_event("dragstart", {"dataTransfer": data})

    def over(at: float) -> None:
        x_zone.dispatch_event(
            "dragover", {"dataTransfer": data, "clientX": at, "clientY": middle}
        )

    def mid(span: list[float]) -> float:
        return (span[0] + span[1]) / 2

    # The middle of the second axis outlines its chip.
    over(mid(axes[1]))
    expect(tip).to_have_text("X の facet を置き換える")
    expect(x_zone.locator(".chip").nth(1)).to_have_class(re.compile(r"\btarget\b"))
    expect(line).to_be_hidden()
    # The last quarter of the first axis's region goes in between, with the line between the chips.
    over(axes[0][1] - 2)
    expect(tip).to_have_text("X の facet の左に第 2 軸として挿入")
    expect(x_zone.locator(".chip.target")).to_have_count(0)
    box = line.bounding_box()
    assert chips[0][1] <= box["x"] and box["x"] + box["width"] <= chips[1][0]
    # The margin left of the first axis goes in first, left of the first chip.
    over(axes[0][0] - 5)
    expect(tip).to_have_text("X の x の左に第 1 軸として挿入")
    box = line.bounding_box()
    assert box["x"] + box["width"] <= chips[0][0]
    # The room of the second facet column goes in last, right of the last chip.
    over(zone["x"] + zone["width"] - 10)
    expect(tip).to_have_text("X の facet の右に第 3 軸として挿入")
    box = line.bounding_box()
    assert chips[1][1] <= box["x"]
    page.evaluate("() => document.dispatchEvent(new DragEvent('dragend'))")

    # The drops do what the marks said (without Group X, so that more axes still fit).
    task = drawn_task(page)
    page.locator('.zone[data-role="col"] .chip-remove').click()
    new_plot(page, task)
    wait_aligned(page, "x", 2)
    axes = spans(page, "x", 2)["axes"]
    drop_at(page, "color", "x", mid(axes[1]) - zone["x"], zone["height"] / 2)
    expect(x_zone.locator(".chip-name")).to_have_text(["x", "color"])
    wait_aligned(page, "x", 2)
    axes = spans(page, "x", 2)["axes"]
    drop_at(page, "y", "x", axes[0][0] - 5 - zone["x"], zone["height"] / 2)
    expect(x_zone.locator(".chip-name")).to_have_text(["y", "x", "color"])
    wait_aligned(page, "x", 3)
    axes = spans(page, "x", 3)["axes"]
    drop_at(page, "facet", "x", (axes[0][1] + axes[1][0]) / 2 - zone["x"], zone["height"] / 2)
    expect(x_zone.locator(".chip-name")).to_have_text(["y", "facet", "x", "color"])

    # Y: the margin above the first axis goes in first; the middle of the second replaces it.
    wait_aligned(page, "y", 2)
    y_zone = page.locator('.zone[data-role="y"]')
    y_box = y_zone.bounding_box()
    y_axes = spans(page, "y", 2)["axes"]
    drop_at(page, "facet", "y", y_box["width"] / 2, mid(y_axes[1]) - y_box["y"])
    expect(y_zone.locator(".chip-name")).to_have_text(["x", "facet"])
    wait_aligned(page, "y", 2)
    drop_at(page, "y", "y", y_box["width"] / 2, y_axes[0][0] - 5 - y_box["y"])
    expect(y_zone.locator(".chip-name")).to_have_text(["y", "x", "facet"])
    wait_aligned(page, "y", 3)
    assert errors == []


def test_long_chips_fit_their_regions_and_chips_without_a_figure(
    app_page: Page,
) -> None:
    """A long name is cut within its region and its × and drag still work; without a figure two chips spread evenly, one is centered and none shows the zone's name."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1280, "height": 800})
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    x_zone = page.locator('.zone[data-role="x"]')
    y_zone = page.locator('.zone[data-role="y"]')
    expect(x_zone.locator(".zone-label")).to_be_visible()

    # No figure (Y is empty): one chip is centered, two spread evenly.
    place(page, "x", "x")
    zone = x_zone.bounding_box()
    chip = x_zone.locator(".chip").bounding_box()
    assert abs(chip["x"] + chip["width"] / 2 - (zone["x"] + zone["width"] / 2)) <= 2
    drop_at_no_plot = x_zone.bounding_box()
    page.locator("#columns .column").filter(
        has=page.get_by_text(LONG, exact=True)
    ).drag_to(
        x_zone,
        target_position={"x": drop_at_no_plot["width"] - 5, "y": drop_at_no_plot["height"] / 2},
    )
    expect(x_zone.locator(".chip-name")).to_have_text(["x", LONG])
    page.wait_for_function(f"() => ({EQUAL_DEVIATION})('x') <= 2")

    # With a figure, the long chip keeps to its axis's region, cut short.
    place(page, "y", "y")
    y_box = y_zone.bounding_box()
    drop_at(page, LONG, "y", y_box["width"] / 2, y_box["height"] - 5)
    expect(y_zone.locator(".chip-name")).to_have_text(["y", LONG])
    wait_aligned(page, "x", 2)
    wait_aligned(page, "y", 2)
    for role in ["x", "y"]:
        s = spans(page, role, 2)
        boundary = (s["axes"][0][1] + s["axes"][1][0]) / 2
        assert s["chips"][0][1] <= boundary <= s["chips"][1][0]
        assert s["chips"][1][1] <= s["axes"][1][1] + 1
        name = page.locator(f'.zone[data-role="{role}"] .chip-name').nth(1)
        assert name.evaluate(
            "(n) => n.scrollWidth > n.clientWidth || n.scrollHeight > n.clientHeight"
        )

    # Its × removes it, and a drag of it swaps it with the first.
    task = drawn_task(page)
    y_zone.locator(".chip").nth(1).locator(".chip-remove").click()
    expect(y_zone.locator(".chip-name")).to_have_text(["y"])
    new_plot(page, task)
    task = drawn_task(page)
    x_chips = x_zone.locator(".chip")
    x_chips.nth(1).drag_to(x_chips.nth(0))
    expect(x_zone.locator(".chip-name")).to_have_text([LONG, "x"])
    new_plot(page, task)
    wait_aligned(page, "x", 2)
    assert errors == []
