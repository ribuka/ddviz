"""E2E: the axis menu's "フィルタで除外された水準も軸に残す" keeps the bands of every row of a categorical axis through the local filter (Issue #281)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Locator, Page, Route, expect

from ddviz.server.settings import PlotSettings, Settings
from tests.e2e.test_axis_menu import _right_click_tick
from tests.e2e.test_color_levels import add_filter, box, tick
from tests.e2e.test_kept_ranges import settle, shown, zoom
from tests.e2e.test_nulls import close_toasts
from tests.e2e.test_scatter import place, wait_idle, watch_errors

pytestmark = pytest.mark.e2e

ROWS = 600
TICKS = "() => document.getElementById('plot')._fullLayout.xaxis.ticktext"
ITEM = "フィルタで除外された水準も軸に残す"
EVERY = [f"g{i}" for i in range(6)]


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Serve g cycling over g0 to g5 and c over a, b, c: the rows of a have g0 and g3, those of b g1 and g4."""
    path = tmp_path / "bands.parquet"
    pl.DataFrame(
        {
            "g": [f"g{i % 6}" for i in range(ROWS)],
            "c": [["a", "b", "c"][i % 3] for i in range(ROWS)],
            "y": [float(i) for i in range(ROWS)],
            "v": [float(i % 7) for i in range(ROWS)],
        }
    ).write_parquet(path)
    return path


def item_of_x(page: Page) -> Locator:
    """Open the menu of x's tick labels and return its item."""
    _right_click_tick(page, "x")
    item = page.locator(".axis-menu").get_by_role("button", name=ITEM)
    expect(item).to_be_visible()
    return item


def toggle(page: Page) -> None:
    """Pick the item of x's menu and wait for the plot it asks for."""
    with page.expect_response("**/api/plot"):
        item_of_x(page).click()
    settle(page)


def test_the_item_keeps_the_bands_of_every_row(app_page: Page) -> None:
    """On, a filter to c = a keeps the 6 bands; changed to c = b, the bands and a zoom by hand stay; off, the bands are those of the filter again."""
    page = app_page
    errors = watch_errors(page)
    place(page, "g", "x")
    place(page, "y", "y")
    settle(page)
    item = item_of_x(page)
    expect(item).to_be_enabled()
    expect(item).to_have_class("scale-menu-item")
    page.keyboard.press("Escape")

    add_filter(page, "c")
    tick(page, "c", ["a"])
    settle(page)
    assert page.evaluate(TICKS) == ["g0", "g3"]

    toggle(page)
    assert page.evaluate(TICKS) == EVERY
    assert shown(page, "xaxis") == pytest.approx([-0.5, 5.5])
    expect(item_of_x(page)).to_have_class("scale-menu-item checked")
    page.keyboard.press("Escape")

    zoom(page, {"xaxis.range": [1.5, 3.5]})
    tick(page, "c", ["b"], "**/api/view")
    with page.expect_response("**/api/view") as answered:
        box(page, "c", "a").uncheck()
    settle(page)
    assert answered.value.json()["meta"]["axis_levels"] == {"g": EVERY}
    # The bands within the zoom.
    assert page.evaluate(TICKS) == ["g2", "g3"]
    assert shown(page, "xaxis") == pytest.approx([1.5, 3.5])

    # Off: the bands of the rows of b, over their automatic range.
    toggle(page)
    assert page.evaluate(TICKS) == ["g1", "g4"]
    assert shown(page, "xaxis") == pytest.approx([-0.5, 1.5])
    expect(item_of_x(page)).to_have_class("scale-menu-item")
    assert errors == []


def test_the_item_of_a_numeric_axis_is_grayed_out(app_page: Page) -> None:
    """A numeric x shows the item disabled."""
    page = app_page
    place(page, "v", "x")
    place(page, "y", "y")
    settle(page)
    expect(item_of_x(page)).to_be_disabled()


@pytest.mark.parametrize(
    "settings", [Settings(plot=PlotSettings(max_axis_levels=4))]
)
def test_a_refused_item_turns_back(app_page: Page) -> None:
    """Under ``plot.max_axis_levels`` of 4, turning the item on for the 6 levels of every row is refused: it turns back off and the figure stays."""
    page = app_page
    place(page, "y", "y")
    settle(page)
    add_filter(page, "c")
    tick(page, "c", ["a"])
    place(page, "g", "x")
    settle(page)
    assert page.evaluate(TICKS) == ["g0", "g3"]
    with page.expect_response("**/api/plot") as refused:
        item_of_x(page).click()
    assert not refused.value.ok
    assert "「フィルタで除外された水準も軸に残す」を外す" in refused.value.text()
    settle(page)
    expect(page.locator("#status")).to_have_class("notice-error")
    close_toasts(page)
    assert page.evaluate(TICKS) == ["g0", "g3"]
    assert shown(page, "xaxis") == pytest.approx([-0.5, 1.5])
    expect(item_of_x(page)).to_have_class("scale-menu-item")


def test_a_lost_answer_restores_the_graph_with_the_item_off(app_page: Page) -> None:
    """When the answer of the plot that turns the item on is lost after the server drew it, the plot that restores the drawn graph asks for the item off: the bands of the filter, unchecked."""
    page = app_page
    place(page, "g", "x")
    place(page, "y", "y")
    settle(page)
    add_filter(page, "c")
    tick(page, "c", ["a"])
    settle(page)
    kept: list[object] = []
    lost: list[int] = []

    def lose(route: Route) -> None:
        kept.append(route.request.post_data_json["keep_unfiltered_axis_levels"])
        if lost:
            route.continue_()
            return
        lost.append(1)
        route.fetch()
        route.abort()

    page.route("**/api/plot", lose)
    with page.expect_response(
        lambda r: r.url.endswith("/api/plot")
        and r.request.post_data_json["keep_unfiltered_axis_levels"] == []
    ) as restored:
        item_of_x(page).click()
    assert restored.value.ok
    # The error stays shown: the status is not that of a result.
    page.wait_for_timeout(300)
    wait_idle(page)
    page.unroute("**/api/plot")
    assert kept == [["g"], []]
    expect(page.locator("#status")).to_have_class("notice-error")
    close_toasts(page)
    assert page.evaluate(TICKS) == ["g0", "g3"]
    expect(item_of_x(page)).to_have_class("scale-menu-item")
