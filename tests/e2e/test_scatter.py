"""E2E: build a scatter plot by drag and drop and hover over a row."""

from __future__ import annotations

import re

import polars as pl
import pytest
from playwright.sync_api import Page, Route, expect

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
    # Without a color column the pixel's count names no series ("None" once).
    assert re.fullmatch(r"\d+ 行", lines["このピクセル"])


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

    # Without Y, a new number to a row draws nothing.
    page.locator('.zone[data-role="y"] .chip-remove').click()
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


def test_box_plots_without_x_lie_in_one_band(
    app_page: Page, scatter_frame: pl.DataFrame
) -> None:
    """With Y alone, points lie in one band; box plots side by side are ticked by series and hover without an x line."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    place(page, "y", "y")
    place(page, "color", "color")
    page.wait_for_function(PAINTED_PIXEL)
    expect(page.locator("#plot .xtick text")).to_have_count(0)
    icons = page.locator("#elements .element")
    points, box = icons.nth(0), icons.nth(1)
    expect(box).to_be_enabled()
    expect(icons.nth(2)).to_be_disabled()
    box.click()
    expect(page.locator("#plot .xtick text")).to_have_text(["a", "b", "c"])
    points.click()
    expect(points).to_have_attribute("aria-pressed", "false")

    values = scatter_frame.filter(pl.col("color") == "b", pl.col("y").is_finite())["y"]
    median = float(values.median())
    # The box of b, the middle one of three, lies in the middle of the band.
    at = page.wait_for_function(
        """(median) => {
          const gd = document.getElementById("plot");
          const full = gd._fullLayout;
          const status = document.querySelector("#status").textContent;
          if (!full?.xaxis || !status.includes("外れ値")) return null;
          const rect = gd.getBoundingClientRect();
          return {
            x: rect.left + full.xaxis._offset + full.xaxis.l2p(0),
            y: rect.top + full.yaxis._offset + full.yaxis.l2p(median),
          };
        }""",
        arg=median,
    ).json_value()
    label = page.locator("#hover-label")
    page.mouse.move(at["x"], at["y"])
    expect(label).to_be_visible()
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    # The one band is no column: the series comes first.
    assert next(iter(lines)) == "color"
    assert lines["color"] == "b"
    assert int(lines["行数"].replace(",", "")) == values.len()
    assert float(lines["50%"]) == pytest.approx(median, rel=1e-5)


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


def test_a_column_with_too_many_levels_filters_by_contained_text(
    app_page: Page, scatter_frame: pl.DataFrame
) -> None:
    """The label column, one level per row, gets a text box; the plot then draws only the rows whose label contains the text."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    source = columns.filter(has=page.get_by_text("label", exact=True))
    source.drag_to(page.locator("#filters"))
    card = page.locator(".filter-card")
    expect(card).to_contain_text("部分一致で絞る")
    status = page.locator("#status")
    task = status.inner_text()
    box = card.locator(".filter-contains input")
    # The Enter that commits an IME conversion keeps the box in use.
    box.focus()
    box.evaluate(
        """(box) => box.dispatchEvent(new KeyboardEvent("keydown", {
          key: "Enter", keyCode: 229, isComposing: true, bubbles: true,
        }))"""
    )
    expect(box).to_be_focused()
    box.fill("r12")
    box.press("Enter")
    expect(status).not_to_have_text(task)
    expect(status).to_contain_text("（フィルタ後）")
    page.wait_for_function(SETTLED)
    kept = scatter_frame.filter(
        pl.col("label").str.contains("r12", literal=True),
        pl.col("x").is_finite(),
        pl.col("y").is_finite(),
    ).height
    expect(status).to_contain_text(f": {kept:,} 行")
    expect(page.locator(".filter-summary")).to_have_text("（1）label: 「r12」を含む")


