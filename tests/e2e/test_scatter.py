"""E2E: build a scatter plot by drag and drop and hover over a row."""

from __future__ import annotations

import math
import re

import polars as pl
import pytest
from playwright.sync_api import ConsoleMessage, Locator, Page, Route, expect

from ddviz.server.settings import LegendSettings, PlotSettings, Settings

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


# Panels in the top row of the plotted figure, or null before one.
TOP_ROW_PANELS = """() => {
  const layout = document.getElementById("plot").layout;
  if (!layout?.yaxis) return null;
  const top = layout.yaxis.domain[1];
  return ["", "2", "3"].filter((s) => layout[`yaxis${s}`]?.domain[1] === top).length;
}"""


def wait_top_row(page: Page, n: int) -> None:
    """Wait until the figure puts `n` panels in its top row."""
    page.wait_for_function(f"() => ({TOP_ROW_PANELS})() === {n}")


def test_wrap_replaces_group_x_and_wraps_the_panels(app_page: Page) -> None:
    """A column on Wrap removes Group X's and draws a panel per level, labeled by the level; the zone shows no number to a row."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    for column, role in [("y", "y"), ("facet", "col"), ("color", "wrap")]:
        place(page, column, role)
    wrap = page.locator('.zone[data-role="wrap"]')
    expect(page.locator('.zone[data-role="col"] .chip')).to_have_count(0)
    page.wait_for_function(PAINTED_PIXEL)
    expect(page.locator("#plot .annotation-text")).to_have_text(["a", "b", "c"])
    expect(wrap.locator("input")).to_have_count(0)
    expect(wrap).not_to_contain_text("自動")


def test_the_wrap_form_sets_the_panels_to_a_row(app_page: Page) -> None:
    """A right click on Wrap opens the form of the panels to a row: a draft until applied, checked, and replotted only for a new number."""
    page = app_page
    plots: list[str] = []
    page.on(
        "request",
        lambda r: plots.append(r.url) if r.url.endswith("/api/plot") else None,
    )
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    wrap = page.locator('.zone[data-role="wrap"]')
    form = page.locator(".wrap-menu")
    automatic = form.get_by_role("radio", name=re.compile("^自動"))
    manual = form.get_by_role("radio", name="指定")
    field = form.get_by_label("パネル数")
    error = form.locator(".wrap-menu-error")

    # An empty Wrap opens nothing.
    wrap.click(button="right")
    expect(form).to_have_count(0)

    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "color", "wrap")
    page.wait_for_function(PAINTED_PIXEL)
    wrap.locator(".chip-name").click(button="right")
    expect(form).to_be_visible()
    expect(form.locator(".scale-menu-heading")).to_have_text("1 行のパネル数")
    label = form.locator(".wrap-menu-choice").first
    expect(label).to_have_text(re.compile(r"^自動（\d+）$"))
    auto = int(re.search(r"\d+", label.inner_text()).group())
    wait_top_row(page, auto)
    expect(automatic).to_be_checked()
    expect(field).to_be_disabled()
    expect(field).to_have_value("")
    # The form stays in the window, though Wrap lies at its right edge.
    box = form.bounding_box()
    width = page.viewport_size["width"]
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= width

    # Bad numbers show the error and keep the plot; blank is not automatic.
    manual.check()
    expect(field).to_be_enabled()
    count = len(plots)
    for bad in ["", "0", "-1", "+2", "1.5", "1e2", "２", "9007199254740992"]:
        field.fill(bad)
        field.press("Enter")
        expect(error).to_have_text(
            "1 以上 9007199254740991 以下の整数を入力してください"
        )
        expect(form).to_be_visible()
    page.wait_for_timeout(300)
    assert len(plots) == count
    wait_top_row(page, auto)

    # A good number with blanks and leading zeros, by the apply button: one to a row.
    field.fill(" 01 ")
    expect(error).to_be_hidden()
    form.get_by_role("button", name="適用").click()
    expect(form).to_have_count(0)
    wait_top_row(page, 1)
    page.wait_for_function(SETTLED)
    assert len(plots) == count + 1

    # Reopened on the room beside the chip: the number set, as an integer.
    zone = wrap.bounding_box()
    assert zone is not None
    wrap.click(
        button="right", position={"x": zone["width"] - 4, "y": zone["height"] / 2}
    )
    expect(manual).to_be_checked()
    expect(field).to_have_value("1")
    # Still the automatic number of the size, not the one set.
    expect(label).to_have_text(f"自動（{auto}）")

    # Escape, a click outside and another right click drop the draft.
    automatic.check()
    page.keyboard.press("Escape")
    expect(form).to_have_count(0)
    wrap.locator(".chip-name").click(button="right")
    expect(field).to_have_value("1")
    field.fill("2")
    page.locator('.zone[data-role="col"]').click()
    expect(form).to_have_count(0)
    wrap.locator(".chip-name").click(button="right")
    field.fill("3")
    # Above the form, which opened at the middle of the chip.
    wrap.click(button="right", position={"x": 2, "y": 1})
    expect(form).to_have_count(1)
    expect(field).to_have_value("1")
    # The same number again plots nothing.
    field.press("Enter")
    expect(form).to_have_count(0)
    page.wait_for_timeout(300)
    assert len(plots) == count + 1

    # More than the levels: three to a row, the number set kept.
    wrap.locator(".chip-name").click(button="right")
    field.fill("10")
    field.press("Enter")
    wait_top_row(page, 3)
    page.wait_for_function(SETTLED)
    wrap.locator(".chip-name").click(button="right")
    expect(field).to_have_value("10")

    # Back to automatic, applied by Enter on the choice.
    automatic.check()
    expect(field).to_be_disabled()
    expect(field).to_have_value("")
    automatic.press("Enter")
    expect(form).to_have_count(0)
    wait_top_row(page, auto)
    page.wait_for_function(SETTLED)

    # A new size gives a new automatic number, shown while one is set.
    wrap.locator(".chip-name").click(button="right")
    manual.check()
    field.fill("1")
    field.press("Enter")
    wait_top_row(page, 1)
    page.wait_for_function(SETTLED)
    size = page.viewport_size
    width = "document.getElementById('plot').layout.width"
    before = page.evaluate(width)
    page.set_viewport_size({"width": 1280, "height": 400})
    page.wait_for_function(f"{width} !== {before}")
    page.wait_for_function(SETTLED)
    wait_top_row(page, 1)
    wrap.locator(".chip-name").click(button="right")
    resized = int(re.search(r"\d+", label.inner_text()).group())
    assert resized != auto
    automatic.check()
    automatic.press("Enter")
    wait_top_row(page, resized)
    page.wait_for_function(SETTLED)
    page.set_viewport_size(size)
    wait_top_row(page, auto)
    page.wait_for_function(SETTLED)

    # Without Y there is no figure: no number shown, the setting kept and
    # used by the next plot.
    page.locator('.zone[data-role="y"] .chip-remove').click()
    expect(page.locator("#empty")).to_be_visible()
    count = len(plots)
    wrap.locator(".chip-name").click(button="right")
    expect(label).to_have_text("自動")
    manual.check()
    field.fill("2")
    field.press("Enter")
    page.wait_for_timeout(300)
    assert len(plots) == count
    expect(page.locator("#empty")).to_be_visible()
    place(page, "y", "y")
    wait_top_row(page, 2)
    # Another column elsewhere keeps the number.
    place(page, "facet", "overlay")
    wait_top_row(page, 2)

    # A wrap column whose plot fails (too many levels) closes the form and
    # keeps the column and the number (Issue #101).
    wrap.locator(".chip-name").click(button="right")
    expect(form).to_be_visible()
    page.locator("#columns .column").filter(
        has=page.get_by_text("label", exact=True)
    ).drag_to(wrap)
    expect(form).to_have_count(0)
    expect(page.locator("#status")).to_have_class("notice-error")
    expect(wrap.locator(".chip-name")).to_have_text("color")
    # The error's toast lies over Wrap.
    toasts = page.locator("#toasts .toast")
    toasts.get_by_role("button", name="閉じる").click()
    expect(toasts).to_have_count(0)
    wrap.locator(".chip-name").click(button="right")
    expect(field).to_have_value("2")
    page.keyboard.press("Escape")
    wait_top_row(page, 2)
    # Another wrap column goes back to automatic.
    place(page, "facet", "wrap")
    wrap.locator(".chip-name").click(button="right")
    expect(automatic).to_be_checked()


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
    # The row of a null color is a series of its own (Show null rows).
    expect(page.locator("#plot .xtick text")).to_have_text(["a", "b", "c", "(null)"])
    points.click()
    expect(points).to_have_attribute("aria-pressed", "false")

    values = scatter_frame.filter(pl.col("color") == "b", pl.col("y").is_finite())["y"]
    median = float(values.median())
    # The box of b lies under its tick, the second of the band's.
    at = page.wait_for_function(
        """(median) => {
          const gd = document.getElementById("plot");
          const full = gd._fullLayout;
          const status = document.querySelector("#status").textContent;
          if (!full?.xaxis || !status.includes("外れ値")) return null;
          const rect = gd.getBoundingClientRect();
          return {
            x: rect.left + full.xaxis._offset + full.xaxis.l2p(full.xaxis.tickvals[1]),
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


@pytest.mark.parametrize(
    "settings",
    [Settings(plot=PlotSettings(legend=LegendSettings(inactive_opacity=0.0)))],
)
def test_inactive_series_at_opacity_0_vanish_and_do_not_hover(app_page: Page) -> None:
    """With ``plot.legend.inactive_opacity = 0``, inactive series draw nothing (smoothing lines and their white edges neither) and the hover does not find them; their legend items stay clickable."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    for column, role in [("y", "y"), ("color", "color")]:
        place(page, column, role)
    page.locator("#elements .element").nth(2).click()
    page.wait_for_function(SETTLED)
    pixel = page.wait_for_function(PAINTED_PIXEL).json_value()
    page.mouse.move(pixel["x"], pixel["y"])
    expect(page.locator("#hover-label")).to_be_visible()
    page.mouse.move(0, 0)

    # The row of a null color is the fourth item (Show null rows).
    items = page.locator("#legend .legend-item")
    expect(items).to_have_count(4)
    for i in range(4):
        items.nth(i).click()
    expect(page.locator("#legend .legend-item.inactive")).to_have_count(4)
    # The legend's own items stay at app.css's opacity.
    expect(items.first).to_have_css("opacity", "0.35")
    page.wait_for_function(f"() => ({PAINTED_PIXEL})() === null")
    with page.expect_response(lambda r: "/api/hover" in r.url) as hover:
        page.mouse.move(pixel["x"], pixel["y"])
    assert "hidden=" in hover.value.url
    assert hover.value.json()["hit"] is None
    expect(page.locator("#hover-label")).to_be_hidden()

    items.first.click()
    page.wait_for_function(PAINTED_PIXEL)


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



def test_an_overlay_level_takes_a_shape_picked_on_its_marker(app_page: Page) -> None:
    """An overlay item's marker opens a menu whose shape panel redraws the level in another shape; another overlay column drops it."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    for column, role in [("y", "y"), ("color", "color"), ("facet", "overlay")]:
        place(page, column, role)
    page.wait_for_function(PAINTED_PIXEL)
    legend = page.locator("#legend")
    shapes = legend.locator(".legend-item").filter(has=page.locator("canvas"))
    expect(shapes).to_have_count(2)
    sample = shapes.nth(1).locator("canvas")
    before = sample.evaluate("(canvas) => canvas.toDataURL()")
    marker = shapes.nth(1).locator(".legend-marker")
    expect(marker).to_have_attribute(
        "title", "右クリックでこの水準の形と大きさを変える"
    )

    # The color legend's markers have no shape item.
    legend.locator(".legend-marker").first.click(button="right")
    menu = page.locator(".shape-menu")
    expect(menu.locator(".color-item")).to_have_count(1)
    expect(menu.locator(".shape-item")).to_have_count(0)
    page.keyboard.press("Escape")

    status = page.locator("#status")
    task = status.inner_text()
    marker.click(button="right")
    expect(menu.locator(".scale-menu-item").first).to_have_text("形")
    expect(menu.locator(".scale-menu-item.checked")).to_have_text("7 px")
    menu.get_by_text("形", exact=True).hover()
    panel = page.locator(".shape-panel")
    expect(panel).to_be_visible()
    expect(panel.locator(".shape-cell")).to_have_count(12)
    # The second level takes the second shape.
    expect(panel.locator(".shape-cell.current")).to_have_attribute(
        "data-shape", "square"
    )
    # Away to a size, the panel closes.
    menu.get_by_text("9 px", exact=True).hover()
    expect(panel).to_have_count(0)
    menu.get_by_text("形", exact=True).hover()
    panel.locator('.shape-cell[data-shape="x"]').click()
    expect(menu).to_have_count(0)
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    page.wait_for_function(PAINTED_PIXEL)
    assert sample.evaluate("(canvas) => canvas.toDataURL()") != before

    marker.click(button="right")
    menu.get_by_text("形", exact=True).hover()
    expect(panel.locator(".shape-cell.current")).to_have_attribute("data-shape", "x")
    # The size stays as it was.
    expect(menu.locator(".scale-menu-item.checked")).to_have_text("7 px")
    task = status.inner_text()
    panel.get_by_text("既定の形に戻す").click()
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    assert sample.evaluate("(canvas) => canvas.toDataURL()") == before

    # The shape stays while the overlay column does, and goes with another.
    marker.click(button="right")
    menu.get_by_text("形", exact=True).hover()
    panel.locator('.shape-cell[data-shape="x"]').click()
    page.wait_for_function(SETTLED)
    assert sample.evaluate("(canvas) => canvas.toDataURL()") != before
    page.locator('.zone[data-role="color"] .chip-remove').click()
    page.wait_for_function(SETTLED)
    place(page, "color", "overlay")
    place(page, "facet", "overlay")
    place(page, "color", "color")
    page.wait_for_function(PAINTED_PIXEL)
    assert sample.evaluate("(canvas) => canvas.toDataURL()") == before


# The colors of the opaque pixels of the image layers, as "r,g,b".
OPAQUE_COLORS = """() => {
  const canvas = document.querySelector("canvas.image-layers");
  const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  const colors = new Set();
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] === 255) colors.add(`${data[i]},${data[i + 1]},${data[i + 2]}`);
  }
  return [...colors];
}"""


def test_overlay_alone_draws_shapes_of_one_color(app_page: Page) -> None:
    """Overlay without a color column draws its levels in shapes of 7 px and one color, with the shape legend alone, whose markers change a level's size and shape."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    page.wait_for_function(PAINTED_PIXEL)
    one_color = page.evaluate(OPAQUE_COLORS)
    assert len(one_color) == 1
    place(page, "facet", "overlay")
    page.wait_for_function(PAINTED_PIXEL)
    legend = page.locator("#legend")
    items = legend.locator(".legend-item")
    shapes = items.filter(has=page.locator("canvas"))
    # The shape legend alone: every item is a shape, under the one title.
    expect(shapes).to_have_count(2)
    expect(items).to_have_count(2)
    expect(legend.locator(".legend-title")).to_have_count(1)
    expect(legend.locator(".legend-title")).to_have_text("facet")
    expect(shapes.first.locator("canvas")).to_have_attribute("width", "7")
    expect(shapes.nth(1).locator("canvas")).to_have_attribute("width", "7")
    assert page.evaluate(OPAQUE_COLORS) == one_color

    status = page.locator("#status")
    task = status.inner_text()
    marker = shapes.nth(1).locator(".legend-marker")
    marker.click(button="right")
    menu = page.locator(".shape-menu")
    expect(menu.locator(".scale-menu-item.checked")).to_have_text("7 px")
    menu.get_by_text("11 px", exact=True).click()
    expect(menu).to_have_count(0)
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    expect(shapes.nth(1).locator("canvas")).to_have_attribute("width", "11")
    expect(shapes.first.locator("canvas")).to_have_attribute("width", "7")

    task = status.inner_text()
    marker.click(button="right")
    menu.get_by_text("形", exact=True).hover()
    panel = page.locator(".shape-panel")
    expect(panel.locator(".shape-cell.current")).to_have_attribute(
        "data-shape", "square"
    )
    panel.locator('.shape-cell[data-shape="x"]').click()
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    marker.click(button="right")
    menu.get_by_text("形", exact=True).hover()
    expect(panel.locator(".shape-cell.current")).to_have_attribute("data-shape", "x")
    page.keyboard.press("Escape")
    assert page.evaluate(OPAQUE_COLORS) == one_color


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
    """A color picked before the images of a view are decoded draws them in that color.

    A plot's figure and legend change only once its images are decoded
    (Issue #101), so the images decoding under the legend are a view's.
    """
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "color", "color")
    page.wait_for_function(PAINTED_PIXEL)
    page.evaluate(HOLD_IMAGES)
    with page.expect_response("**/api/view"):
        page.evaluate("Plotly.relayout('plot', {'xaxis.range': [-0.5, 0.5]})")
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
    """Without drawn axes, X and Y are split into equal regions per column: the first quarter of the n-th goes in before the n-th axis, the last quarter after it, the middle half replaces it."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    x_zone = page.locator('.zone[data-role="x"]')
    y_zone = page.locator('.zone[data-role="y"]')
    x_names = x_zone.locator(".chip-name")
    y_names = y_zone.locator(".chip-name")

    def drop(column: str, zone: Locator, x: float, y: float) -> None:
        page.locator("#columns .column").filter(
            has=page.get_by_text(column, exact=True)
        ).drag_to(zone, target_position={"x": x, "y": y})

    # X runs left to right; Y is empty, so nothing is drawn. One axis: the whole zone is its region.
    place(page, "x", "x", plots=False)
    zone = x_zone.bounding_box()
    middle = zone["height"] / 2
    drop("y", x_zone, zone["width"] * 0.4, middle)
    expect(x_names).to_have_text(["y"])
    drop("x", x_zone, zone["width"] * 0.9, middle)
    expect(x_names).to_have_text(["y", "x"])
    # Two axes: the end of the first half goes in between them.
    drop("facet", x_zone, zone["width"] * 0.45, middle)
    expect(x_names).to_have_text(["y", "facet", "x"])
    # Three axes: the middle of the third replaces the third.
    drop("color", x_zone, zone["width"] * 5 / 6, middle)
    expect(x_names).to_have_text(["y", "facet", "color"])
    for _ in range(3):
        x_zone.locator(".chip-remove").first.click()
    expect(x_names).to_have_count(0)

    # Y runs top to bottom; categorical columns without X draw nothing.
    place(page, "color", "y", plots=False)
    zone = y_zone.bounding_box()
    center = zone["width"] / 2
    drop("facet", y_zone, center, zone["height"] * 0.1)
    expect(y_names).to_have_text(["facet", "color"])
    # The start of the second half goes in between them.
    drop("label", y_zone, center, zone["height"] * 0.55)
    expect(y_names).to_have_text(["facet", "label", "color"])
    # The middle of the first third replaces the first.
    drop("x", y_zone, center, zone["height"] / 6)
    expect(y_names).to_have_text(["x", "label", "color"])


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

    # An axis's tick labels open the axis's own menu (Issue #90; the x ticks
    # lie under the table); the mode bar opens none.
    tick = page.locator("#plot .ytick text").first.bounding_box()
    page.mouse.click(
        tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2, button="right"
    )
    expect(page.locator(".axis-menu")).to_be_visible()
    expect(menu).to_have_count(0)
    page.keyboard.press("Escape")
    page.locator('#plot .modebar-btn[data-val="pan"]').click(button="right")
    expect(menu).to_have_count(0)
    assert plots == []


def test_sort_by_picks_name_or_count_and_picking_it_again_restores_the_file_order(
    app_page: Page,
) -> None:
    """"Sort by" opens Name and Count, checks the order in use, and picking it again goes back to the file order; Count waits for the shares (Issue #67)."""
    page = app_page
    names = page.locator("#columns .column-name")
    button = page.locator(".column-order")
    menu = page.locator(".sort-menu")
    expect(names).to_have_text(["x", "y", "label", "color", "facet"])
    expect(page.locator(".column-hide-empty")).to_be_enabled()

    def pick(text: str) -> None:
        button.click()
        menu.get_by_text(text, exact=True).click()
        expect(menu).to_have_count(0)

    button.click()
    expect(menu.locator(".scale-menu-item")).to_have_text(["Name", "Count"])
    expect(menu.locator(".checked")).to_have_count(0)
    menu.get_by_text("Name", exact=True).click()
    expect(names).to_have_text(["color", "facet", "label", "x", "y"])
    expect(button).to_have_text("Sort by")
    button.click()
    expect(menu.locator(".checked")).to_have_text("Name")
    menu.get_by_text("Count", exact=True).click()
    # x and color hold a null each; ties keep the file order.
    expect(names).to_have_text(["y", "label", "facet", "x", "color"])
    pick("Count")
    expect(names).to_have_text(["x", "y", "label", "color", "facet"])
    button.click()
    expect(menu.locator(".checked")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)

    def pending(route: Route) -> None:
        found = route.fetch().json()
        found["shares"] = "pending"
        route.fulfill(json=found)

    page.route("**/api/columns?*", pending)
    page.reload()
    expect(names.first).to_be_visible()
    button.click()
    expect(menu.get_by_text("Count", exact=True)).to_be_disabled()
    menu.get_by_text("Name", exact=True).click()
    expect(names).to_have_text(["color", "facet", "label", "x", "y"])


def test_a_double_click_on_a_numeric_axis_sets_its_range_ticks_and_lines(
    app_page: Page,
) -> None:
    """The axis dialog checks its fields, aggregates the range it sets, and draws ticks and lines on every panel of the column; going back to the overview keeps them."""
    page = app_page
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "facet", "col")
    views: list[str] = []
    page.on("request", lambda r: "/api/view" in r.url and views.append(r.url))
    dialog = page.locator("dialog.axis-dialog")
    full = "document.getElementById('plot')._fullLayout"

    tick = page.locator("#plot .ytick text").first.bounding_box()
    page.mouse.dblclick(tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2)
    expect(dialog).to_be_visible()
    expect(dialog.locator("h2")).to_have_text("Y 軸: y")
    shown = page.evaluate(f"{full}.yaxis.range")
    assert float(dialog.locator("input[name=min]").input_value()) == pytest.approx(
        shown[0]
    )

    # Wrong fields tell why beside them and change nothing.
    dialog.locator("input[name=min]").fill("3")
    dialog.locator("input[name=max]").fill("2")
    dialog.locator("input[name=dtick]").fill("-1")
    dialog.locator("input[name=minor]").fill("5")
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_be_visible()
    errors = dialog.locator(".axis-dialog-error")
    expect(errors).to_have_text(
        ["", "最小値より大きくしてください", "0 より大きくしてください", "", "", ""]
    )
    dialog.locator("input[name=line]").fill("a")
    dialog.get_by_role("button", name="追加").click()
    expect(errors.nth(5)).to_have_text("数値を入れてください")
    assert views == []

    dialog.locator("input[name=min]").fill("-1")
    dialog.locator("input[name=max]").fill("1")
    dialog.locator("input[name=dtick]").fill("0.5")
    dialog.locator("input[name=line]").fill("0.25")
    dialog.get_by_role("button", name="追加").click()
    expect(dialog.locator(".axis-dialog-line")).to_have_count(1)
    dialog.get_by_role("button", name="適用").click()
    expect(page.locator("#status")).to_contain_text("表示範囲に")
    page.wait_for_function(SETTLED)
    expect(dialog).to_be_visible()
    assert len(views) == 1
    # Both panels of y share the range, the ticks and the line.
    axes = page.evaluate(
        f"['yaxis', 'yaxis2'].map((k) => [{full}[k].range, {full}[k].dtick, {full}[k].minor.dtick])"
    )
    assert axes == [[[-1, 1], 0.5, 0.1], [[-1, 1], 0.5, 0.1]]
    shapes = page.evaluate(f"{full}.shapes.map((s) => [s.yref, s.xref, s.y0, s.line.dash])")
    assert shapes == [["y", "x domain", 0.25, "dash"], ["y2", "x2 domain", 0.25, "dash"]]
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)

    # A double click on the plot area goes back to the overview's range; the
    # ticks and the line stay.
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator("#status")).not_to_contain_text("表示範囲に")
    assert page.evaluate(f"{full}.yaxis.range") == pytest.approx(shown)
    assert page.evaluate(f"[{full}.yaxis.dtick, {full}.shapes.length]") == [0.5, 2]
    assert len(views) == 1

    # Emptied ticks and no lines are plotly's own again.
    page.mouse.dblclick(tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2)
    dialog.locator("input[name=dtick]").fill("")
    dialog.locator("input[name=minor]").fill("")
    dialog.get_by_role("button", name="削除").click()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    assert page.evaluate(f"[{full}.yaxis.tickmode, {full}.shapes.length]") == ["auto", 0]


