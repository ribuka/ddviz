"""E2E: lines joining the points, alone or under them (Issue #149)."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import (
    PAINTED_PIXEL,
    drawn_task,
    new_result,
    place,
    wait_idle,
)

pytestmark = pytest.mark.e2e

# The rows, in the file's order: x is not sorted. Joined in the order of x
# they zigzag between y 0 and 10.
X = [3.0, 1.0, 5.0, 2.0, 4.0]
Y = [0.0, 0.0, 0.0, 10.0, 10.0]


# Pairs of rows at the same x and y, one with a value of v and k and one
# without, and a row without them alone at (5, 1). k splits the lines by its
# levels: those of "a" and of the missing level both pass (2, 2), only the
# missing level's (4, 2). A gradient (v) joins every row in one line, the
# null rows too, each segment in the color of its first row: its segments of
# either level never cover the same pixels.
OVERLAP = {
    "x": [1.0, 3.0, 1.0, 3.0, 5.0],
    "y": [1.0, 3.0, 1.0, 3.0, 1.0],
    "v": [1.0, 2.0, None, None, None],
    "k": ["a", "a", None, None, None],
}


@pytest.fixture
def scatter_path(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """Write five rows of a numeric x and y, and a categorical column; or the columns of a test's `scatter_path` parameter."""
    columns = getattr(request, "param", None)
    frame = (
        pl.DataFrame(columns, schema_overrides={"v": pl.Float64})
        if columns
        else pl.DataFrame({"x": X, "y": Y, "g": ["a", "b", "a", "b", "a"]})
    )
    path = tmp_path / "lines.parquet"
    frame.write_parquet(path)
    return path


def icon(page: Page, name: str):  # noqa: ANN201 - a playwright Locator
    """Return the icon of an element."""
    return page.locator(f'#elements .element[data-element="{name}"]')


def at(page: Page, x: float, y: float) -> dict:
    """Return the page position of a data point of the first panel."""
    return page.evaluate(
        """([x, y]) => {
          const gd = document.getElementById("plot");
          const { xaxis, yaxis } = gd._fullLayout;
          const rect = gd.getBoundingClientRect();
          return { x: rect.left + xaxis._offset + xaxis.l2p(x),
                   y: rect.top + yaxis._offset + yaxis.l2p(y) };
        }""",
        [x, y],
    )


# The alphas of the image layers' canvas around a data point of the first
# panel, in a square of `r` CSS px.
ALPHAS_NEAR = """([x, y, r]) => {
  const full = document.getElementById("plot")._fullLayout;
  const canvas = document.querySelector("canvas.image-layers");
  const dpr = canvas.width / full.width;
  const px = Math.round((full.xaxis._offset + full.xaxis.l2p(x)) * dpr);
  const py = Math.round((full.yaxis._offset + full.yaxis.l2p(y)) * dpr);
  const side = Math.round(r * dpr);
  const { data } = canvas.getContext("2d").getImageData(px - side, py - side, 2 * side + 1, 2 * side + 1);
  return data.filter((_, i) => i % 4 === 3);
}"""


def opacity(page: Page, x: float, y: float) -> int:
    """Return the largest alpha painted around a data point."""
    return page.evaluate(f"(a) => Math.max(...({ALPHAS_NEAR})(a))", [x, y, 3])


def painted(page: Page, x: float, y: float, r: int = 3) -> int:
    """Return how many pixels are painted around a data point."""
    return page.evaluate(
        f"(a) => ({ALPHAS_NEAR})(a).filter((v) => v > 0).length", [x, y, r]
    )


def hover_lines(page: Page, x: float, y: float) -> dict[str, str] | None:
    """Hover at a data point; return the label's values of x and y, or None when it stays hidden."""
    page.mouse.move(0, 0)
    point = at(page, x, y)
    page.mouse.move(point["x"], point["y"])
    label = page.locator("#hover-label")
    try:
        expect(label).to_be_visible(timeout=1500)
    except AssertionError:
        return None
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    # The axis columns only: the row's index and the rows of the pixel aside.
    return {k: v for k, v in lines.items() if k in ("x", "y")}


def select_box(
    page: Page, corner: tuple[float, float], other: tuple[float, float], rows: int
) -> None:
    """Select the rows in a box between two data points, wait for the table to count `rows`, and fold it."""
    page.evaluate("Plotly.relayout('plot', {dragmode: 'select'})")
    a, b = at(page, *corner), at(page, *other)
    with page.expect_response("**/api/selection"):
        page.mouse.move(a["x"], a["y"])
        page.mouse.down()
        page.mouse.move(b["x"], b["y"], steps=5)
        page.mouse.up()
    expect(page.locator("#table .table-title")).to_have_text(f"選んだ行：{rows} 行")
    # The table lies over the bottom of the stage: folded, only its bar does.
    # A table folded before stays folded for the next selection.
    down = page.locator("#table .table-down")
    if down.is_enabled():
        down.click()
    expect(page.locator("#table")).to_have_class("collapsed")