def test_overlay_draws_shapes_with_a_legend_of_their_own(app_page: Page) -> None:
    """Overlay beside color shows a legend of shapes, toggled on its own; a marker's menu changes its level's size, the points' icon every level's."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    for column, role in [("y", "y"), ("color", "color"), ("facet", "overlay")]:
        place(page, column, role)
    page.wait_for_function(PAINTED_PIXEL)
    legend = page.locator("#legend")
    expect(legend.locator(".legend-title")).to_have_text(["color", "facet"])
    shapes = legend.locator(".legend-item").filter(has=page.locator("canvas"))
    expect(shapes).to_have_count(2)
    expect(shapes.first.locator("canvas")).to_have_attribute("width", "7")

    shapes.first.click()
    expect(shapes.first).to_have_class(re.compile("inactive"))
    expect(legend.locator(".legend-item.inactive")).to_have_count(1)

    status = page.locator("#status")
    task = status.inner_text()
    shapes.nth(1).locator(".legend-marker").click(button="right")
    menu = page.locator(".shape-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text(
        re.compile("^形「.+」の大きさ$")
    )
    expect(menu.locator(".scale-menu-item.checked")).to_have_text("7 px")
    menu.get_by_text("11 px", exact=True).click()
    expect(menu).to_have_count(0)
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    # Only that level's shapes grow.
    expect(shapes.nth(1).locator("canvas")).to_have_attribute("width", "11")
    expect(shapes.first.locator("canvas")).to_have_attribute("width", "7")
    page.wait_for_function(PAINTED_PIXEL)
    points = page.locator('#elements .element[data-element="points"]')
    expect(points).to_have_attribute("title", re.compile("7〜11 px"))

    # The points' icon sizes every level, dropping the level's own size.
    task = status.inner_text()
    points.click(button="right")
    expect(menu.locator(".scale-menu-heading")).to_have_text("点の大きさ（全系列）")
    # The size of every series is still 7 px; picking it drops the level's 11 px.
    expect(menu.locator(".scale-menu-item.checked")).to_have_count(0)
    menu.get_by_text("7 px", exact=True).click()
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    expect(shapes.nth(1).locator("canvas")).to_have_attribute("width", "7")
    expect(shapes.first.locator("canvas")).to_have_attribute("width", "7")
    expect(points).to_have_attribute("title", re.compile("（7 px）"))


# Whether the image layers have a pixel of the color [r, g, b].
HAS_COLOR = """([r, g, b]) => {
  const canvas = document.querySelector("canvas.image-layers");
  const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] === 255 && data[i] === r && data[i + 1] === g && data[i + 2] === b) return true;
  }
  return false;
}"""


def test_a_color_level_takes_a_color_picked_on_its_marker(app_page: Page) -> None:
    """A color item's marker opens a menu whose color panel recolors the level without aggregating; another color column drops it, and an interval's marker opens the scale's menu."""
    page = app_page
    plots: list[str] = []
    page.on("request", lambda r: plots.append(r.url) if "/api/plot" in r.url else None)
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    # The images land after the status: the drop waits for them.
    page.wait_for_function(PAINTED_PIXEL)
    place(page, "color", "color")
    page.wait_for_function(PAINTED_PIXEL)
    legend = page.locator("#legend")
    swatch = legend.locator(".legend-item .swatch").first
    expect(swatch).to_have_css("background-color", "rgb(31, 119, 180)")
    marker = legend.locator(".legend-marker").first
    expect(marker).to_have_attribute("title", "右クリックで色と点の大きさを変える")

    marker.click(button="right")
    menu = page.locator(".shape-menu")
    menu.get_by_text("色", exact=True).hover()
    panel = page.locator(".color-panel")
    expect(panel).to_be_visible()
    # Hues in columns, five shades under them and a row of grays.
    expect(panel.locator(".color-cell")).to_have_count(70)
    expect(panel.locator(".color-cell.current")).to_have_attribute("title", "#1f77b4")
    expect(panel.get_by_text("その他の色…")).to_be_visible()
    # Away to a size, the panel closes; back on the color, it opens again.
    menu.get_by_text("9 px", exact=True).hover()
    expect(panel).to_have_count(0)
    menu.get_by_text("色", exact=True).hover()
    asked = len(plots)
    panel.locator('.color-cell[title="#000000"]').click()
    expect(menu).to_have_count(0)
    expect(swatch).to_have_css("background-color", "rgb(0, 0, 0)")
    page.wait_for_function(HAS_COLOR, arg=[0, 0, 0])
    assert len(plots) == asked

    marker.click(button="right")
    menu.get_by_text("色", exact=True).hover()
    expect(panel.locator(".color-cell.current")).to_have_attribute("title", "#000000")
    panel.get_by_text("既定の色に戻す").click()
    expect(swatch).to_have_css("background-color", "rgb(31, 119, 180)")
    page.wait_for_function(f"() => !({HAS_COLOR})([0, 0, 0])")
    assert len(plots) == asked

    # The code field is in HEX from the start: a bad code is marked, a good
    # one (with or without "#", 3 or 6 digits) is picked with Enter.
    marker.click(button="right")
    menu.get_by_text("色", exact=True).hover()
    code = panel.locator(".color-hex-input")
    expect(code).to_have_value("#1f77b4")
    code.fill("#12345")
    code.press("Enter")
    expect(code).to_have_class(re.compile("invalid"))
    expect(menu).to_be_visible()
    code.fill("0f0")
    code.press("Enter")
    expect(menu).to_have_count(0)
    expect(swatch).to_have_css("background-color", "rgb(0, 255, 0)")
    page.wait_for_function(HAS_COLOR, arg=[0, 255, 0])
    assert len(plots) == asked

    # The color stays while the color column does, and goes with another.
    marker.click(button="right")
    menu.get_by_text("色", exact=True).hover()
    panel.locator('.color-cell[title="#000000"]').click()
    expect(swatch).to_have_css("background-color", "rgb(0, 0, 0)")
    place(page, "facet", "color")
    expect(swatch).to_have_css("background-color", "rgb(31, 119, 180)")
    place(page, "color", "color")
    expect(swatch).to_have_css("background-color", "rgb(31, 119, 180)")

    # The intervals of a numeric column take the scale's colors: their
    # markers open the scale's menu.
    place(page, "x", "color")
    legend.locator(".colorbar").click(button="right")
    page.locator(".scale-menu").get_by_text("3 個", exact=True).click()
    page.wait_for_function(SETTLED)
    # The title is the column's name alone, without how it is cut.
    expect(legend.locator(".legend-title")).to_have_text("x")
    marker = legend.locator(".legend-marker").first
    expect(marker).to_have_attribute("title", "右クリックで色の付け方を変える")
    marker.click(button="right")
    menu = page.locator(".scale-menu")
    expect(menu.locator(".scale-menu-item.checked").first).to_have_text("3 個")
    expect(menu.get_by_text("点の大きさ（全系列）")).to_be_visible()
    expect(menu.get_by_text("色", exact=True)).to_be_visible()
    expect(page.locator(".color-panel")).to_have_count(0)