def test_a_double_click_on_a_categorical_axis_opens_no_dialog(app_page: Page) -> None:
    """A categorical axis keeps plotly's double click: no dialog opens."""
    page = app_page
    place(page, "color", "x", plots=False)
    place(page, "y", "y")
    tick = page.locator("#plot .xtick text").first.bounding_box()
    page.mouse.dblclick(tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2)
    page.wait_for_timeout(300)
    expect(page.locator("dialog.axis-dialog")).to_have_count(0)


def test_the_strips_of_a_scrolled_grid_open_the_axis_dialog(app_page: Page) -> None:
    """Scrolled, the tick labels in the strips open their axis's dialog, not the plot's reset; a range of many digits comes back whole."""
    page = app_page
    page.set_viewport_size({"width": 800, "height": 600})
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "facet", "col")
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    page.locator("#scroller").evaluate(SCROLL_AND_SETTLE, 10_000)
    assert page.locator("#scroller").evaluate("(s) => s.scrollLeft") > 0
    dialog = page.locator("dialog.axis-dialog")
    full = "document.getElementById('plot')._fullLayout"

    for side, title in [("y", "Y 軸: y"), ("x", "X 軸: x")]:
        tick = page.locator(f".sticky-strip .tick.{side}").evaluate_all(BOXES)[-1]
        page.mouse.dblclick(
            tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2
        )
        expect(dialog.locator("h2")).to_have_text(title)
        shown = page.evaluate(f"{full}.{side}axis.range")
        values = [
            float(dialog.locator(f"input[name={name}]").input_value())
            for name in ["min", "max"]
        ]
        # The fields hold the very numbers of the range.
        assert values == shown
        dialog.get_by_role("button", name="キャンセル").click()
        expect(dialog).to_have_count(0)


