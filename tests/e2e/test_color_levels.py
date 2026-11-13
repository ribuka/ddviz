"""E2E: the color levels of the local filter, the setting that keeps those of every row, and the filter pane going back when they pass the limit (Issue #124)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Locator, Page, Route, expect

from ddviz.shared.palette import DEFAULT_COLORS
from tests.e2e.test_column_menu import pick
from tests.e2e.test_line_element import at
from tests.e2e.test_plot_failure import LAYOUT, X_RANGE, move
from tests.e2e.test_scatter import (
    HAS_COLOR,
    SETTLED,
    place,
    wait_idle,
    watch_errors,
)

pytestmark = pytest.mark.e2e

ROWS = 3000
KEEP = '.zone-menu [data-item="keep-levels"]'
NULL_ROWS = '.zone-menu [data-item="null-rows"]'
LEGEND_NAMES = "#legend .legend-item .legend-name"
# The background of each color item's swatch.
SWATCHES = """() => [...document.querySelectorAll('#legend .legend-item .swatch')].map(
  (s) => getComputedStyle(s).backgroundColor)"""
REFUSED = (
    "エラー: Color の水準がフィルタの後も上限の 100 個を超えるため描けない（g）。"
    "フィルタで水準を絞るか、別の列を使う"
)


def rgb(hex_color: str) -> str:
    """Return a color as CSS computes it."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgb({r}, {g}, {b})"


PALETTE = [rgb(c) for c in DEFAULT_COLORS]


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write x and y, g of 150 levels (g1 to g150), half (lo for g1 to g80, hi for the others), s of 30 levels and a numeric v."""
    rng = np.random.default_rng(0)
    place_ = np.arange(ROWS) % 150
    frame = pl.DataFrame(
        {
            "x": np.arange(ROWS, dtype=float),
            "y": place_ + rng.uniform(0, 0.5, ROWS),
            "g": [f"g{p + 1}" for p in place_],
            "half": ["lo" if p < 80 else "hi" for p in place_],
            "s": [f"s{i % 30 + 1}" for i in range(ROWS)],
            "v": rng.normal(0, 1, ROWS),
        }
    )
    path = tmp_path / "levels.parquet"
    frame.write_parquet(path)
    return path


@pytest.fixture(autouse=True)
def toasts_let_drops_through(app_page: Page) -> None:
    """Let the pointer through the error toasts, which lie over the zones at the top right."""
    app_page.add_style_tag(
        content="#toasts, #toasts * { pointer-events: none !important; }"
    )


def card(page: Page, column: str) -> Locator:
    """Return the filter card of a column."""
    return page.locator(".filter-card").filter(
        has=page.locator(".filter-card-name").get_by_text(column, exact=True)
    )


def box(page: Page, column: str, level: str) -> Locator:
    """Return the check box of a level of a column's filter card."""
    return (
        card(page, column)
        .locator(".filter-level")
        .filter(has=page.get_by_text(level, exact=True))
        .locator("input")
    )


def tick(
    page: Page, column: str, levels: list[str], path: str = "**/api/overview"
) -> None:
    """Tick levels of a card (in one commit) and wait for the result they ask for."""
    with page.expect_response(path) as answered:
        for level in levels:
            box(page, column, level).check()
    assert answered.value.ok, answered.value.text()
    page.wait_for_function(SETTLED)


def add_filter(page: Page, column: str) -> None:
    """Add a column to the filter pane from its menu (Issue #162) and wait for its levels."""
    pick(page, column, "Add to Local filter")
    expect(card(page, column).locator(".filter-level").first).to_be_visible()


def names(page: Page) -> list[str]:
    """Return the names of the color legend's items."""
    return page.locator(LEGEND_NAMES).all_inner_texts()


def open_color_menu(page: Page) -> None:
    """Right-click the Color zone's chip."""
    page.locator('.zone[data-role="color"] .chip').click(button="right")
    expect(page.locator(".zone-menu")).to_be_visible()