# Holds the decoding of images until `window.releaseImages()`.
HOLD_IMAGES = """() => {
  const hold = new Promise((resolve) => { window.releaseImages = resolve; });
  const original = window.createImageBitmap;
  window.createImageBitmap = async (...args) => {
    await hold;
    return original(...args);
  };
}"""


def test_a_color_picked_while_the_images_decode_draws_them(app_page: Page) -> None:
    """A color picked before the first images are decoded draws them in that color."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    page.wait_for_function(PAINTED_PIXEL)
    page.evaluate(HOLD_IMAGES)
    place(page, "color", "color")
    legend = page.locator("#legend")
    legend.locator(".legend-marker").first.click(button="right")
    page.locator(".shape-menu").get_by_text("色", exact=True).hover()
    page.locator('.color-panel .color-cell[title="#000000"]').click()
    expect(legend.locator(".legend-item .swatch").first).to_have_css(
        "background-color", "rgb(0, 0, 0)"
    )
    page.evaluate("() => window.releaseImages()")
    page.wait_for_function(HAS_COLOR, arg=[0, 0, 0])


# Number of painted pixels of the image layers.
PAINTED_COUNT = """() => {
  const canvas = document.querySelector("canvas.image-layers");
  const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  let n = 0;
  for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) n++;
  return n;
}"""


def test_points_are_circles_sized_by_the_legend_and_the_color_bar(
    app_page: Page,
) -> None:
    """Without an overlay the points are 5px circles; the points' icon, or a gradient's color bar menu changes their size. Without a color column the legend shows no item."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    # Without a scatter plot, the points' icon opens no menu.
    points = page.locator('#elements .element[data-element="points"]')
    points.click(button="right")
    expect(page.locator(".shape-menu")).to_have_count(0)
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    page.wait_for_function(PAINTED_PIXEL)
    small = page.evaluate(PAINTED_COUNT)
    expect(points).to_have_attribute(
        "title", re.compile("5 px.*右クリックで大きさを変える")
    )
    points.click(button="right")
    menu = page.locator(".shape-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text("点の大きさ（全系列）")
    expect(menu.locator(".scale-menu-item.checked")).to_have_text("5 px")
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)

    status = page.locator("#status")
    task = status.inner_text()
    # A single color has no legend: the points' icon opens the menu.
    legend = page.locator("#legend")
    expect(legend.locator(".legend-item")).to_have_count(0)
    expect(legend.locator(".legend-title")).to_have_count(0)
    points.click(button="right")
    expect(menu.locator(".scale-menu-item.checked")).to_have_text("5 px")
    menu.get_by_text("9 px", exact=True).click()
    expect(menu).to_have_count(0)
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    page.wait_for_function(f"() => ({PAINTED_COUNT})() > {small}")

    # A gradient has no markers: its color bar's menu has the size, kept.
    place(page, "x", "color")
    bar = legend.locator(".colorbar")
    expect(bar).to_be_visible()
    task = status.inner_text()
    bar.click(button="right")
    menu = page.locator(".scale-menu")
    expect(menu.get_by_text("点の大きさ（全系列）")).to_be_visible()
    expect(menu.locator(".scale-menu-item.checked").last).to_have_text("9 px")
    menu.get_by_text("3 px", exact=True).click()
    expect(menu).to_have_count(0)
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    page.wait_for_function(PAINTED_PIXEL)

    # In a low window the longer menu stays on screen and scrolls.
    page.set_viewport_size({"width": 1280, "height": 400})
    page.wait_for_function(SETTLED)
    bar.click(button="right")
    box = menu.bounding_box()
    assert box["y"] >= 0 and box["y"] + box["height"] <= 400
    expect(menu.get_by_text("15 px", exact=True)).not_to_be_in_viewport()
    item = menu.get_by_text("2 個", exact=True)
    item.scroll_into_view_if_needed()
    expect(item).to_be_in_viewport()


