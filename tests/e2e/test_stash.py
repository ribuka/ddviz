"""E2E: Stash in the right-click menu of the Color, Symbol, Group X, Group Y and Wrap zones (Issue #275)."""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Locator, Page, Route, expect

from tests.e2e.test_nulls import expect_panels
from tests.e2e.test_scatter import (
    PAINTED_PIXEL,
    SETTLED,
    apply_color_bins,
    place,
    watch_errors,
)

pytestmark = pytest.mark.e2e

ROWS = 400
CHECKED = re.compile(r"(^|\s)checked(\s|$)")
TITLE = "（Stash 中：描画では無いものとして扱う。右クリックの Stash で戻す）"


@pytest.fixture
def scatter_frame() -> pl.DataFrame:
    """Return rows with x, y, two categorical columns and a number with nulls."""
    rng = np.random.default_rng(0)
    return pl.DataFrame(
        {
            "x": rng.normal(0, 1, ROWS),
            "y": rng.normal(0, 1, ROWS),
            "k": rng.choice(["a", "b", "c"], ROWS).tolist(),
            "g": rng.choice(["p", "q"], ROWS).tolist(),
            "v": [None if i % 11 == 0 else float(i) for i in range(ROWS)],
        },
        schema_overrides={"v": pl.Float64},
    )


def chip(page: Page, role: str) -> Locator:
    """Return the chip of a role's zone."""
    return page.locator(f'.zone[data-role="{role}"] .chip')


def pick_stash(page: Page, role: str) -> dict[str, Any]:
    """Right-click the zone's chip, pick Stash, and return the body of the plot it asks for."""
    chip(page, role).click(button="right")
    menu = page.locator(".zone-menu, .wrap-menu")
    with page.expect_request("**/api/plot") as request:
        menu.locator('[data-item="stash"]').click()
    expect(menu).to_have_count(0)
    page.wait_for_function(SETTLED)
    return request.value.post_data_json


def expect_stash_item(page: Page, role: str, checked: bool) -> None:
    """Right-click the zone's chip: Stash is the menu's last item, under a separator, checked or not; Escape closes it."""
    chip(page, role).click(button="right")
    menu = page.locator(".zone-menu, .wrap-menu")
    last = menu.locator(".scale-menu-item").last
    expect(last).to_have_attribute("data-item", "stash")
    expect(last).to_have_text("Stash")
    expect(menu.locator(".scale-menu-separator + .scale-menu-item")).to_have_attribute("data-item", "stash")
    if checked:
        expect(last).to_have_class(CHECKED)
    else:
        expect(last).not_to_have_class(CHECKED)
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)


def test_a_stashed_color_is_drawn_without_and_comes_back_with_its_intervals(
    app_page: Page,
) -> None:
    """Stash on Color fades the chip, sends no color and takes the legend away; taken off, the 4 intervals come back."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "v", "color")
    page.wait_for_function(PAINTED_PIXEL)
    legend = page.locator("#legend")
    apply_color_bins(page, legend.locator(".colorbar"), "4")
    page.wait_for_function(SETTLED)
    items = legend.locator(".legend-item")
    expect(items).to_have_count(5)
    expect(items.last.locator(".legend-name")).to_have_text("(null)")

    # Without a column, the zone opens no menu.
    page.locator('.zone[data-role="symbol"]').click(button="right")
    expect(page.locator(".zone-menu")).to_have_count(0)
    chip(page, "color").click(button="right")
    menu = page.locator(".zone-menu")
    expect(menu.locator(".scale-menu-item")).to_have_text(["Show null rows", "Stash"])
    expect(menu.locator(".scale-menu-item").last).to_have_class("scale-menu-item")
    page.keyboard.press("Escape")

    body = pick_stash(page, "color")
    assert body["encoding"]["color"] is None
    expect(chip(page, "color")).to_have_class("chip stashed")
    expect(chip(page, "color")).to_have_attribute("title", f"v{TITLE}")
    expect(items).to_have_count(0)
    expect(legend.locator(".colorbar")).to_have_count(0)
    expect_stash_item(page, "color", checked=True)

    body = pick_stash(page, "color")
    assert body["encoding"]["color"] == "v"
    assert body["color_bins"]["n"] == 4
    expect(chip(page, "color")).to_have_class("chip")
    expect(items).to_have_count(5)
    expect(items.last.locator(".legend-name")).to_have_text("(null)")
    expect_stash_item(page, "color", checked=False)
    assert errors == []


def test_stash_on_the_facets_and_symbol(app_page: Page) -> None:
    """Group X, Group Y and Symbol stash their column and take it back; a column placed on a stashed zone is drawn."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "k", "col")
    page.wait_for_function(PAINTED_PIXEL)
    expect_panels(page, 3)
    labels = page.locator("#plot .annotation-text")

    chip(page, "col").click(button="right")
    menu = page.locator(".zone-menu")
    # Show null rows first, then a separator and Stash last (user decision on Issue #275).
    expect(menu.locator(".scale-menu-item")).to_have_text(["Show null rows", "Stash"])
    expect(menu.locator(".scale-menu-item").first).to_have_attribute("data-item", "null-rows")
    expect(menu.locator(".scale-menu-separator + .scale-menu-item")).to_have_attribute("data-item", "stash")
    page.keyboard.press("Escape")
    body = pick_stash(page, "col")
    assert body["encoding"]["col"] is None
    expect(chip(page, "col")).to_have_class("chip stashed")
    expect_panels(page, 1)
    expect(labels).to_have_count(0)
    # Another column placed on the stashed zone takes the stash off.
    place(page, "g", "col")
    expect(chip(page, "col")).to_have_class("chip")
    expect_panels(page, 2)
    expect(labels).to_have_text(["g = p", "g = q"])

    # Group Y.
    page.locator('.zone[data-role="col"] .chip-remove').click()
    place(page, "k", "row")
    expect_panels(page, 3)
    body = pick_stash(page, "row")
    assert body["encoding"]["row"] is None
    expect_panels(page, 1)
    expect(labels).to_have_count(0)
    expect_stash_item(page, "row", checked=True)
    body = pick_stash(page, "row")
    assert body["encoding"]["row"] == "k"
    expect_panels(page, 3)
    expect(labels).to_have_text(["k = a", "k = b", "k = c"])

    # Symbol.
    place(page, "g", "symbol")
    items = page.locator("#legend .legend-item")
    expect(items).to_have_count(2)
    body = pick_stash(page, "symbol")
    assert body["encoding"]["symbol"] is None
    expect(chip(page, "symbol")).to_have_class("chip stashed")
    expect(items).to_have_count(0)
    body = pick_stash(page, "symbol")
    assert body["encoding"]["symbol"] == "g"
    expect(items).to_have_count(2)
    assert errors == []