def placed_names(page: Page) -> dict[str, list[str]]:
    """Return the column names on each role's zone, in their order."""
    return {
        role: page.locator(f'.zone[data-role="{role}"] .chip-name').all_inner_texts()
        for role in ["x", "y", "col", "row", "wrap", "color", "overlay"]
    }


def watch_errors(page: Page) -> list[str]:
    """Collect the page's errors and console errors from now on.

    A failed load is left out: Chromium asks for the favicon without the
    cookie (`docs/spec.md`, "認証").
    """
    errors: list[str] = []

    def console(message: ConsoleMessage) -> None:
        if message.type == "error" and not message.text.startswith(
            "Failed to load resource"
        ):
            errors.append(message.text)

    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", console)
    return errors


@pytest.mark.parametrize(
    ("role", "column", "index"),
    [
        ("x", "x", 0),
        ("y", "y", 0),
        ("x", "y", 1),
        ("y", "x", 1),
        ("col", "facet", 0),
        ("row", "facet", 0),
        ("wrap", "facet", 0),
        ("color", "color", 0),
        ("overlay", "color", 0),
    ],
)
def test_a_chip_dragged_to_the_filters_adds_a_card_and_stays_placed(
    app_page: Page, role: str, column: str, index: int
) -> None:
    """A chip of any role, a second axis's too, dragged with the mouse to the filter pane adds a card and keeps every role as it was."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    if index:
        # The end of the zone adds a second axis after the first.
        zone = page.locator(f'.zone[data-role="{role}"]').bounding_box()
        if role == "x":
            drop_at(page, column, role, zone["width"] * 0.9, zone["height"] / 2)
        else:
            drop_at(page, column, role, zone["width"] / 2, zone["height"] * 0.9)
    elif role not in ("x", "y"):
        place(page, column, role)
    before = placed_names(page)
    chip = page.locator(f'.zone[data-role="{role}"] .chip').nth(index)
    expect(chip.locator(".chip-name")).to_have_text(column)

    chip.drag_to(page.locator("#filters"))
    expect(page.locator(".filter-card-name")).to_have_text([column])
    assert placed_names(page) == before
    # The card alone sets no condition.
    expect(page.locator(".filter-summary")).to_have_text("")
    expect(page.locator("#drop-tip")).to_be_hidden()
    expect(page.locator("#filters")).not_to_have_class(re.compile(r"\bover\b"))
    page.wait_for_function(SETTLED)
    assert errors == []


def test_chips_dragged_to_the_filters_make_the_cards_the_column_list_makes(
    app_page: Page,
) -> None:
    """A numeric chip gets a range card and a categorical one a card of levels whose conditions filter the plot; a column already carded is refused and keeps its condition; a folded pane takes a drop on its head and opens; the builder still moves and removes chips afterwards."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "color", "color")
    filters = page.locator("#filters")
    status = page.locator("#status")
    x_chip = page.locator('.zone[data-role="x"] .chip')

    x_chip.drag_to(filters)
    card = page.locator(".filter-card")
    expect(card.locator(".filter-range input")).to_have_count(2)
    lo, hi = card.locator(".filter-range input").all()
    task = status.inner_text()
    lo.fill("0")
    hi.fill("10")
    hi.press("Enter")
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    expect(status).to_contain_text("（フィルタ後）")
    summary = page.locator(".filter-summary")
    expect(summary).to_contain_text("x:")
    condition = summary.inner_text()
    task = status.inner_text()

    # The same column again: refused, with the tip saying so while it hovers.
    x_chip.hover()
    page.mouse.down()
    box = filters.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=5)
    # The drag starts on the first moves; this one is a dragover on the pane.
    page.mouse.move(box["x"] + box["width"] / 2 + 1, box["y"] + box["height"] / 2)
    expect(page.locator("#drop-tip")).to_have_text("x はフィルタにある")
    expect(filters).not_to_have_class(re.compile(r"\bover\b"))
    page.mouse.up()
    expect(page.locator("#drop-tip")).to_be_hidden()
    expect(card).to_have_count(1)
    expect(summary).to_have_text(condition)
    expect(lo).to_have_value("0")
    expect(status).to_have_text(task)
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text(["x"])

    # A folded pane takes the drop on its head and opens.
    page.locator(".filter-toggle").click()
    expect(filters).to_have_class(re.compile(r"\bcollapsed\b"))
    page.locator('.zone[data-role="color"] .chip').drag_to(page.locator(".filter-head"))
    expect(filters).not_to_have_class(re.compile(r"\bcollapsed\b"))
    levels = page.locator(".filter-card").nth(1).locator(".filter-level")
    expect(levels).not_to_have_count(0)
    expect(page.locator('.zone[data-role="color"] .chip-name')).to_have_text(["color"])
    levels.filter(has=page.get_by_text("a", exact=True)).locator("input").check()
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    expect(summary).to_contain_text("color:")

    # The builder still moves a chip between roles and removes one dropped outside.
    page.locator('.zone[data-role="color"] .chip').drag_to(
        page.locator('.zone[data-role="overlay"]')
    )
    expect(page.locator('.zone[data-role="overlay"] .chip-name')).to_have_text(
        ["color"]
    )
    expect(page.locator('.zone[data-role="color"] .chip')).to_have_count(0)
    page.wait_for_function(SETTLED)
    page.locator('.zone[data-role="overlay"] .chip').drag_to(page.locator("#columns"))
    expect(page.locator('.zone[data-role="overlay"] .chip')).to_have_count(0)
    expect(page.locator(".filter-card")).to_have_count(2)
    page.wait_for_function(SETTLED)
    assert errors == []


