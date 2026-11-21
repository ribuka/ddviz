"""E2E: Show null rows on the Color, Symbol, Group X, Group Y and Wrap zones, and the missing level in the legend and the panels."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, Route, expect

from ddviz.server.settings import PlotSettings, Settings
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


def test_show_null_rows_toggles_per_zone_and_the_missing_level_is_colored(  # noqa: PLR0915
    app_page: Page,
) -> None:
    """The zones' menu turns the null rows off and on, kept per zone across moves; the missing level is gray, apart from the "(null)" text, and takes a color."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="k")).to_be_visible()
    place(page, "x", "x")
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
    expect(page.locator(".zone-menu")).to_have_count(0)
    open_zone_menu(page, "color")
    item = page.locator('.zone-menu [data-item="null-rows"]')
    expect(item).to_have_text("Show null rows")
    expect(item).to_have_class("scale-menu-item checked")
    item.click()
    expect(page.locator(".zone-menu")).to_have_count(0)
    expect(items).to_have_count(3)
    page.wait_for_function(SETTLED)
    page.wait_for_function(f"() => !({HAS_COLOR})([128, 128, 128])")
    page.locator('.zone[data-role="color"] .chip').click(button="right")
    expect(item).to_have_class("scale-menu-item")
    page.keyboard.press("Escape")
    expect(page.locator(".zone-menu")).to_have_count(0)

    # Moved to Symbol alone, k draws its shapes by the Symbol's setting.
    page.locator('.zone[data-role="color"] .chip').drag_to(
        page.locator('.zone[data-role="symbol"]')
    )
    expect(items).to_have_count(4)
    open_zone_menu(page, "color")
    expect(page.locator(".zone-menu")).to_have_count(0)
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
    place(page, "x", "x")
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
    page.locator('.zone-menu [data-item="null-rows"]').click()
    expect(items).to_have_count(0)
    expect(legend.locator(".colorbar")).to_be_visible()


# The panels of the figure: one x axis each.
PANELS = r"""() => Object.keys(document.getElementById("plot").layout ?? {})
  .filter((key) => /^xaxis\d*$/.test(key)).length"""


def expect_panels(page: Page, n: int) -> None:
    """Wait until the figure has `n` panels and is settled."""
    page.wait_for_function(f"() => ({PANELS})() === {n}")
    page.wait_for_function(SETTLED)


