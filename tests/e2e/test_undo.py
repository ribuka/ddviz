"""E2E: undo and redo of the drawing settings, by the buttons and the keys (Issue #277)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, Request, Route, expect

from tests.e2e.test_app_menu import FAKE_API, GEOMETRY
from tests.e2e.test_axis_freeze import card
from tests.e2e.test_kept_ranges import zoom
from tests.e2e.test_scatter import (
    drop_on_filters,
    place,
    wait_idle,
    watch_errors,
)

pytestmark = pytest.mark.e2e

UNDO = "元に戻す (Ctrl+Z)"
REDO = "やり直す (Ctrl+Y)"
FULL = "document.getElementById('plot')._fullLayout"


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write x and y around 0, and z around 100."""
    rng = np.random.default_rng(0)
    n = 2000
    frame = pl.DataFrame(
        {
            "x": rng.normal(0, 1, n),
            "y": rng.normal(0, 1, n),
            "z": rng.normal(100, 1, n),
        }
    )
    path = tmp_path / "undo.parquet"
    frame.write_parquet(path)
    return path


def plots(page: Page) -> list[dict[str, Any]]:
    """Collect the bodies of the plot requests the page sends from now on."""
    bodies: list[dict[str, Any]] = []

    def on_request(request: Request) -> None:
        if request.url.endswith("/api/plot"):
            bodies.append(request.post_data_json)

    page.on("request", on_request)
    return bodies


def press(page: Page, keys: str) -> dict[str, Any]:
    """Press `keys` with nothing focused, and return the body of the plot it asks for, once drawn."""
    page.evaluate("document.activeElement?.blur()")
    with page.expect_request("**/api/plot") as request:
        page.keyboard.press(keys)
    wait_idle(page)
    return request.value.post_data_json


def click(page: Page, label: str) -> dict[str, Any]:
    """Click the button `label`, and return the body of the plot it asks for, once drawn."""
    with page.expect_request("**/api/plot") as request:
        page.get_by_role("button", name=label).click()
    wait_idle(page)
    return request.value.post_data_json


def chip_names(page: Page, role: str) -> list[str]:
    """Return the names of a role's chips."""
    return page.locator(f'.zone[data-role="{role}"] .chip-name').all_inner_texts()


def x_and_y(page: Page) -> None:
    """Place x on X and y on Y."""
    expect(page.locator("#columns .column").first).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")


def test_the_buttons_lead_the_row_and_start_disabled(app_page: Page) -> None:
    """In a browser the two buttons are the first of the row above the zones, disabled on a new page."""
    page = app_page
    expect(page.locator("#columns .column").first).to_be_visible()
    top = page.locator("#top > *")
    expect(top.nth(0)).to_have_attribute("aria-label", UNDO)
    expect(top.nth(1)).to_have_attribute("aria-label", REDO)
    undo = page.get_by_role("button", name=UNDO)
    redo = page.get_by_role("button", name=REDO)
    expect(undo).to_be_disabled()
    expect(redo).to_be_disabled()
    expect(undo).to_have_attribute("title", UNDO)
    expect(redo).to_have_attribute("title", REDO)
    a, b = undo.bounding_box(), redo.bounding_box()
    elements = page.locator("#elements").bounding_box()
    assert a["x"] + a["width"] <= b["x"]
    assert b["x"] + b["width"] <= elements["x"]
    expect(page.locator("#titlebar")).to_have_count(0)


def test_undo_and_redo_a_column_replaced(app_page: Page) -> None:
    """Undo puts the Y replaced back and plots it; redo puts the new one back; the buttons follow."""
    page = app_page
    errors = watch_errors(page)
    x_and_y(page)
    undo = page.get_by_role("button", name=UNDO)
    redo = page.get_by_role("button", name=REDO)
    expect(undo).to_be_enabled()
    expect(redo).to_be_disabled()
    place(page, "z", "y")
    assert click(page, UNDO)["encoding"]["y"] == ["y"]
    assert chip_names(page, "y") == ["y"]
    expect(redo).to_be_enabled()
    assert click(page, REDO)["encoding"]["y"] == ["z"]
    assert chip_names(page, "y") == ["z"]
    expect(redo).to_be_disabled()
    # Ctrl+Y and Ctrl+Shift+Z redo too.
    assert press(page, "Control+z")["encoding"]["y"] == ["y"]
    assert press(page, "Control+y")["encoding"]["y"] == ["z"]
    assert press(page, "Control+z")["encoding"]["y"] == ["y"]
    assert press(page, "Control+Shift+z")["encoding"]["y"] == ["z"]
    # Back to x alone, then to the first step, the empty graph: neither
    # draws a figure, so neither plots.
    assert press(page, "Control+z")["encoding"]["y"] == ["y"]
    sent = plots(page)
    page.keyboard.press("Control+z")
    assert chip_names(page, "x") == ["x"]
    assert chip_names(page, "y") == []
    page.keyboard.press("Control+z")
    wait_idle(page)
    assert sent == []
    assert chip_names(page, "x") == []
    assert chip_names(page, "y") == []
    expect(page.locator("#empty")).to_be_visible()
    expect(undo).to_be_disabled()
    assert errors == []


