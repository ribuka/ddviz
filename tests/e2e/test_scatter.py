"""E2E: build a scatter plot by drag and drop and hover over a row."""

from __future__ import annotations

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
    for column, role in [("x", "x"), ("y", "y"), ("facet", "col"), ("color", "wrap")]:
        source = columns.filter(has=page.get_by_text(column, exact=True))
        source.drag_to(page.locator(f'.zone[data-role="{role}"]'))
    wrap = page.locator('.zone[data-role="wrap"]')
    expect(wrap.locator(".chip-name")).to_have_text("color")
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
