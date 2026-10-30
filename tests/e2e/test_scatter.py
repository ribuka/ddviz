"""E2E: build a scatter plot by drag and drop and hover over a row."""

from __future__ import annotations

import re

import polars as pl
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Returns a painted pixel of the image layers in client coordinates, or null.
PAINTED_PIXEL = """() => {
  const canvas = document.querySelector("canvas.image-layers");
  if (!canvas || canvas.width === 0) return null;
  const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  let best = null;
  for (let i = 3; i < data.length; i += 4) {
    if (data[i] === 0) continue;
    const p = (i - 3) / 4;
    const x = p % canvas.width;
    const y = Math.floor(p / canvas.width);
    const d = (x - cx) ** 2 + (y - cy) ** 2;
    if (!best || d < best.d) best = { x, y, d };
  }
  if (!best) return null;
  const rect = canvas.getBoundingClientRect();
  const scale = rect.width / canvas.width;
  return { x: rect.left + (best.x + 0.5) * scale, y: rect.top + (best.y + 0.5) * scale };
}"""


# Whether the status shows a result: no plot is being aggregated.
SETTLED = """() => {
  const text = document.querySelector("#status").textContent;
  return text.includes("行") && !text.includes("集約中");
}"""


def place(page: Page, column: str, role: str, plots: bool = True) -> None:
    """Drag a column onto a role's zone, check that it landed, and wait for the plot it starts.

    A plot drawn during the next drag moves the zones (on the CI runner, the
    drop then missed its zone).
    """
    source = page.locator("#columns .column").filter(
        has=page.get_by_text(column, exact=True)
    )
    zone = page.locator(f'.zone[data-role="{role}"]')
    source.drag_to(zone)
    expect(zone.locator(".chip-name")).to_have_text(column)
    if plots:
        page.wait_for_function(SETTLED)


def test_a_scatter_plot_draws_and_hovers(
    app_page: Page, scatter_frame: pl.DataFrame
) -> None:
    """Dropping x and y draws the points on the canvas; hovering one shows its row."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    expect(page.locator("#empty")).to_be_visible()

    for role in ["x", "y"]:
        column = columns.filter(has=page.get_by_text(role, exact=True))
        zone = page.locator(f'.zone[data-role="{role}"]')
        column.drag_to(zone)
        expect(zone.locator(".chip-name")).to_have_text(role)

    pixel = page.wait_for_function(PAINTED_PIXEL).json_value()
    expect(page.locator("#empty")).to_be_hidden()
    # The default limit of the hover files leaves every column in.
    expect(page.locator("#hover-warning")).to_be_hidden()

    page.mouse.move(pixel["x"], pixel["y"])
    label = page.locator("#hover-label")
    expect(label).to_be_visible()
    expect(label).to_contain_text("行番号: ")
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    row = scatter_frame.row(int(lines["行番号"]), named=True)
    for column in ["x", "y"]:
        assert float(lines[column]) == pytest.approx(row[column], rel=1e-5)


def test_wrap_replaces_group_x_and_wraps_the_panels(app_page: Page) -> None:
    """A column on Wrap removes Group X's and draws a panel per level, labeled by the level; the number to a row can be set."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    for column, role in [("y", "y"), ("facet", "col"), ("color", "wrap")]:
        place(page, column, role)
    wrap = page.locator('.zone[data-role="wrap"]')
    expect(page.locator('.zone[data-role="col"] .chip')).to_have_count(0)
    page.wait_for_function(PAINTED_PIXEL)
    labels = page.locator("#plot .annotation-text")
    expect(labels).to_have_text(["a", "b", "c"])

    wrap.locator(".wrap-cols").fill("1")
    wrap.locator(".wrap-cols").press("Enter")
    # One panel to a row: the panels stack, the first on top.
    page.wait_for_function(
        """() => {
          const layout = document.getElementById("plot").layout;
          return layout?.yaxis3 && layout.yaxis3.domain[1] < layout.yaxis2.domain[0]
            && layout.xaxis3.domain[0] === layout.xaxis.domain[0];
        }"""
    )
    expect(labels).to_have_text(["a", "b", "c"])

    # Without X, a new number to a row draws nothing.
    page.locator('.zone[data-role="x"] .chip-remove').click()
    expect(page.locator("#empty")).to_be_visible()
    wrap.locator(".wrap-cols").fill("2")
    wrap.locator(".wrap-cols").press("Enter")
    page.wait_for_timeout(1000)
    expect(page.locator("#empty")).to_be_visible()
    expect(labels).to_have_count(0)