def overlaps(a: dict, b: dict) -> bool:
    """Whether two bounding boxes overlap."""
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


# Scrolls a scroller to a left position and draws for it (a scroll event, also
# when it does not move), then waits two frames: the scroll event of a move
# comes before the next frame's animation frame callbacks.
SCROLL_AND_SETTLE = """async (s, left) => {
  s.scrollLeft = left;
  s.dispatchEvent(new Event("scroll"));
  for (let i = 0; i < 2; i++) await new Promise((resolve) => requestAnimationFrame(resolve));
}"""

# The bounding boxes of elements in the viewport, all read in one go.
BOXES = """(els) => els.map((e) => {
  const { x, y, width, height } = e.getBoundingClientRect();
  return { x, y, width, height };
})"""


def test_the_mode_bar_shows_without_hover_and_stays_in_sight(app_page: Page) -> None:
    """The mode bar shows with the pointer off the plot, apart from the facet labels, and stays at the top right of a grid that scrolls."""
    page = app_page
    # Two panels of their smallest width do not fit: the grid scrolls.
    page.set_viewport_size({"width": 800, "height": 600})
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "facet", "col")
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    page.mouse.move(0, 0)
    mode_bar = page.locator("#plot .modebar")
    expect(mode_bar).to_be_visible()
    expect(mode_bar).to_have_css("opacity", "1")
    stage = page.locator("#stage").bounding_box()
    labels = page.locator(".sticky-strip .facet.col")
    expect(labels).to_have_count(2)

    for left in [0, 10_000]:
        # A scroll that moves fires its own scroll event a frame later, which
        # rebuilds the labels: wait for it, then read the boxes at once, so
        # that no label is replaced (and has no box) between two reads.
        page.locator("#scroller").evaluate(SCROLL_AND_SETTLE, left)
        box = mode_bar.bounding_box()
        assert stage["x"] <= box["x"]
        assert box["x"] + box["width"] <= stage["x"] + stage["width"]
        assert stage["y"] <= box["y"] < stage["y"] + 30
        for label in labels.evaluate_all(BOXES):
            if label["width"] and label["height"]:
                assert not overlaps(box, label)
        # The button on top takes the click, not the strip under it.
        mode_bar.locator('[data-val="zoom"]').click()
        assert (
            page.evaluate("document.getElementById('plot').layout.dragmode") == "zoom"
        )
        mode_bar.locator('[data-val="pan"]').click()