def test_undo_takes_back_each_setting(app_page: Page) -> None:
    """The size of the markers, a log Y, an element and a filter come back with Ctrl+Z."""
    page = app_page
    errors = watch_errors(page)
    x_and_y(page)

    # The size of every series' markers.
    points = page.locator('#elements .element[data-element="points"]')
    points.click(button="right")
    with page.expect_request("**/api/plot") as request:
        page.locator(".shape-menu").get_by_text("9 px", exact=True).click()
    assert request.value.post_data_json["shape_size"] == 9
    wait_idle(page)
    assert press(page, "Control+z")["shape_size"] is None

    # A log Y, from the menu of its tick labels.
    ticks = page.locator("#plot .ytick text")
    box = ticks.nth(ticks.count() // 2).bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right")
    with page.expect_request("**/api/plot") as request:
        page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    assert request.value.post_data_json["axis_scales"] == {"x": {}, "y": {"y": "log"}}
    wait_idle(page)
    assert press(page, "Control+z")["axis_scales"] == {"x": {}, "y": {}}
    page.wait_for_function(f"() => {FULL}.yaxis.type === 'linear'")

    # The lines joining the points.
    line = page.locator('#elements .element[data-element="line"]')
    with page.expect_request("**/api/plot") as request:
        line.click()
    assert request.value.post_data_json["encoding"]["elements"] == ["points", "line"]
    wait_idle(page)
    assert press(page, "Control+z")["encoding"]["elements"] == ["points"]
    expect(line).to_have_attribute("aria-pressed", "false")

    # A condition of the filter.
    drop_on_filters(page, page.locator("#columns .column").filter(has=page.get_by_text("x", exact=True)), 1)
    # One edit: the low end alone. Each end entered is an edit of its own,
    # and each result drawn a step.
    inputs = card(page, "x").locator(".filter-range input")
    with page.expect_request("**/api/overview"):
        inputs.first.fill("0")
        inputs.first.press("Enter")
    wait_idle(page)
    body = press(page, "Control+z")
    assert body["filters"] == []
    # The card added is a step of its own: it stays, at its whole range.
    expect(inputs.first).not_to_have_value("0")
    # Redo sends the condition again.
    body = press(page, "Control+y")
    assert [f["column"] for f in body["filters"]] == ["x"]
    assert errors == []


def test_a_zoom_makes_no_step(app_page: Page) -> None:
    """After a zoom, Ctrl+Z takes back the edit before it."""
    page = app_page
    x_and_y(page)
    place(page, "z", "y")
    zoom(page, {"xaxis.range": [-1.0, 1.0]})
    assert press(page, "Control+z")["encoding"]["y"] == ["y"]


def test_ctrl_z_in_a_text_field_is_the_fields(app_page: Page) -> None:
    """With the column search box focused, Ctrl+Z sends no plot and leaves the graph."""
    page = app_page
    x_and_y(page)
    place(page, "z", "y")
    sent = plots(page)
    search = page.locator(".column-search")
    search.click()
    search.press("Control+z")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert sent == []
    assert chip_names(page, "y") == ["z"]


def test_undo_while_plotting_cancels_the_edit(app_page: Page) -> None:
    """Ctrl+Z while a plot is held puts the chips back; the held result, once it comes, is not drawn."""
    page = app_page
    errors = watch_errors(page)
    x_and_y(page)
    held: list[Route] = []

    def hold(route: Route) -> None:
        if not held:
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/plot", hold)
    source = page.locator("#columns .column").filter(has=page.get_by_text("z", exact=True))
    source.drag_to(page.locator('.zone[data-role="y"]'))
    page.wait_for_function("() => document.getElementById('plot').classList.contains('busy')")
    assert chip_names(page, "y") == ["z"]
    redo = page.get_by_role("button", name=REDO)
    expect(page.get_by_role("button", name=UNDO)).to_be_enabled()
    expect(redo).to_be_disabled()
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("Control+z")
    assert chip_names(page, "y") == ["y"]
    # The result of z (around 100) comes, and is dropped.
    held[0].continue_()
    wait_idle(page)
    page.wait_for_timeout(300)
    wait_idle(page)
    assert chip_names(page, "y") == ["y"]
    lo, hi = page.evaluate(f"{FULL}.yaxis.range")
    assert -10 < lo < hi < 10
    # The step shown stays: nothing to redo, and undo goes to x alone.
    expect(redo).to_be_disabled()
    page.unroute("**/api/plot")
    page.keyboard.press("Control+z")
    assert chip_names(page, "y") == []
    assert chip_names(page, "x") == ["x"]
    assert errors == []


@pytest.mark.parametrize("desktop", [True])
def test_the_window_has_the_buttons_in_its_title_bar(page: Page, app_page: Page) -> None:
    """In the window the buttons stand right of `…` and left of the title, out of the caption's drag, and undo."""
    page.add_init_script(GEOMETRY)
    page.add_init_script(FAKE_API)
    page.reload()
    expect(page.locator("#titlebar")).to_be_visible()
    expect(page.locator("#top .undo-button")).to_have_count(0)
    menu = page.locator("#titlebar .titlebar-menu").bounding_box()
    undo = page.locator("#titlebar").get_by_role("button", name=UNDO)
    redo = page.locator("#titlebar").get_by_role("button", name=REDO)
    title = page.locator("#titlebar .titlebar-title").bounding_box()
    a, b = undo.bounding_box(), redo.bounding_box()
    assert menu["x"] + menu["width"] <= a["x"]
    assert a["x"] + a["width"] <= b["x"]
    assert b["x"] + b["width"] <= title["x"]
    for button in (undo, redo):
        assert button.evaluate("(e) => getComputedStyle(e).appRegion") == "no-drag"
        assert button.evaluate("(e) => e.getBoundingClientRect().height") == pytest.approx(menu["height"])
    x_and_y(page)
    place(page, "z", "y")
    with page.expect_request("**/api/plot") as request:
        undo.click()
    assert request.value.post_data_json["encoding"]["y"] == ["y"]
    wait_idle(page)
    assert chip_names(page, "y") == ["y"]


def hold_next_plot(page: Page) -> list[Route]:
    """Hold the next plot request until the test lets it go; the others go through."""
    held: list[Route] = []

    def hold(route: Route) -> None:
        if not held:
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/plot", hold)
    return held


def replace_y_held(page: Page) -> list[Route]:
    """Drop z on Y with its plot held, and wait for the plot to be in flight."""
    held = hold_next_plot(page)
    source = page.locator("#columns .column").filter(has=page.get_by_text("z", exact=True))
    source.drag_to(page.locator('.zone[data-role="y"]'))
    page.wait_for_function("() => document.getElementById('plot').classList.contains('busy')")
    assert chip_names(page, "y") == ["z"]
    return held


def reverse_x(page: Page) -> None:
    """Reverse X from the menu of its tick labels."""
    ticks = page.locator("#plot .xtick text")
    box = ticks.nth(ticks.count() // 2).bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right")
    page.locator(".axis-menu").get_by_role("button", name="向きを反転").click()


def x_reversed(page: Page) -> bool:
    """Return whether plotly draws X reversed."""
    return page.evaluate(f"() => {{ const r = {FULL}.xaxis.range; return r[0] > r[1]; }}")


def let_go(page: Page, held: list[Route], fail: bool) -> None:
    """Let the held plot go, or answer it with a failure, and wait for it to settle."""
    if fail:
        held[0].fulfill(status=500, body="boom")
        expect(page.locator("#status")).to_contain_text("boom")
    else:
        held[0].continue_()
    wait_idle(page)
    page.unroute("**/api/plot")


@pytest.mark.parametrize("fail", [False, True])
def test_a_direction_set_while_plotting_is_a_step_of_its_own(app_page: Page, fail: bool) -> None:
    """A direction reversed while an edit is plotted is a step without the edit; the edit, drawn, is the next step."""
    page = app_page
    page.add_style_tag(content="#toasts, #toasts * { pointer-events: none !important; }")
    x_and_y(page)
    held = replace_y_held(page)
    reverse_x(page)
    page.wait_for_function(f"() => {{ const r = {FULL}.xaxis.range; return r[0] > r[1]; }}")
    let_go(page, held, fail)
    assert x_reversed(page)
    if not fail:
        assert chip_names(page, "y") == ["z"]
        # The edit goes back, the direction stays.
        assert press(page, "Control+z")["encoding"]["y"] == ["y"]
        assert x_reversed(page)
    else:
        assert chip_names(page, "y") == ["y"]
    # Then the direction goes back, on the graph drawn before the edit.
    assert press(page, "Control+z")["encoding"]["y"] == ["y"]
    assert not x_reversed(page)
    assert chip_names(page, "y") == ["y"]


@pytest.mark.parametrize("fail", [False, True])
def test_a_card_added_while_plotting_is_a_step_of_its_own(app_page: Page, fail: bool) -> None:
    """A filter card added while an edit is plotted is a step without the edit; the edit, drawn, is the next step."""
    page = app_page
    page.add_style_tag(content="#toasts, #toasts * { pointer-events: none !important; }")
    x_and_y(page)
    held = replace_y_held(page)
    drop_on_filters(page, page.locator("#columns .column").filter(has=page.get_by_text("x", exact=True)), 1)
    let_go(page, held, fail)
    expect(page.locator(".filter-card")).to_have_count(1)
    if not fail:
        assert press(page, "Control+z")["encoding"]["y"] == ["y"]
        expect(page.locator(".filter-card")).to_have_count(1)
    # Then the card goes, on the graph drawn before the edit.
    assert press(page, "Control+z")["encoding"]["y"] == ["y"]
    expect(page.locator(".filter-card")).to_have_count(0)
    assert chip_names(page, "y") == ["y"]


def test_undo_while_plotting_keeps_a_direction_set_meanwhile(app_page: Page) -> None:
    """Ctrl+Z while an edit is plotted cancels the edit and keeps the direction reversed meanwhile."""
    page = app_page
    x_and_y(page)
    held = replace_y_held(page)
    reverse_x(page)
    page.wait_for_function(f"() => {{ const r = {FULL}.xaxis.range; return r[0] > r[1]; }}")
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("Control+z")
    assert chip_names(page, "y") == ["y"]
    let_go(page, held, False)
    assert x_reversed(page)
    assert chip_names(page, "y") == ["y"]
    assert press(page, "Control+z")["encoding"]["y"] == ["y"]
    assert not x_reversed(page)


# Holds the next figure plotly draws until `window.releaseDraw()`.
HOLD_DRAW = """() => {
  const draw = Plotly.newPlot;
  window.releaseDraw = null;
  Plotly.newPlot = (...args) => {
    Plotly.newPlot = draw;
    return new Promise((done) => {
      window.releaseDraw = () => draw.apply(Plotly, args).then(done);
    });
  };
}"""


def test_a_plot_superseded_while_drawn_is_no_step(app_page: Page) -> None:
    """A plot whose figure a newer edit supersedes while it is drawn is not committed: undo skips it."""
    page = app_page
    errors = watch_errors(page)
    x_and_y(page)
    page.evaluate(HOLD_DRAW)
    column = page.locator("#columns .column")
    y_zone = page.locator('.zone[data-role="y"]')
    column.filter(has=page.get_by_text("z", exact=True)).drag_to(y_zone)
    page.wait_for_function("() => window.releaseDraw !== null")
    # y again, its plot held while z's figure is drawn.
    held = hold_next_plot(page)
    column.filter(has=page.get_by_text("y", exact=True)).drag_to(y_zone)
    while not held:
        page.wait_for_timeout(50)
    page.evaluate("window.releaseDraw()")
    page.wait_for_timeout(300)
    held[0].continue_()
    wait_idle(page)
    page.unroute("**/api/plot")
    assert chip_names(page, "y") == ["y"]
    lo, hi = page.evaluate(f"{FULL}.yaxis.range")
    assert -10 < lo < hi < 10
    # The step before is x alone: z was never committed.
    sent = plots(page)
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("Control+z")
    wait_idle(page)
    assert sent == []
    assert chip_names(page, "y") == []
    assert chip_names(page, "x") == ["x"]
    assert errors == []


def test_a_card_added_while_undo_fails_keeps_the_direction_shown(app_page: Page) -> None:
    """A card added while an undo is plotted takes only the card: when the undo fails, the direction shown stays for the next plot."""
    page = app_page
    page.add_style_tag(content="#toasts, #toasts * { pointer-events: none !important; }")
    x_and_y(page)
    reverse_x(page)
    page.wait_for_function(f"() => {{ const r = {FULL}.xaxis.range; return r[0] > r[1]; }}")
    held = hold_next_plot(page)
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("Control+z")
    page.wait_for_function("() => document.getElementById('plot').classList.contains('busy')")
    drop_on_filters(page, page.locator("#columns .column").filter(has=page.get_by_text("x", exact=True)), 1)
    let_go(page, held, True)
    assert x_reversed(page)
    expect(page.locator(".filter-card")).to_have_count(1)
    place(page, "z", "y")
    assert x_reversed(page)