def dialog_at(page: Page, x: float, y: float) -> str | None:
    """Double-click a point and return the title of the axis dialog it opens, or None; cancel it.

    It waits first for longer than plotly's double click (300ms): the first
    press of each double click reaches plotly, which would count it with
    the previous one.
    """
    page.wait_for_timeout(400)
    page.mouse.dblclick(x, y)
    dialog = page.locator("dialog.axis-dialog")
    page.wait_for_timeout(100)
    if not dialog.count():
        return None
    expect(dialog).to_have_count(1)
    title = dialog.locator("h2").inner_text()
    dialog.get_by_role("button", name="キャンセル").click()
    expect(dialog).to_have_count(0)
    return title


def test_a_double_click_on_the_left_margin_of_y_opens_its_dialog(
    app_page: Page,
) -> None:
    """The whole margin left of a numeric y opens its dialog once, keeping the zoom and asking nothing; the plot area's edge, the y zone and its chip open none."""
    from tests.e2e.test_axis_menu import margin_points, y_margins

    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    full = "document.getElementById('plot')._fullLayout"
    page.evaluate("Plotly.relayout('plot', {'yaxis.range': [-0.5, 0.5]})")
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    expect(page.locator("#status")).to_contain_text("表示範囲に")
    asked: list[str] = []
    page.on(
        "request",
        lambda r: re.search(r"/api/(plot|view|overview)\b", r.url) and asked.append(r.url),
    )
    margins = y_margins(page)
    (row,) = margins["rows"]
    for x, y in margin_points(margins, row):
        assert dialog_at(page, x, y) == "Y 軸: y", (x, y)
    assert page.evaluate(f"{full}.yaxis.range") == [-0.5, 0.5]
    expect(page.locator("#status")).to_contain_text("表示範囲に")

    # The y zone, its blank and its chip, open no dialog.
    middle = (row["top"] + row["bottom"]) / 2
    zone = page.locator('.zone[data-role="y"]')
    chip = zone.locator(".chip-name").bounding_box()
    assert dialog_at(page, margins["zone"] - 3, row["bottom"] - 5) is None
    assert dialog_at(page, chip["x"] + chip["width"] / 2, chip["y"] + chip["height"] / 2) is None
    expect(zone.locator(".chip-name")).to_have_text("y")
    assert asked == []

    # The left edge of the plot area goes back to the overview.
    assert dialog_at(page, row["left"] + 2, middle) is None
    page.wait_for_function(f"() => {full}.yaxis.range[0] < -0.5")
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)

    # A selection stays, as the range does.
    shown = page.evaluate(f"{full}.yaxis.range")
    selections = box_select(page)
    below = table_top(page)
    points = [(x, y) for x, y in margin_points(margins, row) if y < below - 2]
    assert len(points) >= 8
    for x, y in points:
        assert dialog_at(page, x, y) == "Y 軸: y", (x, y)
    assert selections == []
    expect(page.locator("#table")).to_be_visible()
    assert page.evaluate(f"{full}.yaxis.range") == shown
    assert errors == []