def test_show_null_rows_of_the_facets_toggles_the_null_panel(app_page: Page) -> None:  # noqa: PLR0915
    """Group X and Group Y's menu and the Wrap form's checkbox draw the null rows as a last "(null)" panel and take it away, each zone keeping its setting across moves."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="k")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    # Without a column the zone has no menu.
    open_zone_menu(page, "col")
    expect(page.locator(".zone-menu")).to_have_count(0)
    place(page, "k", "col")
    page.wait_for_function(PAINTED_PIXEL)
    expect_panels(page, 4)
    labels = page.locator("#plot .annotation-text")
    expect(labels).to_have_text(
        ["k = (null)（文字列）", "k = a", "k = b", "k = (null)"]
    )

    # Group X's menu has Show null rows alone, checked; off, the panel goes.
    open_zone_menu(page, "col")
    item = page.locator('.zone-menu [data-item="null-rows"]')
    expect(item).to_have_text("Show null rows")
    expect(item).to_have_class("scale-menu-item checked")
    expect(page.locator('.zone-menu [data-item="keep-levels"]')).to_have_count(0)
    item.click()
    expect(page.locator(".zone-menu")).to_have_count(0)
    expect_panels(page, 3)
    # Without the missing panel, the "(null)" text is not marked.
    expect(labels).to_have_text(["k = (null)", "k = a", "k = b"])

    # Moved to Group Y, k draws its panel by Group Y's setting.
    page.locator('.zone[data-role="col"] .chip').drag_to(
        page.locator('.zone[data-role="row"]')
    )
    expect(page.locator('.zone[data-role="row"] .chip-name')).to_have_text("k")
    expect_panels(page, 4)
    expect(labels.last).to_have_text("k = (null)")
    open_zone_menu(page, "row")
    expect(item).to_have_class("scale-menu-item checked")
    item.click()
    expect_panels(page, 3)
    # Back on Group X, Group X's setting is still off.
    page.locator('.zone[data-role="row"] .chip').drag_to(
        page.locator('.zone[data-role="col"]')
    )
    expect(page.locator('.zone[data-role="col"] .chip-name')).to_have_text("k")
    open_zone_menu(page, "col")
    expect(item).to_have_class("scale-menu-item")
    item.click()
    expect_panels(page, 4)

    # On Wrap, the form's checkbox plots again at once and stays open.
    plots: list[str] = []
    page.on(
        "request",
        lambda r: plots.append(r.url) if r.url.endswith("/api/plot") else None,
    )
    page.locator('.zone[data-role="col"] .chip').drag_to(
        page.locator('.zone[data-role="wrap"]')
    )
    expect(page.locator('.zone[data-role="wrap"] .chip-name')).to_have_text("k")
    expect_panels(page, 4)
    expect(labels.last).to_have_text("(null)")
    wrap = page.locator('.zone[data-role="wrap"]')
    form = page.locator(".wrap-menu")
    box = form.get_by_role("checkbox", name="Show null rows")
    wrap.locator(".chip-name").click(button="right")
    expect(box).to_be_checked()
    count = len(plots)
    box.uncheck()
    expect_panels(page, 3)
    expect(labels).to_have_text(["(null)", "a", "b"])
    assert len(plots) == count + 1
    expect(form).to_be_visible()
    box.click()
    expect_panels(page, 4)
    expect(labels.last).to_have_text("(null)")
    expect(form).to_be_visible()
    box.uncheck()
    expect_panels(page, 3)
    page.keyboard.press("Escape")
    expect(form).to_have_count(0)
    # Reopened, the form shows the setting; Group X keeps its own.
    wrap.locator(".chip-name").click(button="right")
    expect(box).not_to_be_checked()
    page.keyboard.press("Escape")
    page.locator('.zone[data-role="wrap"] .chip').drag_to(
        page.locator('.zone[data-role="col"]')
    )
    expect(page.locator('.zone[data-role="col"] .chip-name')).to_have_text("k")
    expect_panels(page, 4)


@pytest.mark.parametrize("settings", [Settings(plot=PlotSettings(max_levels=3))])
def test_a_show_null_rows_whose_plot_fails_turns_back(app_page: Page) -> None:
    """Turned on past ``plot.max_levels`` (k's 3 levels and its nulls), the plot is refused and Color's, Group X's and Wrap's Show null rows turn back off, the drawn figure kept."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="k")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    item = page.locator('.zone-menu [data-item="null-rows"]')
    status = page.locator("#status")
    for role in ("color", "col"):
        # Off while the zone holds v, then k in its place: its 3 levels draw.
        place(page, "v", role)
        page.wait_for_function(SETTLED)
        open_zone_menu(page, role)
        item.click()
        page.wait_for_function(SETTLED)
        place(page, "k", role)
        expect(page.locator(f'.zone[data-role="{role}"] .chip-name')).to_have_text("k")
        page.wait_for_function(SETTLED)
        expect(status).not_to_have_class("notice-error")
        panels = page.evaluate(f"({PANELS})()")
        open_zone_menu(page, role)
        expect(item).to_have_class("scale-menu-item")
        item.click()
        expect(status).to_have_class("notice-error")
        close_toasts(page)
        open_zone_menu(page, role)
        expect(item).to_have_class("scale-menu-item")
        page.keyboard.press("Escape")
        expect(page.locator(f'.zone[data-role="{role}"] .chip-name')).to_have_text("k")
        assert page.evaluate(f"({PANELS})()") == panels
        page.locator(f'.zone[data-role="{role}"] .chip-remove').click()
        page.wait_for_function(SETTLED)

    wrap = page.locator('.zone[data-role="wrap"]')
    box = page.locator(".wrap-menu").get_by_role("checkbox", name="Show null rows")
    place(page, "v", "wrap")
    page.wait_for_function(SETTLED)
    wrap.locator(".chip-name").click(button="right")
    box.uncheck()
    page.wait_for_function(SETTLED)
    page.keyboard.press("Escape")
    place(page, "k", "wrap")
    expect(wrap.locator(".chip-name")).to_have_text("k")
    expect_panels(page, 3)
    wrap.locator(".chip-name").click(button="right")
    box.click()
    expect(status).to_have_class("notice-error")
    assert page.evaluate(f"({PANELS})()") == 3
    # The open form shows the setting turned back.
    expect(box).not_to_be_checked()
    page.keyboard.press("Escape")
    close_toasts(page)
    wrap.locator(".chip-name").click(button="right")
    expect(box).not_to_be_checked()


def close_toasts(page: Page) -> None:
    """Close the error's toasts, which may lie over the zones."""
    toasts = page.locator("#toasts .toast")
    for button in toasts.get_by_role("button", name="閉じる").all():
        button.click()
    expect(toasts).to_have_count(0)


def test_a_failed_show_null_rows_of_wrap_keeps_the_form_and_its_draft(
    app_page: Page,
) -> None:
    """When the images of the plot toggled in the Wrap form do not come, the setting turns back and the form stays open with the draft of the number."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="k")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "k", "wrap")
    expect_panels(page, 4)
    wrap = page.locator('.zone[data-role="wrap"]')
    form = page.locator(".wrap-menu")
    box = form.get_by_role("checkbox", name="Show null rows")
    manual = form.get_by_role("radio", name="指定")
    field = form.get_by_label("パネル数")
    wrap.locator(".chip-name").click(button="right")
    manual.check()
    field.fill("7")

    failed: list[str] = []

    def images(route: Route) -> None:
        if not failed:
            failed.append(route.request.url)
            route.fulfill(status=500, body="gone")
        else:
            route.continue_()

    page.route("**/api/images/*", images)
    box.click()
    expect(page.locator("#status")).to_contain_text("図の画像を読み込めなかった")
    expect(form).to_be_visible()
    expect(box).to_be_checked()
    expect(manual).to_be_checked()
    expect(field).to_have_value("7")
    # The drawn graph is plotted again, with the setting turned back.
    page.wait_for_function(f"() => ({PANELS})() === 4")
    page.wait_for_function(PAINTED_PIXEL)
    page.unroute("**/api/images/*")
    expect(form).to_be_visible()
    expect(field).to_have_value("7")