def zoom(page: Page, lo: float, hi: float) -> None:
    """Zoom the x axis and wait for its view."""
    with page.expect_response("**/api/view") as answered:
        page.evaluate(f"Plotly.relayout('plot', {{'xaxis.range': [{lo}, {hi}]}})")
    assert answered.value.ok
    page.wait_for_function(SETTLED)


# The API requests that aggregate.
AGGREGATING = ("plot", "overview", "view", "selection")


def api_requests(page: Page) -> list[str]:
    """Collect the names of the requests that aggregate from now on."""
    paths: list[str] = []

    def seen(url: str) -> None:
        name = url.split("/api/")[-1].split("?")[0]
        if "/api/" in url and name in AGGREGATING:
            paths.append(name)

    page.on("request", lambda r: seen(r.url))
    return paths


def wait_until(page: Page, done: Callable[[], bool]) -> None:
    """Let the page run until `done()` holds, for 15s at most."""
    for _ in range(25):
        if done():
            return
        settle(page)
    raise AssertionError("timed out")


def settle(page: Page) -> None:
    """Let the page handle what it was given."""
    page.evaluate("() => new Promise((resolve) => setTimeout(resolve, 600))")


def test_the_levels_of_the_filter_and_the_menu_item(app_page: Page) -> None:
    """A column of 150 levels filtered to 10 colors by those 10; the item is on Color's menu for a categorical column alone, and keeping the 150 is refused, the figure and the axes kept."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    add_filter(page, "g")
    tick(page, "g", [f"g{i}" for i in range(1, 11)])
    place(page, "g", "color")
    expect(page.locator(LEGEND_NAMES)).to_have_text([f"g{i}" for i in range(1, 11)])

    # Symbol's menu has Show null rows alone.
    place(page, "s", "symbol")
    page.locator('.zone[data-role="symbol"] .chip').click(button="right")
    expect(page.locator(NULL_ROWS)).to_be_visible()
    expect(page.locator(KEEP)).to_have_count(0)
    page.keyboard.press("Escape")
    move(page, "symbol", "#columns")
    wait_idle(page)

    zoom(page, 100, 2000)
    shown = page.evaluate(X_RANGE)
    layout = page.evaluate(LAYOUT)
    open_color_menu(page)
    expect(page.locator(KEEP)).to_have_text("フィルタで除外された水準も凡例に残す")
    expect(page.locator(KEEP)).to_have_class("scale-menu-item")
    with page.expect_response("**/api/plot") as refused:
        page.locator(KEEP).click()
    assert refused.value.status >= 400
    expect(page.locator("#status")).to_contain_text("g は 150 個で")
    wait_idle(page)
    open_color_menu(page)
    expect(page.locator(KEEP)).to_have_class("scale-menu-item")
    page.keyboard.press("Escape")
    expect(page.locator(LEGEND_NAMES)).to_have_text([f"g{i}" for i in range(1, 11)])
    assert page.evaluate(X_RANGE) == pytest.approx(shown)
    assert page.evaluate(LAYOUT) == layout

    # A numeric column on Color: a gradient, without the item.
    move(page, "color", "#columns")
    place(page, "v", "color")
    open_color_menu(page)
    expect(page.locator(NULL_ROWS)).to_be_visible()
    expect(page.locator(KEEP)).to_have_count(0)
    page.keyboard.press("Escape")
    # Cut into intervals, neither.
    page.locator("#legend .colorbar").click(button="right")
    page.locator(".scale-menu").get_by_text("3 個", exact=True).click()
    page.wait_for_function(SETTLED)
    expect(page.locator("#legend .legend-item")).to_have_count(3)
    open_color_menu(page)
    expect(page.locator(NULL_ROWS)).to_be_visible()
    expect(page.locator(KEEP)).to_have_count(0)
    page.keyboard.press("Escape")
    assert errors == []


def test_kept_levels_keep_the_colors_of_every_row(app_page: Page) -> None:
    """On, the 30 levels stay with the 25 the filter leaves out marked without rows, in their colors of every row; the setting stays over a removed column and a zoom, and a reload turns it off."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "s", "color")
    every = [f"s{i}" for i in range(1, 31)]
    expect(page.locator(LEGEND_NAMES)).to_have_text(every)
    colors = page.evaluate(SWATCHES)
    assert colors == [PALETTE[i % len(PALETTE)] for i in range(30)]
    add_filter(page, "s")
    kept = ["s2", "s4", "s6", "s8", "s10"]
    tick(page, "s", kept)
    # Off: the levels of the filter, in the palette's order.
    expect(page.locator(LEGEND_NAMES)).to_have_text(kept)
    assert page.evaluate(SWATCHES) == PALETTE[:5]

    zoom(page, 100, 2500)
    shown = page.evaluate(X_RANGE)
    open_color_menu(page)
    with page.expect_response("**/api/plot") as plotted:
        page.locator(KEEP).click()
    assert plotted.value.ok
    page.wait_for_function(SETTLED)
    expect(page.locator(LEGEND_NAMES)).to_have_text(every)
    items = page.locator("#legend .legend-item")
    expect(items.filter(has_text="（行なし）")).to_have_count(25)
    for level in kept:
        expect(items.filter(has=page.get_by_text(level, exact=True))).not_to_have_class(
            re.compile(r"\bempty\b")
        )
    assert page.evaluate(SWATCHES) == colors
    assert page.evaluate(X_RANGE) == pytest.approx(shown)

    # Kept over the column's removal and placing it again.
    move(page, "color", "#columns")
    wait_idle(page)
    place(page, "s", "color")
    expect(page.locator(LEGEND_NAMES)).to_have_text(every)
    open_color_menu(page)
    expect(page.locator(KEEP)).to_have_class("scale-menu-item checked")
    page.keyboard.press("Escape")

    page.reload()
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "s", "color")
    open_color_menu(page)
    expect(page.locator(KEEP)).to_have_class("scale-menu-item")
    page.keyboard.press("Escape")
    assert errors == []


