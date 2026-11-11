"""E2E: the menu of an axis's tick labels puts its column on a log axis and back."""

from __future__ import annotations

import math

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import SETTLED, drop_at, place, watch_errors

pytestmark = pytest.mark.e2e

FULL = "document.getElementById('plot')._fullLayout"


# The y axes' left margins, in client pixels, from the DOM and plotly's
# layout (not from the width of the tick labels, which depends on the fonts):
# the right edge of the y zone, the left edge of the stage, and per panel row
# its top and bottom, the left of its leftmost plot area, and the height
# halfway between its first two tick labels.
Y_MARGINS = """() => {
  const gd = document.getElementById("plot");
  const full = gd._fullLayout;
  const o = gd.getBoundingClientRect();
  const rows = new Map();
  for (const key of Object.keys(full).filter((k) => /^yaxis[0-9]*$/.test(k))) {
    const ya = full[key];
    const xa = full[ya.anchor.replace(/^x/, "xaxis")];
    const top = o.top + ya._offset;
    const left = o.left + xa._offset;
    const ticks = ya._vals.filter((t) => !t.minor).map((t) => top + ya.l2p(t.x));
    const row = rows.get(top);
    if (!row || left < row.left) {
      rows.set(top, { top, bottom: top + ya._length, left, between: (ticks[0] + ticks[1]) / 2 });
    }
  }
  return {
    zone: document.querySelector('#builder > .zone[data-role="y"]').getBoundingClientRect().right,
    stage: document.getElementById("stage").getBoundingClientRect().left,
    rows: [...rows.values()].sort((a, b) => a.top - b.top),
  };
}"""


def y_margins(page: Page) -> dict:
    """Return the y axes' left margins (`Y_MARGINS`)."""
    return page.evaluate(Y_MARGINS)


def margin_points(margins: dict, row: dict) -> list[tuple[float, float]]:
    """Return points of a panel row's left margin: its left, middle and axis side, the gap left of the stage, at its top, bottom, middle and between two tick labels.

    The browser rounds the pointer to whole pixels: the edges are taken
    inside the row.
    """
    zone, left = margins["zone"], row["left"]
    xs = [zone + 1, (zone + left) / 2, left - 1, (zone + margins["stage"]) / 2]
    ys = [
        math.ceil(row["top"]),
        math.floor(row["bottom"]),
        (row["top"] + row["bottom"]) / 2,
        row["between"],
    ]
    return [(x, y) for x in xs for y in ys]


def add_second_y(page: Page, column: str) -> None:
    """Drop a column at the end of the y zone, as y's second axis."""
    zone = page.locator('.zone[data-role="y"]').bounding_box()
    drop_at(page, column, "y", zone["width"] / 2, zone["height"] * 0.95)
    expect(page.locator('.zone[data-role="y"] .chip-name')).to_have_count(2)