def test_a_categorical_x_draws_bands_named_by_its_levels(app_page: Page) -> None:
    """A text column dropped on X draws a band per level, ticked with its names; the element icons show points on, box plots off, and smoothing lines unavailable without a numeric X."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    for column, role in [("color", "x"), ("y", "y")]:
        source = columns.filter(has=page.get_by_text(column, exact=True))
        zone = page.locator(f'.zone[data-role="{role}"]')
        source.drag_to(zone)
        expect(zone.locator(".chip-name")).to_have_text(column)
    page.wait_for_function(PAINTED_PIXEL)
    expect(page.locator("#plot .xtick text")).to_have_text(["a", "b", "c"])

    icons = page.locator("#elements .element")
    expect(icons).to_have_count(3)
    points = icons.nth(0)
    expect(points).to_have_attribute("aria-pressed", "true")
    expect(icons.nth(1)).to_be_enabled()
    expect(icons.nth(1)).to_have_attribute("aria-pressed", "false")
    expect(icons.nth(2)).to_be_disabled()
    # Points are the only element drawn: they stay on.
    points.click()
    expect(points).to_have_attribute("aria-pressed", "true")


def test_box_plots_draw_over_the_bands_and_hover(
    app_page: Page, scatter_frame: pl.DataFrame
) -> None:
    """The box plot icon draws a box per level; without points, hovering a box shows its numbers; a numeric X turns box plots off."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    for column, role in [("color", "x"), ("y", "y")]:
        source = columns.filter(has=page.get_by_text(column, exact=True))
        source.drag_to(page.locator(f'.zone[data-role="{role}"]'))
    page.wait_for_function(PAINTED_PIXEL)
    icons = page.locator("#elements .element")
    points, box = icons.nth(0), icons.nth(1)
    box.click()
    expect(box).to_have_attribute("aria-pressed", "true")
    points.click()
    expect(points).to_have_attribute("aria-pressed", "false")
    # Box plots are the only element drawn: they stay on.
    box.click()
    expect(box).to_have_attribute("aria-pressed", "true")

    values = scatter_frame.filter(pl.col("color") == "b", pl.col("y").is_finite())["y"]
    median = float(values.median())
    # The middle of the band of b, at its median, once the boxes are drawn.
    at = page.wait_for_function(
        """(median) => {
          const gd = document.getElementById("plot");
          const full = gd._fullLayout;
          if (!full?.xaxis || !document.querySelector("#status").textContent.includes("行")) return null;
          const rect = gd.getBoundingClientRect();
          return {
            x: rect.left + full.xaxis._offset + full.xaxis.l2p(1),
            y: rect.top + full.yaxis._offset + full.yaxis.l2p(median),
          };
        }""",
        arg=median,
    ).json_value()
    label = page.locator("#hover-label")
    expect(label).to_be_hidden()
    page.mouse.move(at["x"], at["y"])
    expect(label).to_be_visible()
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    assert lines["color"] == "b"
    assert int(lines["行数"].replace(",", "")) == values.len()
    assert float(lines["50%"]) == pytest.approx(median, rel=1e-5)

    # A numeric column on X cannot have box plots: the points come back.
    source = columns.filter(has=page.get_by_text("x", exact=True))
    source.drag_to(page.locator('.zone[data-role="x"] .chip'))
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text("x")
    expect(box).to_be_disabled()
    expect(box).to_have_attribute("aria-pressed", "false")
    expect(points).to_have_attribute("aria-pressed", "true")


def test_smoothing_lines_draw_alone_and_change_their_method(app_page: Page) -> None:
    """The smoothing line icon draws a line per series; without points only the lines are painted; its menu picks another method, which plots again."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    for column, role in [("y", "y"), ("color", "color")]:
        place(page, column, role)
    page.wait_for_function(PAINTED_PIXEL)
    icons = page.locator("#elements .element")
    points, smooth = icons.nth(0), icons.nth(2)
    expect(smooth).to_be_enabled()
    expect(smooth).to_have_attribute("title", re.compile("GCV"))
    smooth.click()
    expect(smooth).to_have_attribute("aria-pressed", "true")
    points.click()
    expect(points).to_have_attribute("aria-pressed", "false")
    status = page.locator("#status")
    expect(status).to_contain_text("点は描いていない")
    page.wait_for_function(PAINTED_PIXEL)
    task = status.inner_text()

    smooth.click(button="right")
    menu = page.locator(".scale-menu")
    expect(menu.locator(".scale-menu-item.checked").first).to_have_text(
        "GCV 平滑化スプライン"
    )
    menu.get_by_text("lowess", exact=True).click()
    expect(menu).to_have_count(0)
    expect(smooth).to_have_attribute("title", re.compile("lowess、frac = 2/3"))
    expect(status).not_to_have_text(task)
    expect(status).to_contain_text("点は描いていない")
    page.wait_for_function(PAINTED_PIXEL)
