"""E2E: the menu of an axis's tick labels puts its column on a log axis and back."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import SETTLED, place, watch_errors

pytestmark = pytest.mark.e2e

FULL = "document.getElementById('plot')._fullLayout"


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
    place(page, "x", "x", plots=False)
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
    place(page, "color", "x", plots=False)
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