def test_the_mode_bar_saves_the_plot_data(app_page: Page) -> None:
    """The mode bar's download button opens a menu that saves the overview's bins as CSV; Esc closes it."""
    page = app_page
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    button = page.locator('#plot .modebar-btn[data-title^="データを保存"]')
    button.click()
    menu = page.locator(".data-menu")
    expect(menu).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)

    button.click()
    with page.expect_download() as info:
        menu.get_by_role("button", name="CSV").click()
    download = info.value
    assert re.fullmatch(r"scatter_\d{8}-\d{6}\.csv", download.suggested_filename)
    table = pl.read_csv(download.path())
    assert table.columns[:3] == ["x_column", "x_lo", "x_hi"]
    status = page.locator("#status").text_content()
    assert f" {table['count'].sum():,} 行" in status
    expect(menu).to_have_count(0)


def drop_at(page: Page, column: str, role: str, x: float, y: float) -> None:
    """Drag a column from the list onto a role's zone at a point relative to the zone, and wait for the plot."""
    source = page.locator("#columns .column").filter(
        has=page.get_by_text(column, exact=True)
    )
    zone = page.locator(f'.zone[data-role="{role}"]')
    source.drag_to(zone, target_position={"x": x, "y": y})
    page.wait_for_function(SETTLED)


def test_axis_drops_split_the_zone_into_a_region_per_axis(app_page: Page) -> None:
    """On X and Y, the zone is split into a region per axis: the first quarter of the n-th goes in before the n-th axis, the last quarter after it, the middle half replaces it."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    x_zone = page.locator('.zone[data-role="x"]')
    y_zone = page.locator('.zone[data-role="y"]')
    x_names = x_zone.locator(".chip-name")
    y_names = y_zone.locator(".chip-name")

    # X runs left to right. One axis: the whole zone is its region.
    zone = x_zone.bounding_box()
    middle = zone["height"] / 2
    drop_at(page, "y", "x", zone["width"] * 0.4, middle)
    expect(x_names).to_have_text(["y"])
    drop_at(page, "x", "x", zone["width"] * 0.9, middle)
    expect(x_names).to_have_text(["y", "x"])
    # Two axes: the end of the first half goes in between them.
    zone = x_zone.bounding_box()
    drop_at(page, "facet", "x", zone["width"] * 0.45, middle)
    expect(x_names).to_have_text(["y", "facet", "x"])
    # Three axes: the middle of the third replaces the third.
    zone = x_zone.bounding_box()
    drop_at(page, "color", "x", zone["width"] * 5 / 6, middle)
    expect(x_names).to_have_text(["y", "facet", "color"])

    # Y runs top to bottom: the start of the zone goes in first.
    zone = y_zone.bounding_box()
    center = zone["width"] / 2
    drop_at(page, "x", "y", center, zone["height"] * 0.1)
    expect(y_names).to_have_text(["x", "y"])
    # The start of the second half goes in between them.
    zone = y_zone.bounding_box()
    drop_at(page, "facet", "y", center, zone["height"] * 0.55)
    expect(y_names).to_have_text(["x", "facet", "y"])
    # The middle of the first third replaces the first.
    zone = y_zone.bounding_box()
    drop_at(page, "color", "y", center, zone["height"] / 6)
    expect(y_names).to_have_text(["color", "facet", "y"])


def test_axis_drop_marks_follow_the_regions(app_page: Page) -> None:
    """While dragging over X, the tip, the line and the outline follow the regions: the middle outlines the column it replaces, the ends show a line."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    x_zone = page.locator('.zone[data-role="x"]')
    tip = page.locator("#drop-tip")
    line = page.locator("#drop-line")
    source = page.locator("#columns .column").filter(
        has=page.get_by_text("facet", exact=True)
    )
    # Playwright's mouse fires no dragover while the button is held: send
    # the drag's events to the elements instead.
    data = page.evaluate_handle("() => new DataTransfer()")
    source.dispatch_event("dragstart", {"dataTransfer": data})
    zone = x_zone.bounding_box()
    middle = zone["y"] + zone["height"] / 2

    def over(share: float) -> None:
        x_zone.dispatch_event(
            "dragover",
            {
                "dataTransfer": data,
                "clientX": zone["x"] + zone["width"] * share,
                "clientY": middle,
            },
        )

    over(0.5)
    expect(tip).to_have_text("X の x を置き換える")
    expect(x_zone.locator(".chip.target")).to_have_count(1)
    expect(line).to_be_hidden()
    over(0.9)
    expect(tip).to_have_text("X の x の右に第 2 軸として挿入")
    expect(x_zone.locator(".chip.target")).to_have_count(0)
    expect(line).to_be_visible()
    # The line stands right of the chip, not at the end of the region.
    chip = x_zone.locator(".chip").bounding_box()
    box = line.bounding_box()
    assert chip["x"] + chip["width"] <= box["x"] < chip["x"] + chip["width"] + 6
    over(0.1)
    expect(tip).to_have_text("X の x の左に第 1 軸として挿入")
    box = line.bounding_box()
    assert chip["x"] - 6 < box["x"] + box["width"] <= chip["x"]
    page.evaluate("() => document.dispatchEvent(new DragEvent('dragend'))")
    expect(tip).to_be_hidden()
    # The end of the last region goes in last: no "+" after the chips.
    expect(page.locator(".zone-add")).to_have_count(0)