def test_lines_join_the_points_alone_or_under_them_and_hover_their_rows(
    app_page: Page,
) -> None:
    """Points alone, points and lines, lines alone: the lines follow x; without points the rows still hover and are selected at their points, not along the lines; a categorical X takes the lines off."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="g")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    page.wait_for_function(PAINTED_PIXEL)
    points, line = icon(page, "points"), icon(page, "line")
    expect(points).to_have_attribute("aria-pressed", "true")
    expect(line).to_have_attribute("aria-pressed", "false")
    expect(line).to_be_enabled()
    # Points alone: the points and their hover, nothing between them.
    assert painted(page, 2, 10) > 0
    assert painted(page, 1.5, 5) == 0
    assert hover_lines(page, 2, 10) == {"x": "2", "y": "10"}
    assert hover_lines(page, 1.5, 5) is None
    # No menu of the lines' width while they are not drawn.
    line.click(button="right")
    expect(page.locator(".scale-menu")).to_have_count(0)

    task = drawn_task(page)
    line.click()
    expect(line).to_have_attribute("aria-pressed", "true")
    new_result(page, task)
    wait_idle(page)
    expect(line).to_have_attribute("title", re.compile("2 px"))
    # In the order of x: (1, 0) to (2, 10), never (3, 0) to (1, 0) in the
    # file's order, which would pass (2, 0).
    assert painted(page, 1.5, 5) > 0
    assert painted(page, 2.5, 5) > 0
    assert painted(page, 2, 0) == 0
    assert hover_lines(page, 2, 10) == {"x": "2", "y": "10"}

    task = drawn_task(page)
    points.click()
    expect(points).to_have_attribute("aria-pressed", "false")
    new_result(page, task)
    wait_idle(page)
    expect(page.locator("#status")).to_contain_text("点は描いていない")
    # Lines alone: the hover still finds the rows at their points, and none
    # in the middle of a segment, far from its ends.
    assert painted(page, 1.5, 5) > 0
    assert hover_lines(page, 2, 10) == {"x": "2", "y": "10"}
    assert hover_lines(page, 4, 10) == {"x": "4", "y": "10"}
    assert hover_lines(page, 1.5, 5) is None
    # The lines are the only element drawn: they stay on.
    line.click()
    expect(line).to_have_attribute("aria-pressed", "true")

    # A box around a point selects its row; one on a segment only, none.
    select_box(page, (1.8, 9), (2.2, 10.15), 1)
    select_box(page, (1.4, 4), (1.6, 6), 0)

    # A color column splits the lines: b joins (1, 0) and (2, 10), a joins
    # (3, 0), (4, 10) and (5, 0), and nothing joins (2, 10) and (3, 0). Its
    # legend fades the lines of a level.
    place(page, "g", "color")
    assert painted(page, 1.5, 5) > 0
    assert painted(page, 3.5, 5) > 0
    assert painted(page, 2.5, 5) == 0
    assert opacity(page, 3.5, 5) == 255
    page.locator("#legend .legend-item").filter(has_text="a").click()
    page.wait_for_function(f"() => Math.max(...({ALPHAS_NEAR})([3.5, 5, 3])) < 64")
    assert opacity(page, 1.5, 5) == 255

    # A categorical X cannot have the lines: they go off, and the points
    # come back on.
    place(page, "g", "x")
    expect(line).to_be_disabled()
    expect(line).to_have_attribute("aria-pressed", "false")
    expect(points).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(PAINTED_PIXEL)


def test_the_width_of_the_lines_is_picked_in_their_icon_menu(app_page: Page) -> None:
    """The lines' icon's menu shows 2 px checked, and 5 px widens every line; the width stays over a zoom and with the lines off and on again."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="g")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    page.wait_for_function(PAINTED_PIXEL)
    points, line = icon(page, "points"), icon(page, "line")
    task = drawn_task(page)
    line.click()
    new_result(page, task)
    task = drawn_task(page)
    points.click()
    new_result(page, task)
    wait_idle(page)
    thin = painted(page, 1.5, 5, 8)
    assert thin > 0

    line.click(button="right")
    menu = page.locator(".scale-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text("線の太さ（全系列）")
    expect(menu.locator(".scale-menu-item")).to_have_text(
        ["1 px", "2 px", "3 px", "4 px", "5 px"]
    )
    expect(menu.locator(".scale-menu-item.checked")).to_have_text("2 px")
    task = drawn_task(page)
    menu.get_by_text("5 px", exact=True).click()
    expect(menu).to_have_count(0)
    new_result(page, task)
    wait_idle(page)
    expect(line).to_have_attribute("title", re.compile("5 px"))
    assert painted(page, 1.5, 5, 8) > thin * 2

    # A zoom keeps the width.
    task = drawn_task(page)
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [1.2, 2.8]})")
    new_result(page, task)
    wait_idle(page)
    assert page.evaluate(
        "document.getElementById('plot')._fullLayout.xaxis.range[0]"
    ) == pytest.approx(1.2)
    # Back on the points, off and on again with the lines: still 5 px.
    task = drawn_task(page)
    points.click()
    new_result(page, task)
    task = drawn_task(page)
    line.click()
    new_result(page, task)
    task = drawn_task(page)
    line.click()
    new_result(page, task)
    wait_idle(page)
    line.click(button="right")
    expect(page.locator(".scale-menu .scale-menu-item.checked")).to_have_text("5 px")
    page.keyboard.press("Escape")


