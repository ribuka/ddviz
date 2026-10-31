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
    """Overlay beside color shows a legend of shapes, toggled on its own; a marker's menu changes their size, which plots again."""
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
    expect(menu.locator(".scale-menu-item.checked")).to_have_text("7 px")
    menu.get_by_text("11 px", exact=True).click()
    expect(menu).to_have_count(0)
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    expect(shapes.first.locator("canvas")).to_have_attribute("width", "11")
    page.wait_for_function(PAINTED_PIXEL)


def overlaps(a: dict, b: dict) -> bool:
    """Whether two bounding boxes overlap."""
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


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
        page.locator("#scroller").evaluate(
            "(s, left) => { s.scrollLeft = left; s.dispatchEvent(new Event('scroll')); }",
            left,
        )
        box = mode_bar.bounding_box()
        assert stage["x"] <= box["x"]
        assert box["x"] + box["width"] <= stage["x"] + stage["width"]
        assert stage["y"] <= box["y"] < stage["y"] + 30
        for label in labels.all():
            if label.is_visible():
                assert not overlaps(box, label.bounding_box())
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


def test_axis_drops_replace_except_near_chip_edges_and_on_the_plus(
    app_page: Page,
) -> None:
    """On X and Y, a drop away from the chips' edges replaces the nearest chip; one near an edge or on the "+" goes in as an n-th axis."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    x_zone = page.locator('.zone[data-role="x"]')
    y_zone = page.locator('.zone[data-role="y"]')
    x_names = x_zone.locator(".chip-name")
    y_names = y_zone.locator(".chip-name")

    # The empty end of the zone, far from the chip, replaces it.
    zone = x_zone.bounding_box()
    drop_at(page, "y", "x", zone["width"] - 4, zone["height"] / 2)
    expect(x_names).to_have_text(["y"])
    # The "+" after the chips goes in last.
    plus = x_zone.locator(".zone-add").bounding_box()
    zone = x_zone.bounding_box()
    drop_at(
        page, "x", "x", plus["x"] - zone["x"] + plus["width"] / 2, zone["height"] / 2
    )
    expect(x_names).to_have_text(["y", "x"])
    # Just outside a chip's leading edge goes in before it.
    chip = x_zone.locator(".chip").first.bounding_box()
    drop_at(page, "facet", "x", chip["x"] - zone["x"] - 6, zone["height"] / 2)
    expect(x_names).to_have_text(["facet", "y", "x"])

    # Y runs top to bottom: the empty bottom end replaces the last chip.
    zone = y_zone.bounding_box()
    drop_at(page, "x", "y", zone["width"] / 2, zone["height"] - 4)
    expect(y_names).to_have_text(["x"])
    # Just inside a chip's top edge goes in above it.
    chip = y_zone.locator(".chip").first.bounding_box()
    drop_at(page, "y", "y", zone["width"] / 2, chip["y"] - zone["y"] + 4)
    expect(y_names).to_have_text(["y", "x"])


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