def test_group_y_reads_top_to_bottom_and_the_kind_tabs_show_the_chosen(
    app_page: Page,
) -> None:
    """Group Y is not rotated, as plotly's row labels, while Y is; the column list speaks English and fills the chosen kind's tab."""
    page = app_page
    expect(page.locator("#columns .column").first).to_be_visible()
    expect(page.locator(".column-search")).to_have_attribute("placeholder", "Search ...")
    expect(page.locator(".filter-drop")).to_have_text("Drop a column to filter")
    tabs = page.locator(".column-kinds button")
    expect(tabs).to_have_text(["All", "Numeric", "Categorical"])
    on = {"background-color": "rgb(42, 111, 219)", "color": "rgb(255, 255, 255)"}
    for name, value in on.items():
        expect(tabs.nth(0)).to_have_css(name, value)
    tabs.nth(1).click()
    expect(tabs.nth(1)).to_have_class(re.compile(r"\bon\b"))
    for name, value in on.items():
        expect(tabs.nth(1)).to_have_css(name, value)
    expect(tabs.nth(0)).not_to_have_css("background-color", on["background-color"])
    tabs.nth(0).click()

    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "facet", "row")
    expect(page.locator('.zone[data-role="row"]')).to_have_css("transform", "none")
    expect(page.locator('.zone[data-role="y"]')).not_to_have_css("transform", "none")
    # Read from the top: the name starts above the "×".
    chip = page.locator('.zone[data-role="row"] .chip')
    name = chip.locator(".chip-name").bounding_box()
    remove = chip.locator(".chip-remove").bounding_box()
    assert name["y"] < remove["y"]


def test_the_side_stacks_overlay_color_and_the_legend(app_page: Page) -> None:
    """The pane right of the figure holds Overlay, then Color, then the legend, top to bottom."""
    page = app_page
    tops = [
        page.locator(selector).bounding_box()["y"]
        for selector in [
            '#side [data-role="overlay"]',
            '#side [data-role="color"]',
            "#legend",
        ]
    ]
    assert tops == sorted(tops)


def test_the_column_list_keeps_its_items_while_the_shares_are_counted(
    app_page: Page,
) -> None:
    """While the shares are counted the list asks again every second; an answer listing the same columns keeps their items, and a drag from one still drops.

    A replaced item under the pointer while it is pressed made Chrome drop the
    drag now and then (Issue #37).
    """
    page = app_page

    def pending(route: Route) -> None:
        # Keep the shares pending, so that the list keeps asking again.
        found = route.fetch().json()
        found["shares"] = "pending"
        found["rows"] = None
        for column in found["columns"]:
            column["nonnull"] = None
            column["share"] = None
        route.fulfill(json=found)

    page.route("**/api/columns?*", pending)
    page.reload()
    source = page.locator("#columns .column").filter(
        has=page.get_by_text("y", exact=True)
    )
    expect(source).to_be_visible()
    source.evaluate("(item) => { window.shownItem = item; }")
    with page.expect_response("**/api/columns?*") as answer:
        pass
    answer.value.finished()
    # The answer is shown in the task after its body arrives.
    page.evaluate("() => new Promise((r) => setTimeout(r, 100))")
    assert page.evaluate("() => window.shownItem.isConnected")
    zone = page.locator('.zone[data-role="y"]')
    source.drag_to(zone)
    expect(zone.locator(".chip-name")).to_have_text("y")


# Records whether the notice of a pending aggregation shows from now on.
WATCH_PENDING = """() => {
  const notice = document.getElementById("pending");
  window.pendingShown = false;
  new MutationObserver(() => {
    if (!notice.hidden) window.pendingShown = true;
  }).observe(notice, { attributes: true });
}"""