def test_another_filter_orders_the_legend_and_a_zoom_keeps_it(app_page: Page) -> None:
    """Off, each filter has its levels in natural order and the palette's colors; a zoom keeps them; other levels start active, and a picked color stays with its level."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "s", "color")
    add_filter(page, "s")
    tick(page, "s", ["s4", "s2"])
    expect(page.locator(LEGEND_NAMES)).to_have_text(["s2", "s4"])
    assert page.evaluate(SWATCHES) == PALETTE[:2]

    zoom(page, 300, 1800)
    expect(page.locator(LEGEND_NAMES)).to_have_text(["s2", "s4"])
    assert page.evaluate(SWATCHES) == PALETTE[:2]
    items = page.locator("#legend .legend-item")
    items.nth(1).click()
    expect(items.nth(1)).to_have_class(re.compile(r"\binactive\b"))
    # A pan of the same filter keeps the levels and their state.
    zoom(page, 400, 1900)
    expect(items.nth(1)).to_have_class(re.compile(r"\binactive\b"))

    # Other levels: every one starts active.
    tick(page, "s", ["s1"], "**/api/view")
    expect(page.locator(LEGEND_NAMES)).to_have_text(["s1", "s2", "s4"])
    assert page.evaluate(SWATCHES) == PALETTE[:3]
    expect(page.locator("#legend .legend-item.inactive")).to_have_count(0)

    # A color picked for s2 stays while s2 does, at any place.
    items.nth(1).locator(".legend-marker").click(button="right")
    page.locator(".shape-menu").get_by_text("色", exact=True).hover()
    page.locator('.color-panel .color-cell[title="#000000"]').click()
    expect(items.nth(1).locator(".swatch")).to_have_css(
        "background-color", "rgb(0, 0, 0)"
    )
    page.keyboard.press("Escape")
    box(page, "s", "s1").uncheck()
    with page.expect_response("**/api/view"):
        box(page, "s", "s6").check()
    page.wait_for_function(SETTLED)
    expect(page.locator(LEGEND_NAMES)).to_have_text(["s2", "s4", "s6"])
    assert page.evaluate(SWATCHES) == ["rgb(0, 0, 0)", PALETTE[1], PALETTE[2]]
    assert errors == []


def lo_drawn(page: Page) -> None:
    """Draw x and y colored by g, filtered to half lo: 80 levels."""
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    add_filter(page, "half")
    tick(page, "half", ["lo"])
    place(page, "g", "color")
    expect(page.locator(LEGEND_NAMES)).to_have_count(80)


def expect_lo(page: Page) -> None:
    """Expect the filter pane back at its one card of half, lo ticked."""
    expect(page.locator(".filter-card")).to_have_count(1)
    expect(box(page, "half", "lo")).to_be_checked()
    expect(box(page, "half", "hi")).not_to_be_checked()
    expect(page.locator(".filter-summary")).to_have_text("（1）half: 1/2")


def test_a_filter_past_the_limit_goes_back_to_the_last_drawn(app_page: Page) -> None:
    """A tick or a removed card that lets past 100 levels tells so and puts the figure and the filter pane back as last drawn, asking nothing; another condition then draws, zoomed too."""
    page = app_page
    errors = watch_errors(page)
    status = page.locator("#status")
    lo_drawn(page)
    layout = page.evaluate(LAYOUT)
    legend = names(page)
    asked = api_requests(page)

    # A tick that adds levels.
    with page.expect_response("**/api/overview") as refused:
        box(page, "half", "hi").check()
    assert refused.value.status == 400
    assert refused.value.json()["error"] == "filtered_color_levels"
    expect(status).to_have_text(REFUSED)
    expect_lo(page)
    settle(page)
    assert asked == ["overview"]
    assert page.evaluate(LAYOUT) == layout
    assert names(page) == legend
    expect(page.locator("#toasts .toast")).to_contain_text([REFUSED])

    # Another condition draws.
    box(page, "half", "lo").uncheck()
    tick(page, "half", ["hi"])
    expect(page.locator(LEGEND_NAMES)).to_have_count(70)
    expect(page.locator(LEGEND_NAMES).first).to_have_text("g81")

    # The removed card comes back as it was.
    layout = page.evaluate(LAYOUT)
    asked.clear()
    with page.expect_response("**/api/overview") as refused:
        card(page, "half").locator(".filter-card-remove").click()
    assert refused.value.status == 400
    expect(status).to_have_text(REFUSED)
    expect(page.locator(".filter-card")).to_have_count(1)
    expect(box(page, "half", "hi")).to_be_checked()
    expect(box(page, "half", "lo")).not_to_be_checked()
    settle(page)
    assert asked == ["overview"]
    assert page.evaluate(LAYOUT) == layout
    expect(page.locator(LEGEND_NAMES)).to_have_count(70)

    # Zoomed: the view is refused, the axes stay.
    zoom(page, 200, 1500)
    shown = page.evaluate(X_RANGE)
    layout = page.evaluate(LAYOUT)
    asked.clear()
    with page.expect_response("**/api/view") as refused:
        box(page, "half", "lo").check()
    assert refused.value.status == 400
    expect(status).to_have_text(REFUSED)
    expect(box(page, "half", "lo")).not_to_be_checked()
    settle(page)
    assert asked == ["view"]
    assert page.evaluate(X_RANGE) == pytest.approx(shown)
    assert page.evaluate(LAYOUT) == layout
    expect(page.locator(LEGEND_NAMES)).to_have_count(70)
    assert errors == []


def test_a_zoom_while_waiting_keeps_its_ranges(app_page: Page) -> None:
    """Zoomed while the refused filter is aggregated, the axes keep the zoom and one view of the filter drawn last is asked for."""
    page = app_page
    errors = watch_errors(page)
    lo_drawn(page)
    held: list[Route] = []
    page.route("**/api/overview", lambda route: held.append(route))
    box(page, "half", "hi").check()
    page.wait_for_function(
        "() => document.getElementById('plot').classList.contains('busy')"
    )
    wait_until(page, lambda: bool(held))
    views: list[int] = []
    page.on(
        "response",
        lambda r: views.append(r.status) if r.url.endswith("/api/view") else None,
    )
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [300, 1200]})")
    wait_until(page, lambda: len(views) >= 2)
    wait_idle(page)
    settle(page)
    assert views == [400, 200]
    # The error stays until the next edit.
    expect(page.locator("#status")).to_have_text(REFUSED)
    assert page.evaluate(X_RANGE) == pytest.approx([300, 1200])
    expect_lo(page)
    expect(page.locator(LEGEND_NAMES)).to_have_count(80)
    held[0].fulfill(
        status=409, content_type="application/json", body='{"cancelled": true}'
    )
    page.unroute("**/api/overview")
    settle(page)
    assert errors == []


def test_an_older_refusal_after_a_newer_success_changes_nothing(app_page: Page) -> None:
    """The refusal of a filter that a newer one superseded, come after the newer one was drawn, leaves the pane and the figure of the newer one."""
    page = app_page
    errors = watch_errors(page)
    lo_drawn(page)
    held: list[Route] = []

    def handle(route: Route) -> None:
        if held:
            route.continue_()
        else:
            held.append(route)

    page.route("**/api/overview", handle)
    box(page, "half", "hi").check()
    wait_until(page, lambda: bool(held))
    box(page, "half", "lo").uncheck()
    page.wait_for_function(
        "() => document.querySelectorAll('#legend .legend-item').length === 70"
    )
    page.wait_for_function(SETTLED)
    held[0].fulfill(
        status=400,
        content_type="application/json",
        body=json.dumps(
            {
                "detail": REFUSED.removeprefix("エラー: "),
                "error": "filtered_color_levels",
            }
        ),
    )
    settle(page)
    page.unroute("**/api/overview")
    expect(box(page, "half", "hi")).to_be_checked()
    expect(box(page, "half", "lo")).not_to_be_checked()
    expect(page.locator(LEGEND_NAMES)).to_have_count(70)
    expect(page.locator("#status")).not_to_have_class(re.compile("notice-error"))
    expect(page.locator("#toasts .toast")).to_have_count(0)
    # The page logs the error answer it was given: no other.
    assert errors == []


def test_the_hover_selection_and_lines_follow_the_new_levels(app_page: Page) -> None:
    """After another filter changed the levels, the hover names and colors a row by its level, the table lists the rows of the legend's levels, and the lines take their level's color."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "s", "color")
    line = page.locator('#elements .element[data-element="line"]')
    line.click()
    expect(line).to_have_attribute("aria-pressed", "true")
    wait_idle(page)
    add_filter(page, "s")
    tick(page, "s", ["s9"])
    expect(page.locator(LEGEND_NAMES)).to_have_text(["s9"])
    first = [int(PALETTE[0][4:-1].split(", ")[i]) for i in range(3)]
    page.wait_for_function(HAS_COLOR, arg=first)

    # Row 1508 is of s9, at y 8 to 8.5.
    point = at(page, 1508, 8.25)
    page.mouse.move(point["x"], point["y"])
    label = page.locator("#hover-label")
    expect(label).to_be_visible()
    lines = dict(row.split(": ", 1) for row in label.inner_text().splitlines())
    assert lines["s"] == "s9"
    assert "（s9: " in lines["このピクセル"]
    expect(label).to_have_css("background-color", PALETTE[0])
    page.mouse.move(0, 0)

    page.evaluate("Plotly.relayout('plot', {dragmode: 'select'})")
    area = page.locator("#plot .nsewdrag").first.bounding_box()
    assert area is not None
    with page.expect_response("**/api/selection") as selected:
        page.mouse.move(area["x"] + 5, area["y"] + 5)
        page.mouse.down()
        page.mouse.move(
            area["x"] + area["width"] - 5, area["y"] + area["height"] - 5, steps=5
        )
        page.mouse.up()
    assert selected.value.json()["rows"] > 0
    expect(page.locator("#table")).to_be_visible()
    table = page.evaluate("() => fetch('/api/table').then((r) => r.json())")
    values = next(c["values"] for c in table["columns"] if c["name"] == "s")
    assert set(values) == {"s9"}
    assert errors == []


