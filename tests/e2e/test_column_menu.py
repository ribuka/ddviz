"""E2E: the menu of a listed column places it on the filter pane or a role (Issue #162)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_plot_failure import failing
from tests.e2e.test_scatter import SETTLED, placed_names, watch_errors

pytestmark = pytest.mark.e2e

ITEMS = [
    "Add to Local filter",
    "Add to Xaxis (Overwrite)",
    "Add to Xaxis (Append)",
    "Add to Yaxis (Overwrite)",
    "Add to Yaxis (Append)",
    "Add to Symbol",
    "Add to Color",
    "Add to GroupX",
    "Add to GroupY",
    "Add to Wrap",
]


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write four numeric columns and three categorical ones of few levels."""
    rng = np.random.default_rng(0)
    n = 600
    frame = pl.DataFrame(
        {
            **{f"p{i}": rng.normal(0, 1, n) for i in range(1, 5)},
            "kind": rng.choice(["a", "b", "c"], n),
            "site": rng.choice(["s", "t"], n),
            "grp": rng.choice(["g", "h"], n),
        }
    )
    path = tmp_path / "menu.parquet"
    frame.write_parquet(path)
    return path


def open_menu(page: Page, column: str, at: float = 20) -> Locator:
    """Right-click a listed column's row `at` pixels from its left and return its menu.

    The menu opens at the pointer: rows below it stay in reach left of it.
    """
    row = page.locator("#columns .column").filter(has=page.get_by_text(column, exact=True))
    box = row.bounding_box()
    assert box is not None
    row.click(button="right", position={"x": at, "y": box["height"] / 2})
    menu = page.locator(".column-menu")
    expect(menu).to_be_visible()
    return menu


def item(page: Page, text: str) -> Locator:
    """Return an item of the open column menu by its text."""
    return page.locator(".column-menu .scale-menu-item").filter(has_text=text)


def pick(page: Page, column: str, text: str, *, plots: bool = False) -> None:
    """Open a column's menu and pick an item; with `plots`, wait for the graph it draws."""
    open_menu(page, column)
    if plots:
        with page.expect_response("**/api/plot"):
            item(page, text).click()
        page.wait_for_function(SETTLED)
    else:
        item(page, text).click()
    expect(page.locator(".column-menu")).to_have_count(0)


def expect_refused(page: Page, column: str, text: str, reason: str) -> None:
    """Expect an item of a column's menu disabled with `reason` as its tip, then close the menu."""
    open_menu(page, column)
    row = item(page, text)
    expect(row).to_be_disabled()
    expect(row).to_have_attribute("title", reason)
    page.keyboard.press("Escape")
    expect(page.locator(".column-menu")).to_have_count(0)


def test_the_menu_opens_in_order_moves_and_closes(app_page: Page) -> None:
    """Ten items in order; another row moves the menu, a click outside, Escape, a search and an item close it."""
    page = app_page
    errors = watch_errors(page)
    rows = page.locator("#columns .column")
    expect(rows.filter(has_text="grp")).to_be_visible()

    menu = open_menu(page, "p1")
    expect(menu.locator(".scale-menu-item")).to_have_text(ITEMS)
    # Another row moves the menu to its column: one menu, for p2.
    open_menu(page, "p2", at=6)
    expect(page.locator(".column-menu")).to_have_count(1)
    item(page, "Add to Local filter").click()
    expect(page.locator("#filters .filter-card")).to_have_count(1)
    expect(page.locator("#filters .filter-card")).to_contain_text("p2")
    expect(menu).to_have_count(0)

    open_menu(page, "p1")
    page.locator(".column-count").click()
    expect(page.locator(".column-menu")).to_have_count(0)
    open_menu(page, "p1")
    page.keyboard.press("Escape")
    expect(page.locator(".column-menu")).to_have_count(0)
    # The heading and the space of the list are not rows: no menu.
    page.locator(".column-count").click(button="right")
    expect(page.locator(".column-menu")).to_have_count(0)

    # A search that no longer lists the column closes its menu; one that
    # still lists it keeps it open.
    search = page.locator(".column-search")
    open_menu(page, "kind")
    search.fill("k")
    expect(rows).to_have_count(1)
    expect(page.locator(".column-menu")).to_have_count(1)
    search.fill("p")
    expect(rows).to_have_count(5)
    expect(page.locator(".column-menu")).to_have_count(0)

    # A placement keeps the keyword in the history, as a drop does.
    search.fill("p3")
    expect(rows).to_have_count(1)
    pick(page, "p3", "Add to Xaxis (Append)")
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text(["p3"])
    search.fill("")
    search.blur()
    search.focus()
    expect(page.locator(".search-history-word")).to_have_text(["p3"])
    assert errors == []