# The opaque pixels around a data point of the first panel, in a square of
# `r` CSS px: how many are gray (the missing level's color) and how many are
# of another color.
GRAY_NEAR = """([x, y, r]) => {
  const full = document.getElementById("plot")._fullLayout;
  const canvas = document.querySelector("canvas.image-layers");
  const dpr = canvas.width / full.width;
  const px = Math.round((full.xaxis._offset + full.xaxis.l2p(x)) * dpr);
  const py = Math.round((full.yaxis._offset + full.yaxis.l2p(y)) * dpr);
  const side = Math.round(r * dpr);
  const { data } = canvas.getContext("2d").getImageData(px - side, py - side, 2 * side + 1, 2 * side + 1);
  let gray = 0;
  let other = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 250) continue;
    const near = [0, 1, 2].every((c) => Math.abs(data[i + c] - 128) <= 8);
    if (near) gray += 1;
    else other += 1;
  }
  return { gray, other };
}"""


def colors_near(page: Page, x: float, y: float, r: int = 1) -> dict[str, int]:
    """Return how many opaque pixels around a data point are gray and how many of another color."""
    return page.evaluate(f"(a) => ({GRAY_NEAR})(a)", [x, y, r])


def hover_value(page: Page, x: float, y: float, column: str) -> str | None:
    """Hover at a data point; return the label's value of a column, or None when it stays hidden."""
    page.mouse.move(0, 0)
    point = at(page, x, y)
    page.mouse.move(point["x"], point["y"])
    label = page.locator("#hover-label")
    try:
        expect(label).to_be_visible(timeout=1500)
    except AssertionError:
        return None
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines() if ": " in line)
    return lines.get(column)


@pytest.mark.parametrize("scatter_path", [OVERLAP], indirect=True, ids=["overlap"])
def test_the_missing_level_lies_behind_the_values_of_the_same_activity(
    app_page: Page,
) -> None:
    """A point (with a gradient color) and a line (with a categorical one) of the missing level at the place of one with a value lie behind it, and the hover finds the row with a value; with the values' series inactive, the active missing level lies on top (Issue #186)."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="v")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "v", "color")
    page.wait_for_function(PAINTED_PIXEL)
    items = page.locator("#legend .legend-item")
    expect(items.locator(".legend-name")).to_have_text(["(null)"])

    # The points where both series are: the value's color only. Where only
    # the missing level is: gray.
    for x, y in [(1, 1), (3, 3)]:
        near = colors_near(page, x, y)
        assert near["other"] > 0 and near["gray"] == 0, (x, y, near)
    near = colors_near(page, 5, 1)
    assert near["gray"] > 0 and near["other"] == 0, near
    assert hover_value(page, 1, 1, "v") == "1"
    assert hover_value(page, 3, 3, "v") == "2"

    # Only the missing level active: it lies on top of the inactive values,
    # and the hover finds it.
    items.last.click(button="right")
    expect(page.locator("#legend .colorbar.inactive")).to_have_count(1)
    page.wait_for_function(f"() => ({GRAY_NEAR})([1, 1, 1]).other === 0")
    for x, y in [(1, 1), (3, 3)]:
        near = colors_near(page, x, y)
        assert near["gray"] > 0 and near["other"] == 0, (x, y, near)
    assert hover_value(page, 1, 1, "v") == "(null)"

    # The lines of a categorical color: "a"'s lies over the missing level's.
    place(page, "k", "color")
    expect(items.locator(".legend-name")).to_have_text(["a", "(null)"])
    task = drawn_task(page)
    icon(page, "line").click()
    new_result(page, task)
    wait_idle(page)
    for x, y in [(1, 1), (2, 2)]:
        near = colors_near(page, x, y)
        assert near["other"] > 0 and near["gray"] == 0, (x, y, near)
    for x, y in [(5, 1), (4, 2)]:
        near = colors_near(page, x, y)
        assert near["gray"] > 0 and near["other"] == 0, (x, y, near)
    assert hover_value(page, 1, 1, "k") == "a"
    # "a" inactive: the active missing level's line and point lie on top.
    items.first.click()
    page.wait_for_function(f"() => ({GRAY_NEAR})([2, 2, 1]).other === 0")
    for x, y in [(1, 1), (2, 2)]:
        near = colors_near(page, x, y)
        assert near["gray"] > 0 and near["other"] == 0, (x, y, near)