def test_the_margin_of_an_axis_without_a_dialog_opens_none(app_page: Page) -> None:
    """The margin of a categorical or log y opens no dialog, and the menu's items as before."""
    from tests.e2e.test_axis_menu import y_margins

    page = app_page
    place(page, "x", "x", plots=False)
    place(page, "color", "y")
    margins = y_margins(page)
    (row,) = margins["rows"]
    point = ((margins["zone"] + row["left"]) / 2, row["between"])
    assert dialog_at(page, *point) is None

    place(page, "y", "y")
    margins = y_margins(page)
    (row,) = margins["rows"]
    point = (margins["zone"] + 1, (row["top"] + row["bottom"]) / 2)
    page.mouse.click(*point, button="right")
    menu = page.locator(".axis-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text("Y 軸: y")
    menu.get_by_role("button", name="対数表示").click()
    page.wait_for_function(
        "() => document.getElementById('plot')._fullLayout.yaxis.type === 'log'"
    )
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    assert dialog_at(page, *point) is None
    page.mouse.click(*point, button="right")
    expect(menu.get_by_role("button", name="対数表示")).to_have_class(
        "scale-menu-item checked"
    )
    page.keyboard.press("Escape")


def box_select(page: Page) -> list[str]:
    """Select rows with a Box Select drag in the middle of the stage, fold the table, and return the list of the requests on the selection from then on.

    The table lies over the bottom of the stage, which is its own: folded,
    only its bar does (`table_top`).
    """
    page.evaluate("Plotly.relayout('plot', {dragmode: 'select'})")
    stage = page.locator("#stage").bounding_box()
    x, y = stage["x"] + stage["width"] / 2, stage["y"] + stage["height"] / 2
    with page.expect_request("**/api/selection"):
        page.mouse.move(x - 30, y - 30)
        page.mouse.down()
        page.mouse.move(x + 30, y + 30, steps=5)
        page.mouse.up()
    expect(page.locator("#table")).to_be_visible()
    page.locator("#table .table-down").click()
    expect(page.locator("#table")).to_have_class(re.compile(r"\bcollapsed\b"))
    page.wait_for_timeout(300)
    asked: list[str] = []
    page.on(
        "request",
        lambda r: "/api/selection" in r.url and asked.append(f"{r.method} {r.url}"),
    )
    return asked


def table_top(page: Page) -> float:
    """Return the top of the table (client pixels), or infinity while it is hidden."""
    box = page.locator("#table").bounding_box()
    return box["y"] if box else math.inf


# Scrolls a grid to a point and waits for the strips to follow.
SCROLL_TO = """async (s, [left, top]) => {
  s.scrollLeft = left;
  s.scrollTop = top;
  s.dispatchEvent(new Event("scroll"));
  for (let i = 0; i < 2; i++) await new Promise((resolve) => requestAnimationFrame(resolve));
}"""


def test_the_left_strip_and_the_gap_left_of_it_open_their_rows_axis(
    app_page: Page,
) -> None:
    """Scrolled both ways and resized, the left strip, its left side and the gap left of it open the axis of the panel row at that height in sight, keeping the selection; above and below the strip, none."""
    from tests.e2e.test_axis_menu import add_second_y, menu_at, y_margins

    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 800, "height": 400})
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    add_second_y(page, "x")
    place(page, "facet", "col")
    place(page, "color", "row")
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    strip = page.locator(".sticky-strip.left")
    selections = box_select(page)

    for size in [None, {"width": 760, "height": 380}]:
        if size:
            page.set_viewport_size(size)
            page.wait_for_timeout(300)
            page.wait_for_function(SETTLED)
        scroller = page.locator("#scroller")
        scroller.evaluate(SCROLL_TO, [10_000, 90])
        assert scroller.evaluate("(s) => s.scrollLeft") > 0
        assert scroller.evaluate("(s) => s.scrollTop") > 0
        margins = y_margins(page)
        box = strip.bounding_box()
        top, bottom = box["y"], min(box["y"] + box["height"], table_top(page) - 2)
        xs = [
            margins["zone"] + 1,
            (margins["zone"] + margins["stage"]) / 2,
            box["x"] + 1,
            box["x"] + box["width"] - 1,
        ]
        # The levels of Group Y outside, the y columns inside.
        checked = 0
        for i, row in enumerate(margins["rows"]):
            seen = [max(row["top"], top), min(row["bottom"], bottom)]
            if seen[1] - seen[0] < 8:
                continue
            column = ["y", "x"][i % 2]
            ys = [(seen[0] + seen[1]) / 2]
            if seen[0] + 3 < row["between"] < seen[1] - 3:
                ys.append(row["between"])
            for x in xs:
                for y in ys:
                    assert menu_at(page, x, y) == f"Y 軸: {column}", (x, y, size)
                    assert dialog_at(page, x, y) == f"Y 軸: {column}", (x, y, size)
                    checked += 1
        assert checked >= 8
        # The x strip at the bottom left and the table's bar are not y's.
        assert menu_at(page, margins["zone"] + 1, bottom + 5) is None
    assert selections == []
    expect(page.locator("#table")).to_be_visible()
    assert errors == []