def test_a_refusal_while_an_old_overview_stands_in_draws_the_last_filter(
    app_page: Page,
) -> None:
    """Back from a zoom of another filter, the old overview stands in; a refused filter then goes back to the filter drawn last and draws its overview, not the old one."""
    page = app_page
    errors = watch_errors(page)
    lo_drawn(page)
    zoom(page, 200, 1500)
    box(page, "half", "lo").uncheck()
    tick(page, "half", ["hi"], "**/api/view")
    expect(page.locator(LEGEND_NAMES)).to_have_count(70)
    held: list[Route] = []
    answers: list[int] = []

    def handle(route: Route) -> None:
        if held:
            route.continue_()
        else:
            held.append(route)

    page.route("**/api/overview", handle)
    page.on(
        "response",
        lambda r: answers.append(r.status) if r.url.endswith("/api/overview") else None,
    )
    # Back to the whole ranges: the overview of lo stands in.
    page.evaluate(
        "Plotly.relayout('plot', {'xaxis.autorange': true, 'yaxis.autorange': true})"
    )
    wait_until(page, lambda: bool(held))
    expect(page.locator(LEGEND_NAMES)).to_have_count(70)
    box(page, "half", "lo").check()
    wait_until(page, lambda: len(answers) >= 2)
    wait_idle(page)
    assert answers == [400, 200]
    expect(page.locator("#status")).to_have_text(REFUSED)
    expect(box(page, "half", "hi")).to_be_checked()
    expect(box(page, "half", "lo")).not_to_be_checked()
    expect(page.locator(LEGEND_NAMES)).to_have_count(70)
    # The overview drawn is that of hi.
    assert (
        page.evaluate(
            "() => document.getElementById('plot').classList.contains('pending')"
        )
        is False
    )
    held[0].fulfill(
        status=409, content_type="application/json", body='{"cancelled": true}'
    )
    page.unroute("**/api/overview")
    settle(page)
    assert errors == []


