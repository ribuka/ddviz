"""E2E: Show null rows on the Color and Symbol zones, and the missing level in the legend."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import HAS_COLOR, PAINTED_PIXEL, SETTLED, place

pytestmark = pytest.mark.e2e

ROWS = 400
GRAY = "rgb(128, 128, 128)"


@pytest.fixture
def scatter_frame() -> pl.DataFrame:
    """Return rows whose k is a text, a "(null)" text or null, and whose v is a number, null or NaN."""
    rng = np.random.default_rng(0)
    k = rng.choice(["a", "b", "(null)", "?"], ROWS).tolist()
    v = rng.normal(0, 1, ROWS)
    v[::7] = np.nan
    return pl.DataFrame(
        {
            "x": rng.normal(0, 1, ROWS),
            "y": rng.normal(0, 1, ROWS),
            "k": [None if s == "?" else s for s in k],
            "v": [None if i % 11 == 0 else float(x) for i, x in enumerate(v)],
        },
        schema_overrides={"v": pl.Float64},
    )


def open_zone_menu(page: Page, role: str) -> None:
    """Right-click a zone: its label while empty, its chip once filled (which hides the label)."""
    page.locator(f'.zone[data-role="{role}"]').click(button="right")


def test_show_null_rows_toggles_per_zone_and_the_missing_level_is_colored(
    app_page: Page,
) -> None:
    """The zones' menu turns the null rows off and on, kept per zone across moves; the missing level is gray, apart from the "(null)" text, and takes a color."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="k")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "k", "color")
    page.wait_for_function(PAINTED_PIXEL)
    items = page.locator("#legend .legend-item")
    expect(items.locator(".legend-name")).to_have_text(
        ["(null)（文字列）", "a", "b", "(null)"]
    )
    expect(items.last.locator(".swatch")).to_have_css("background-color", GRAY)
    page.wait_for_function(HAS_COLOR, arg=[128, 128, 128])

    # Without a column the zone has no menu.
    open_zone_menu(page, "symbol")
    expect(page.locator(".null-menu")).to_have_count(0)
    open_zone_menu(page, "color")
    item = page.locator(".null-menu .scale-menu-item")
    expect(item).to_have_text("Show null rows")
    expect(item).to_have_class("scale-menu-item checked")
    item.click()
    expect(page.locator(".null-menu")).to_have_count(0)
    expect(items).to_have_count(3)
    page.wait_for_function(SETTLED)
    page.wait_for_function(f"() => !({HAS_COLOR})([128, 128, 128])")
    page.locator('.zone[data-role="color"] .chip').click(button="right")
    expect(item).to_have_class("scale-menu-item")
    page.keyboard.press("Escape")
    expect(page.locator(".null-menu")).to_have_count(0)

    # Moved to Symbol alone, k draws its shapes by the Symbol's setting.
    page.locator('.zone[data-role="color"] .chip').drag_to(
        page.locator('.zone[data-role="symbol"]')
    )
    expect(items).to_have_count(4)
    open_zone_menu(page, "color")
    expect(page.locator(".null-menu")).to_have_count(0)
    open_zone_menu(page, "symbol")
    expect(item).to_have_class("scale-menu-item checked")
    page.keyboard.press("Escape")
    # Back on Color, the Color's setting is still off.
    page.locator('.zone[data-role="symbol"] .chip').drag_to(
        page.locator('.zone[data-role="color"]')
    )
    expect(page.locator('.zone[data-role="color"] .chip-name')).to_have_text("k")
    expect(items).to_have_count(3)
    open_zone_menu(page, "color")
    item.click()
    expect(items).to_have_count(4)
    page.wait_for_function(SETTLED)

    # The missing level toggles, and takes a color and back its gray.
    items.last.click()
    expect(items.last).to_have_class("legend-item inactive")
    items.last.click()
    items.last.locator(".legend-marker").click(button="right")
    menu = page.locator(".shape-menu")
    menu.get_by_text("色", exact=True).hover()
    panel = page.locator(".color-panel")
    expect(panel.locator(".color-hex-input")).to_have_value("#808080")
    panel.locator('.color-cell[title="#000000"]').click()
    expect(items.last.locator(".swatch")).to_have_css(
        "background-color", "rgb(0, 0, 0)"
    )
    page.wait_for_function(HAS_COLOR, arg=[0, 0, 0])
    items.last.locator(".legend-marker").click(button="right")
    menu.get_by_text("色", exact=True).hover()
    panel.get_by_text("既定の色に戻す").click()
    expect(items.last.locator(".swatch")).to_have_css("background-color", GRAY)


def test_a_gradient_has_its_missing_level_under_the_bar(app_page: Page) -> None:
    """A numeric color keeps its bar; its null and NaN rows are a gray item under it, toggled and colored on their own."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="v")).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    place(page, "v", "color")
    page.wait_for_function(PAINTED_PIXEL)
    legend = page.locator("#legend")
    expect(legend.locator(".colorbar")).to_be_visible()
    items = legend.locator(".legend-item")
    expect(items.locator(".legend-name")).to_have_text(["(null)"])
    expect(items.locator(".swatch")).to_have_css("background-color", GRAY)
    page.wait_for_function(HAS_COLOR, arg=[128, 128, 128])
    # Isolated, the missing level leaves the bar's level inactive.
    items.first.click(button="right")
    expect(legend.locator(".colorbar")).to_have_class("colorbar inactive")
    items.first.click(button="right")
    expect(legend.locator(".colorbar")).to_have_class("colorbar")
    items.first.locator(".legend-marker").click(button="right")
    page.locator(".shape-menu").get_by_text("色", exact=True).hover()
    page.locator('.color-panel .color-cell[title="#000000"]').click()
    page.wait_for_function(HAS_COLOR, arg=[0, 0, 0])
    # Off, the gradient has its bar alone.
    open_zone_menu(page, "color")
    page.locator(".null-menu .scale-menu-item").click()
    expect(items).to_have_count(0)
    expect(legend.locator(".colorbar")).to_be_visible()