def test_the_pending_mark_shows_only_on_a_slow_result(app_page: Page) -> None:
    """A zoom fades the images and shows "集約中…" only when its result takes long; a fast one is drawn without them (Issue #45)."""
    page = app_page
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    page.wait_for_function(PAINTED_PIXEL)
    plot = page.locator("#plot")
    notice = page.locator("#pending")

    # A result that comes at once is drawn without the mark.
    page.evaluate(WATCH_PENDING)
    page.route("**/api/view", lambda route: route.continue_())
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [0.2, 0.8]})")
    expect(page.locator("#status")).to_contain_text("表示範囲")
    page.wait_for_function(SETTLED)
    assert not page.evaluate("window.pendingShown")
    expect(plot).not_to_have_class(re.compile(r"\bpending\b"))
    page.unroute("**/api/view")

    # A result held back is marked once the delay passes, and unmarked when drawn.
    held: list[Route] = []

    def hold(route: Route) -> None:
        held.append(route)

    page.route("**/api/view", hold)
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [0.3, 0.7]})")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.includes('表示範囲を集約中')"
    )
    expect(notice).to_be_hidden()
    expect(plot).not_to_have_class(re.compile(r"\bpending\b"))
    expect(notice).to_be_visible()
    expect(plot).to_have_class(re.compile(r"\bpending\b"))
    assert len(held) == 1
    held[0].continue_()
    page.wait_for_function(SETTLED)
    expect(notice).to_be_hidden()
    expect(plot).not_to_have_class(re.compile(r"\bpending\b"))


def test_a_right_click_on_the_plot_picks_the_drag_mode_and_resets_the_axes(
    app_page: Page,
) -> None:
    """The plot's right-click menu checks the drag mode, switches it as the mode bar does, resets the axes to the overview without aggregating, and keeps a box selection."""
    page = app_page
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    plots: list[str] = []
    page.on(
        "request",
        lambda request: "/api/plot" in request.url and plots.append(request.url),
    )
    menu = page.locator(".plot-menu")
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    status = page.locator("#status")

    def dragmode() -> str:
        return page.evaluate("document.getElementById('plot')._fullLayout.dragmode")

    def pick(name: str, x: float = cx, y: float = cy) -> None:
        page.mouse.click(x, y, button="right")
        menu.get_by_role("button", name=name, exact=True).click()
        expect(menu).to_have_count(0)

    # Pan is the starting mode and is checked.
    page.mouse.click(cx, cy, button="right")
    expect(menu.locator(".checked")).to_have_text("Pan")
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)

    pick("Zoom")
    assert dragmode() == "zoom"
    expect(page.locator('#plot .modebar-btn[data-val="zoom"]')).to_have_class(
        re.compile(r"\bactive\b")
    )
    page.mouse.move(cx - 60, cy - 60)
    page.mouse.down()
    page.mouse.move(cx + 60, cy + 60, steps=5)
    page.mouse.up()
    expect(status).to_contain_text("表示範囲に")
    page.wait_for_function(SETTLED)

    pick("Reset axes")
    expect(status).not_to_contain_text("表示範囲に")
    assert plots == []

    pick("Box Select")
    assert dragmode() == "select"
    page.mouse.move(cx - 60, cy - 60)
    page.mouse.down()
    page.mouse.move(cx + 60, cy + 60, steps=5)
    page.mouse.up()
    table = page.locator("#table")
    expect(table).to_be_visible()
    selections = "document.getElementById('plot').layout.selections.length"
    assert page.evaluate(selections) == 1
    # Right clicks, also two in a row, inside and outside the box neither drop
    # nor change the selection.
    for x, y in [(cx, cy), (cx, cy), (box["x"] + 5, box["y"] + 5)]:
        page.mouse.click(x, y, button="right")
        expect(menu).to_be_visible()
    page.keyboard.press("Escape")
    expect(table).to_be_visible()
    assert page.evaluate(selections) == 1
    assert dragmode() == "select"

    # An axis's tick labels open the menu too (the x ticks lie under the table);
    # the mode bar does not.
    tick = page.locator("#plot .ytick text").first.bounding_box()
    page.mouse.click(
        tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2, button="right"
    )
    expect(menu).to_be_visible()
    page.keyboard.press("Escape")
    page.locator('#plot .modebar-btn[data-val="pan"]').click(button="right")
    expect(menu).to_have_count(0)
    assert plots == []