# Holds the text of the next answer of the path given (`/api/overview` or
# `/api/view`) until `window.releaseText()`; its headers come at once.
HOLD_TEXT = """(path) => {
  const original = window.fetch;
  window.fetch = async (url, options) => {
    const response = await original(url, options);
    if (!String(url).endsWith(path) || window.releaseText) return response;
    const hold = new Promise((resolve) => { window.releaseText = resolve; });
    const text = response.text();
    return {
      ok: response.ok,
      status: response.status,
      text: async () => { await hold; return text; },
      json: async () => { await hold; return JSON.parse(await text); },
    };
  };
}"""


@pytest.mark.parametrize("path", ["/api/overview", "/api/view"])
def test_a_refusal_read_after_a_newer_request_changes_nothing(
    app_page: Page, path: str
) -> None:
    """A refusal of the overview or of a zoomed view whose text is read after a newer filter was sent leaves the pane, the pending figure and the status to the newer filter, which is then drawn."""
    page = app_page
    errors = watch_errors(page)
    lo_drawn(page)
    if path == "/api/view":
        zoom(page, 200, 1500)
    page.evaluate(HOLD_TEXT, path)
    with page.expect_response(f"**{path}") as refused:
        box(page, "half", "hi").check()
    assert refused.value.status == 400
    page.wait_for_function("() => Boolean(window.releaseText)")
    # The newer filter is held while the old text is read.
    newer: list[Route] = []
    page.route(f"**{path}", lambda route: newer.append(route))
    box(page, "half", "lo").uncheck()
    wait_until(page, lambda: bool(newer))
    page.evaluate("() => window.releaseText()")
    settle(page)
    expect(box(page, "half", "hi")).to_be_checked()
    expect(box(page, "half", "lo")).not_to_be_checked()
    expect(page.locator("#status")).not_to_have_class(re.compile("notice-error"))
    expect(page.locator("#toasts .toast")).to_have_count(0)
    # The newer request still waits.
    expect(page.locator("#plot")).to_have_class(re.compile(r"\bbusy\b"))
    newer[0].continue_()
    page.unroute(f"**{path}")
    page.wait_for_function(
        "() => document.querySelectorAll('#legend .legend-item').length === 70"
    )
    page.wait_for_function(SETTLED)
    expect(box(page, "half", "hi")).to_be_checked()
    expect(box(page, "half", "lo")).not_to_be_checked()
    assert errors == []