# A window shorter than the menu of ten items.
HEIGHT = 200
WIDTH = 700


def test_the_menu_fits_a_small_window(app_page: Page) -> None:
    """In a window shorter than the menu, it stays inside and scrolls to its last item."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="grp")).to_be_visible()
    page.set_viewport_size({"width": WIDTH, "height": HEIGHT})
    # A right click at the window's bottom right corner (the rows there are
    # under the status bar in so small a window): the menu moves left and up.
    row = page.locator("#columns .column").filter(has=page.get_by_text("p1", exact=True))
    row.dispatch_event("contextmenu", {"clientX": WIDTH - 2, "clientY": HEIGHT - 2, "button": 2})
    menu = page.locator(".column-menu")
    expect(menu).to_be_visible()
    rect = menu.bounding_box()
    assert rect is not None
    assert rect["y"] >= 0
    assert rect["y"] + rect["height"] <= HEIGHT
    assert rect["x"] + rect["width"] <= WIDTH
    assert menu.evaluate("(m) => m.scrollHeight > m.clientHeight")
    item(page, "Add to Wrap").click()
    expect(page.locator('.zone[data-role="wrap"] .chip-name')).to_have_text(["p1"])


def test_local_filter_opens_the_pane_and_refuses_a_second_card(app_page: Page) -> None:
    """A folded pane opens to show the card; a column with a card cannot add another."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="grp")).to_be_visible()
    page.locator("#filters .filter-down").click()
    expect(page.locator("#filters.collapsed")).to_have_count(1)
    pick(page, "kind", "Add to Local filter")
    expect(page.locator("#filters .filter-card")).to_have_count(1)
    expect(page.locator("#filters.collapsed")).to_have_count(0)
    expect_refused(page, "kind", "Add to Local filter", "既に配置済み")
    open_menu(page, "kind")
    item(page, "Add to Local filter").click(force=True)
    page.keyboard.press("Escape")
    expect(page.locator("#filters .filter-card")).to_have_count(1)
    # A column with a card can still go on a role.
    pick(page, "kind", "Add to Color")
    expect(page.locator('.zone[data-role="color"] .chip-name')).to_have_text(["kind"])


@pytest.mark.parametrize(("role", "axis"), [("x", "Xaxis"), ("y", "Yaxis")])
def test_overwrite_and_append_on_an_axis(app_page: Page, role: str, axis: str) -> None:
    """Append on an empty axis, Overwrite of the one axis, Append after it, and Overwrite of an axis picked."""
    page = app_page
    errors = watch_errors(page)
    chips = page.locator(f'.zone[data-role="{role}"] .chip-name')
    overwrite = f"Add to {axis} (Overwrite)"
    append = f"Add to {axis} (Append)"
    expect(page.locator("#columns .column").filter(has_text="grp")).to_be_visible()

    expect_refused(page, "p1", overwrite, "置き換える軸がない")
    # Y alone draws a graph (X does not): each one is waited for.
    plots = role == "y"
    pick(page, "p1", append, plots=plots)
    expect(chips).to_have_text(["p1"])
    # One axis: Overwrite replaces it at once, without a submenu.
    open_menu(page, "p2")
    expect(item(page, overwrite)).not_to_have_class("has-sub")
    page.keyboard.press("Escape")
    pick(page, "p2", overwrite, plots=plots)
    expect(chips).to_have_text(["p2"])
    pick(page, "p3", append, plots=plots)
    pick(page, "kind", append)
    expect(chips).to_have_text(["p2", "p3", "kind"])

    # Several axes: Overwrite opens them in their order; the one picked is
    # replaced in its place.
    open_menu(page, "p4")
    item(page, overwrite).hover()
    submenu = page.locator(".column-submenu .scale-menu-item")
    expect(submenu).to_have_text(["1. p2", "2. p3", "3. kind"])
    # Another item closes the submenu; Overwrite opens it again.
    item(page, "Add to Color").hover()
    expect(submenu).to_have_count(0)
    item(page, overwrite).hover()
    submenu.filter(has_text="2. p3").click()
    expect(page.locator(".column-menu, .column-submenu")).to_have_count(0)
    expect(chips).to_have_text(["p2", "p4", "kind"])

    # A column on the axis cannot go on it again, by either item; it can go
    # on the other axis and on another role.
    expect_refused(page, "p4", overwrite, "既に配置済み")
    expect_refused(page, "p4", append, "既に配置済み")
    other = "Yaxis" if axis == "Xaxis" else "Xaxis"
    pick(page, "p4", f"Add to {other} (Append)", plots=True)
    pick(page, "p4", "Add to Color", plots=True)
    names = placed_names(page)
    assert names[role] == ["p2", "p4", "kind"]
    assert names["y" if role == "x" else "x"] == ["p4"]
    assert names["color"] == ["p4"]
    page.wait_for_function(SETTLED)
    assert errors == []


