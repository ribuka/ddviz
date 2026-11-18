"""E2E: the Symbol zone's setting that keeps the levels of every row, the local filter aside (Issue #282)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_color_levels import (
    KEEP,
    NULL_ROWS,
    add_filter,
    scatter_path,  # noqa: F401 - the data of these tests
    tick,
    toasts_let_drops_through,  # noqa: F401 - autouse
    zoom,
)
from tests.e2e.test_plot_failure import LAYOUT, X_RANGE, move
from tests.e2e.test_scatter import SETTLED, place, wait_idle, watch_errors

pytestmark = pytest.mark.e2e

# The names of the symbol legend's items (those with a shape).
SHAPE_NAMES = "#legend .legend-item:has(.swatch.shape) .legend-name"
SHAPE_ITEMS = "#legend .legend-item:has(.swatch.shape)"


def open_symbol_menu(page: Page) -> None:
    """Right-click the Symbol zone's chip."""
    page.locator('.zone[data-role="symbol"] .chip').click(button="right")
    expect(page.locator(".zone-menu")).to_be_visible()


def test_kept_symbol_levels_stay_in_the_legend_without_rows(app_page: Page) -> None:
    """On, the 30 shapes stay with the 28 the filter leaves out marked without rows; off again, they go; a numeric symbol has no item."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "s", "symbol")
    expect(page.locator(SHAPE_NAMES)).to_have_count(30)
    # g1 and g2 have s1 and s2 alone.
    add_filter(page, "g")
    tick(page, "g", ["g1", "g2"])
    expect(page.locator(SHAPE_NAMES)).to_have_text(["s1", "s2"])

    open_symbol_menu(page)
    expect(page.locator(KEEP)).to_have_text("フィルタで除外された水準も凡例に残す")
    expect(page.locator(KEEP)).to_have_class("scale-menu-item")
    with page.expect_response("**/api/plot") as plotted:
        page.locator(KEEP).click()
    assert plotted.value.ok
    assert plotted.value.request.post_data_json["keep_unfiltered_symbol_levels"] is True
    assert plotted.value.request.post_data_json["keep_unfiltered_color_levels"] is False
    page.wait_for_function(SETTLED)
    expect(page.locator(SHAPE_NAMES)).to_have_text([f"s{i}" for i in range(1, 31)])
    expect(page.locator(SHAPE_ITEMS).filter(has_text="（行なし）")).to_have_count(28)
    open_symbol_menu(page)
    expect(page.locator(KEEP)).to_have_class("scale-menu-item checked")

    # Off again: the shapes without rows go.
    with page.expect_response("**/api/plot") as plotted:
        page.locator(KEEP).click()
    assert plotted.value.ok
    page.wait_for_function(SETTLED)
    expect(page.locator(SHAPE_NAMES)).to_have_text(["s1", "s2"])
    expect(page.locator(SHAPE_ITEMS).filter(has_text="（行なし）")).to_have_count(0)

    # A numeric column on Symbol, cut into intervals: no item.
    move(page, "symbol", "#columns")
    wait_idle(page)
    place(page, "v", "symbol")
    open_symbol_menu(page)
    expect(page.locator(NULL_ROWS)).to_be_visible()
    expect(page.locator(KEEP)).to_have_count(0)
    page.keyboard.press("Escape")
    assert errors == []


def test_kept_symbol_levels_past_the_limit_turn_back(app_page: Page) -> None:
    """On, the 150 levels of every row pass the limit: refused, the check turns back, the figure, the legend and the axis range stay."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    add_filter(page, "g")
    tick(page, "g", [f"g{i}" for i in range(1, 11)])
    place(page, "g", "symbol")
    expect(page.locator(SHAPE_NAMES)).to_have_text([f"g{i}" for i in range(1, 11)])

    zoom(page, 100, 2000)
    shown = page.evaluate(X_RANGE)
    layout = page.evaluate(LAYOUT)
    open_symbol_menu(page)
    with page.expect_response("**/api/plot") as refused:
        page.locator(KEEP).click()
    assert refused.value.status >= 400
    expect(page.locator("#status")).to_contain_text("g は 150 個で")
    expect(page.locator("#status")).to_contain_text(
        "「フィルタで除外された水準も凡例に残す」を外す"
    )
    wait_idle(page)
    open_symbol_menu(page)
    expect(page.locator(KEEP)).to_have_class("scale-menu-item")
    page.keyboard.press("Escape")
    expect(page.locator(SHAPE_NAMES)).to_have_text([f"g{i}" for i in range(1, 11)])
    assert page.evaluate(X_RANGE) == pytest.approx(shown)
    assert page.evaluate(LAYOUT) == layout
    assert errors == []