def menu_at(page: Page, x: float, y: float) -> str | None:
    """Right-click a point and return the heading of the axis menu it opens, or None; close the menus."""
    page.mouse.click(x, y, button="right")
    menu = page.locator(".axis-menu")
    heading = (
        menu.locator(".scale-menu-heading").inner_text() if menu.count() else None
    )
    if heading is not None:
        expect(menu).to_have_count(1)
        expect(page.locator(".plot-menu")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    expect(page.locator(".plot-menu")).to_have_count(0)
    return heading


def _right_click_tick(page: Page, side: str) -> None:
    """Right-click the middle tick label of plotly's `side` ("x" or "y") axis."""
    ticks = page.locator(f"#plot .{side}tick text")
    box = ticks.nth(ticks.count() // 2).bounding_box()
    page.mouse.click(
        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right"
    )


def _settled(page: Page) -> None:
    """Wait for the result of the last request."""
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)


def test_the_tick_menu_toggles_a_log_axis(app_page: Page) -> None:
    """Log x keeps y's zoom, warns of the rows not positive, survives Reset axes and goes back to linear."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    # A zoom of y, which the change of x's scale keeps.
    page.evaluate("Plotly.relayout('plot', {'yaxis.range': [-0.5, 0.5]})")
    _settled(page)

    _right_click_tick(page, "x")
    menu = page.locator(".axis-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text("X 軸: x")
    item = menu.get_by_role("button", name="対数表示")
    expect(item).to_be_enabled()
    expect(item).not_to_have_class("scale-menu-item checked")
    item.click()
    expect(menu).to_have_count(0)
    page.wait_for_function(f"() => {FULL}.xaxis.type === 'log'")
    _settled(page)
    page.wait_for_function(
        f"() => Math.abs({FULL}.yaxis.range[0] + 0.5) < 1e-9"
        f" && Math.abs({FULL}.yaxis.range[1] - 0.5) < 1e-9"
    )
    warning = page.locator("#log-warning")
    expect(warning).to_be_visible()
    expect(warning).to_have_text(
        "対数表示のため、X の x の0以下の値を持つ行を描画対象から除外しています"
    )
    # The x axis spans the exponents of the positive values (about 1e-4 to 4).
    lo, hi = page.evaluate(f"{FULL}.xaxis.range")
    assert -6 < lo < hi < 1

    # A zoom sends the values, not the exponents.
    with page.expect_request("**/api/view") as request:
        page.evaluate("Plotly.relayout('plot', {'xaxis.range': [-1, 0]})")
    (x_range,) = request.value.post_data_json["x_ranges"]
    assert x_range == [pytest.approx(0.1), pytest.approx(1.0)]
    _settled(page)

    # Reset axes keeps the log axis.
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.click(
        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right"
    )
    page.locator(".plot-menu").get_by_role("button", name="Reset axes").click()
    _settled(page)
    assert page.evaluate(f"{FULL}.xaxis.type") == "log"

    _right_click_tick(page, "x")
    item = page.locator(".axis-menu").get_by_role("button", name="対数表示")
    expect(item).to_have_class("scale-menu-item checked")
    item.click()
    page.wait_for_function(f"() => {FULL}.xaxis.type === 'linear'")
    _settled(page)
    expect(warning).to_be_hidden()
    assert errors == []


def test_the_log_item_of_a_categorical_axis_is_grayed_out(app_page: Page) -> None:
    """A categorical axis's menu shows the item disabled; Escape closes it."""
    page = app_page
    place(page, "color", "x")
    place(page, "y", "y")
    _right_click_tick(page, "x")
    menu = page.locator(".axis-menu")
    expect(menu.get_by_role("button", name="対数表示")).to_be_disabled()
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    # The middle of the plot keeps the plot's own menu.
    plot = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.click(
        plot["x"] + plot["width"] / 2, plot["y"] + plot["height"] / 2, button="right"
    )
    expect(page.locator(".plot-menu")).to_have_count(1)
    expect(page.locator(".axis-menu")).to_have_count(0)


def test_a_box_dragged_on_a_log_axis_selects_by_its_values(app_page: Page) -> None:
    """A Box Select drag on a log x sends the values under the box's edges, and the layer and table follow."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    _right_click_tick(page, "x")
    page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    page.wait_for_function(f"() => {FULL}.xaxis.type === 'log'")
    _settled(page)
    page.evaluate("Plotly.relayout('plot', {dragmode: 'select'})")
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    x0, x1 = box["x"] + box["width"] * 0.3, box["x"] + box["width"] * 0.7
    y0, y1 = box["y"] + box["height"] * 0.2, box["y"] + box["height"] * 0.8
    # The values plotly's x axis has at the box's left and right edges.
    expected = page.evaluate(
        f"""([a, b]) => {{
          const xa = {FULL}.xaxis;
          const left = document.querySelector('#plot .nsewdrag').getBoundingClientRect().left;
          return [a, b].map((p) => 10 ** xa.p2l(p - left));
        }}""",
        [x0, x1],
    )
    with page.expect_request("**/api/selection") as request:
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=5)
        page.mouse.up()
    x_range = request.value.post_data_json["x_range"]
    assert x_range == [pytest.approx(v, rel=1e-2) for v in expected]
    expect(page.locator("#table")).to_be_visible()
    # plotly's box stays where it was dragged.
    shown = page.evaluate(
        f"() => {{ const s = {FULL}.selections[0]; return [s.x0, s.x1].sort((a, b) => a - b); }}"
    )
    assert shown == [pytest.approx(v, rel=1e-2) for v in expected]
    # A view drawn again keeps the box at its values.
    page.evaluate("Plotly.relayout('plot', {'yaxis.range': [-2, 2]})")
    _settled(page)
    page.wait_for_function("() => !document.querySelector('#plot').classList.contains('pending')")
    again = page.evaluate(
        f"() => {{ const s = {FULL}.selections[0]; return [s.x0, s.x1].sort((a, b) => a - b); }}"
    )
    assert again == [pytest.approx(v, rel=1e-2) for v in expected]
    assert errors == []


def test_a_warning_keeps_the_height_of_the_status_bar(app_page: Page) -> None:
    """A warning's icon does not make the bar taller, which would shrink the plot area.

    A short line stands in for the font of the CI runner (Linux), where the
    icon made the bar taller and the overview was aggregated again
    (`docs/spec.md`, "フッターのエラーと警告").
    """
    page = app_page
    heights = page.evaluate(
        """() => {
          const bar = document.getElementById('statusbar');
          bar.style.lineHeight = '12px';
          const warning = document.getElementById('log-warning');
          const before = bar.getBoundingClientRect().height;
          warning.textContent = 'x が 0 以下の 1 行を描いていません';
          warning.hidden = false;
          return [before, bar.getBoundingClientRect().height];
        }"""
    )
    assert heights[1] == heights[0]


def test_the_left_margin_of_y_opens_its_menu(app_page: Page) -> None:
    """The whole margin left of y's tick labels, and the gap left of the stage, open y's menu; around it the plot's menu or none."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    margins = y_margins(page)
    (row,) = margins["rows"]
    for x, y in margin_points(margins, row):
        assert menu_at(page, x, y) == "Y 軸: y", (x, y)
    middle = (row["top"] + row["bottom"]) / 2
    halfway = (margins["zone"] + row["left"]) / 2
    # Above and below the panel, in the y zone and on the plot area: not y's.
    for x, y in [
        (halfway, row["top"] - 2),
        (halfway, row["bottom"] + 2),
        (margins["zone"] - 3, middle),
    ]:
        assert menu_at(page, x, y) is None, (x, y)
    page.mouse.click(row["left"] + 1, middle, button="right")
    expect(page.locator(".plot-menu")).to_have_count(1)
    expect(page.locator(".axis-menu")).to_have_count(0)
    page.keyboard.press("Escape")
    assert errors == []


def test_each_panel_row_of_the_margin_opens_its_own_column(app_page: Page) -> None:
    """With two y columns by Group Y, each row of the margin opens its row's column; with Wrap, the leftmost panel's; not between the rows nor on a panel's right edge."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    add_second_y(page, "x")
    place(page, "facet", "row")
    margins = y_margins(page)
    # The levels of Group Y outside, the y columns inside.
    assert len(margins["rows"]) == 4
    for row, column in zip(margins["rows"], ["y", "x", "y", "x"], strict=True):
        for x, y in margin_points(margins, row):
            assert menu_at(page, x, y) == f"Y 軸: {column}", (x, y)

    # Wrap draws one y column, its panels in two rows.
    page.locator('.zone[data-role="row"] .chip-remove').click()
    page.locator('.zone[data-role="y"] .chip-remove').last.click()
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    place(page, "color", "wrap")
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    margins = y_margins(page)
    first, second = margins["rows"]
    for row in (first, second):
        for x, y in margin_points(margins, row):
            assert menu_at(page, x, y) == "Y 軸: y", (x, y)
    halfway = (margins["zone"] + first["left"]) / 2
    for y in [first["top"] - 2, (first["bottom"] + second["top"]) / 2, second["bottom"] + 2]:
        assert menu_at(page, halfway, y) is None, y
    # The right edge of the first panel is its plot area's, though the second
    # panel's y drag area may reach over it.
    right = page.evaluate(
        "(() => { const a = document.getElementById('plot')._fullLayout.xaxis;"
        " return document.getElementById('plot').getBoundingClientRect().left"
        " + a._offset + a._length; })()"
    )
    page.mouse.click(right - 1, first["between"], button="right")
    expect(page.locator(".plot-menu")).to_have_count(1)
    expect(page.locator(".axis-menu")).to_have_count(0)
    page.keyboard.press("Escape")
    assert errors == []


def test_the_margin_of_a_categorical_y_grays_out_its_log_item(app_page: Page) -> None:
    """A categorical y's margin opens its menu with the log item disabled."""
    page = app_page
    place(page, "x", "x")
    place(page, "color", "y")
    margins = y_margins(page)
    (row,) = margins["rows"]
    page.mouse.click(margins["zone"] + 1, (row["top"] + row["bottom"]) / 2, button="right")
    menu = page.locator(".axis-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text("Y 軸: color")
    expect(menu.get_by_role("button", name="対数表示")).to_be_disabled()
    expect(menu.get_by_role("button", name="向きを反転")).to_be_enabled()
    page.keyboard.press("Escape")