def test_single_roles_replace_and_wrap_excludes_facets_and_axes(app_page: Page) -> None:
    """Single roles are replaced at once; Wrap and the facets remove each other; Wrap and an n-th axis refuse each other."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="grp")).to_be_visible()
    pick(page, "p1", "Add to Xaxis (Append)")
    pick(page, "p2", "Add to Yaxis (Append)", plots=True)
    pick(page, "kind", "Add to Symbol", plots=True)
    pick(page, "site", "Add to Symbol", plots=True)
    pick(page, "kind", "Add to Color", plots=True)
    expect_refused(page, "kind", "Add to Color", "既に配置済み")
    pick(page, "site", "Add to GroupX", plots=True)
    pick(page, "grp", "Add to GroupY", plots=True)
    names = placed_names(page)
    assert (names["symbol"], names["color"], names["col"], names["row"]) == (["site"], ["kind"], ["site"], ["grp"])

    # Wrap removes the facets.
    pick(page, "grp", "Add to Wrap", plots=True)
    names = placed_names(page)
    assert (names["col"], names["row"], names["wrap"]) == ([], [], ["grp"])
    # With Wrap, Append beside an axis is refused; Overwrite still replaces.
    expect_refused(page, "p3", "Add to Xaxis (Append)", "Wrap が配置されている")
    expect_refused(page, "p3", "Add to Yaxis (Append)", "Wrap が配置されている")
    open_menu(page, "p3")
    item(page, "Add to Yaxis (Append)").click(force=True)
    page.keyboard.press("Escape")
    assert placed_names(page)["y"] == ["p2"]
    pick(page, "p3", "Add to Xaxis (Overwrite)", plots=True)
    assert placed_names(page)["x"] == ["p3"]

    # A facet removes Wrap; then an n-th axis refuses Wrap.
    pick(page, "site", "Add to GroupY", plots=True)
    names = placed_names(page)
    assert (names["row"], names["wrap"]) == (["site"], [])
    pick(page, "p4", "Add to Yaxis (Append)", plots=True)
    assert placed_names(page)["y"] == ["p2", "p4"]
    expect_refused(page, "grp", "Add to Wrap", "第2軸以降がある")
    expect_refused(page, "site", "Add to Wrap", "第2軸以降がある")
    page.wait_for_function(SETTLED)
    assert errors == []


def test_a_failed_plot_takes_back_a_placement(app_page: Page) -> None:
    """A placement whose plot fails comes back to the drawn graph, as a drop does."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="grp")).to_be_visible()
    pick(page, "p1", "Add to Xaxis (Append)")
    pick(page, "p2", "Add to Yaxis (Append)", plots=True)
    pick(page, "site", "Add to GroupX", plots=True)
    expect(page.locator('.zone[data-role="col"] .chip-name')).to_have_text(["site"])
    page.wait_for_function(SETTLED)
    status = page.locator("#status")
    before = placed_names(page)

    count = failing(page)
    picks = [
        ("p3", "Add to Xaxis (Append)"),
        ("p3", "Add to Yaxis (Overwrite)"),
        ("kind", "Add to Color"),
        ("grp", "Add to Wrap"),  # Wrap removes Group X
        ("grp", "Add to GroupX"),
    ]
    for i, (column, text) in enumerate(picks, 1):
        pick(page, column, text)
        expect(status).to_have_text(f"エラー: 集約に失敗した {i}")
        assert placed_names(page) == before, i
    assert len(count) == len(picks)

    # A plot that succeeds commits the placement.
    page.unroute("**/api/plot")
    pick(page, "kind", "Add to Color", plots=True)
    page.wait_for_function(SETTLED)
    expect(status).not_to_have_class("notice-error")
    assert placed_names(page) == {**before, "color": ["kind"]}