def test_stash_in_the_wrap_form_keeps_the_number_to_a_row(app_page: Page) -> None:
    """The Wrap form's Stash takes the wrapped panels away and keeps the number set; Enter on it takes the stash off, not apply."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "k", "wrap")
    page.wait_for_function(PAINTED_PIXEL)
    expect_panels(page, 3)
    labels = page.locator("#plot .annotation-text")
    form = page.locator(".wrap-menu")
    chip(page, "wrap").click(button="right")
    # Stash is the form's last item, under a separator, below the apply button.
    expect(form.locator(".scale-menu-item").last).to_have_text("Stash")
    expect(form.locator(".wrap-menu-separator + .wrap-menu-stash")).to_have_count(1)
    form.get_by_label("指定").check()
    page.locator("#wrap-cols-input").fill("1")
    with page.expect_request("**/api/plot") as request:
        form.get_by_role("button", name="適用").click()
    assert request.value.post_data_json["wrap_cols"] == 1
    page.wait_for_function(SETTLED)

    body = pick_stash(page, "wrap")
    assert body["encoding"]["wrap"] is None
    expect(chip(page, "wrap")).to_have_class("chip stashed")
    expect_panels(page, 1)
    expect(labels).to_have_count(0)

    chip(page, "wrap").click(button="right")
    stash = form.locator('[data-item="stash"]')
    expect(stash).to_have_class(CHECKED)
    expect(page.locator("#wrap-cols-input")).to_have_value("1")
    stash.focus()
    with page.expect_request("**/api/plot") as request:
        page.keyboard.press("Enter")
    body = request.value.post_data_json
    assert body["encoding"]["wrap"] == "k"
    assert body["wrap_cols"] == 1
    expect(form).to_have_count(0)
    expect(chip(page, "wrap")).to_have_class("chip")
    expect_panels(page, 3)
    expect(labels).to_have_text(["a", "b", "c"])
    assert errors == []


def test_a_number_applied_while_stashed_survives_a_failed_plot(app_page: Page) -> None:
    """A number to a row applied while Wrap is stashed stays after the plot taking the stash off fails."""
    page = app_page
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "k", "wrap")
    page.wait_for_function(PAINTED_PIXEL)
    pick_stash(page, "wrap")
    expect_panels(page, 1)

    # Applied while stashed: saved, not plotted.
    form = page.locator(".wrap-menu")
    chip(page, "wrap").click(button="right")
    form.get_by_label("指定").check()
    page.locator("#wrap-cols-input").fill("1")
    form.get_by_role("button", name="適用").click()
    expect(form).to_have_count(0)

    failed: list[str] = []

    def fail_once(route: Route) -> None:
        if not failed:
            failed.append(route.request.url)
            route.fulfill(status=500, body="gone")
        else:
            route.continue_()

    page.route("**/api/plot", fail_once)
    chip(page, "wrap").click(button="right")
    form.locator('[data-item="stash"]').click()
    expect(page.locator("#status")).to_contain_text("gone")
    assert failed
    expect(chip(page, "wrap")).to_have_class("chip stashed")
    page.unroute("**/api/plot")

    chip(page, "wrap").click(button="right")
    expect(form.get_by_label("指定")).to_be_checked()
    expect(page.locator("#wrap-cols-input")).to_have_value("1")
    with page.expect_request("**/api/plot") as request:
        form.locator('[data-item="stash"]').click()
    body = request.value.post_data_json
    assert body["encoding"]["wrap"] == "k"
    assert body["wrap_cols"] == 1
    page.wait_for_function(SETTLED)
    expect_panels(page, 3)
