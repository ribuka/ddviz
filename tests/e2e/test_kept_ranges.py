"""E2E: an edit of the graph keeps the zoomed ranges of the axis columns it keeps."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.test_axis_format import open_dialog
from tests.e2e.test_axis_menu import _right_click_tick, add_second_y
from tests.e2e.test_scatter import SETTLED, place, wait_idle, watch_errors

pytestmark = pytest.mark.e2e

FULL = "document.getElementById('plot')._fullLayout"
VIEW = re.compile(r"/api/view\b")
X_ZOOM = [-1.0, 1.0]
Y_ZOOM = [-0.5, 0.5]


def shown(page: Page, key: str) -> list[float]:
    """Return the range of plotly's axis `key`, in linear units, in plotly's order."""
    return page.evaluate(
        f"() => {{ const a = {FULL}.{key}; return a.range.map((v) => a.r2l(v)); }}"
    )


def settle(page: Page) -> None:
    """Wait for the result of the last request, and for nothing aggregated."""
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    wait_idle(page)


def zoom(page: Page, update: dict) -> None:
    """Zoom the axes with a relayout, and wait for the view."""
    with page.expect_request(VIEW):
        page.evaluate("(update) => Plotly.relayout('plot', update)", update)
    settle(page)


def edit_keeps(page: Page, edit: Callable[[], None], x: list, y: list) -> None:
    """Run an edit that plots again: the view of its result is aggregated at the ranges `x` and `y` (one per axis column), which the axes show."""
    with page.expect_request(VIEW) as request:
        edit()
    body = request.value.post_data_json
    assert body["x_ranges"] == [pytest.approx(r) for r in x]
    assert body["y_ranges"] == [pytest.approx(r) for r in y]
    settle(page)
    assert shown(page, "xaxis") == pytest.approx(x[0])
    assert shown(page, "yaxis") == pytest.approx(y[0])


def scale_menu(page: Page, name: str) -> None:
    """Pick an item of the color scale's menu (right click on the legend's title)."""
    page.locator("#legend .scale").first.click(button="right")
    page.locator(".scale-menu").get_by_text(name, exact=True).click()
    expect(page.locator(".scale-menu")).to_have_count(0)


def test_edits_of_the_figure_keep_the_zoomed_ranges(app_page: Page) -> None:
    """Color bins, smoothing, points, lines and a wrap plot again at the zoomed view; Reset axes goes back to the edited overview."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "x", "color")
    zoom(page, {"xaxis.range": X_ZOOM, "yaxis.range": Y_ZOOM})
    keeps = lambda edit: edit_keeps(page, edit, [X_ZOOM], [Y_ZOOM])

    keeps(lambda: scale_menu(page, "5 個"))
    keeps(lambda: scale_menu(page, "行数で等分"))
    keeps(lambda: scale_menu(page, "連続（グラデーション）"))
    smooth = page.locator('#elements .element[data-element="smooth"]')
    points = page.locator('#elements .element[data-element="points"]')
    line = page.locator('#elements .element[data-element="line"]')
    keeps(smooth.click)

    def lowess() -> None:
        smooth.click(button="right")
        page.locator(".scale-menu").get_by_text("lowess", exact=True).click()

    keeps(lowess)
    keeps(points.click)
    keeps(points.click)
    if line.is_enabled():
        keeps(line.click)
    # A wrap's panels share the ranges.
    with page.expect_request(VIEW) as request:
        page.locator("#columns .column").filter(
            has=page.get_by_text("facet", exact=True)
        ).drag_to(page.locator('.zone[data-role="wrap"]'))
    assert request.value.post_data_json["x_ranges"] == [pytest.approx(X_ZOOM)]
    settle(page)
    for key in ["xaxis", "xaxis2"]:
        assert shown(page, key) == pytest.approx(X_ZOOM)

    # Reset axes draws the edited overview.
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.click(
        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right"
    )
    page.locator(".plot-menu").get_by_role("button", name="Reset axes").click()
    settle(page)
    for key in ["xaxis", "yaxis"]:
        lo, hi = shown(page, key)
        assert lo < -2 and hi > 2
    assert errors == []


def test_axis_columns_added_moved_or_left_whole_take_the_new_whole_range(
    app_page: Page,
) -> None:
    """A kept axis keeps its zoom; a new one, one moved to the other role and one shown whole take the whole range; a log toggle resets its own axis alone."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    # y alone is zoomed: x stays whole.
    zoom(page, {"yaxis.range": Y_ZOOM})
    whole_x = shown(page, "xaxis")

    # A second y column: x in the Y role is a new y axis, apart from x in X.
    with page.expect_request(VIEW) as request:
        add_second_y(page, "x")
    body = request.value.post_data_json
    assert body["y_ranges"][0] == pytest.approx(Y_ZOOM)
    settle(page)
    assert shown(page, "xaxis") == pytest.approx(whole_x)
    assert shown(page, "yaxis") == pytest.approx(Y_ZOOM)
    lo, hi = shown(page, "yaxis2")
    assert lo < -2 and hi > 2

    # The second y removed, then added again: it starts whole.
    page.locator('.zone[data-role="y"] .chip-remove').last.click()
    settle(page)
    assert shown(page, "yaxis") == pytest.approx(Y_ZOOM)

    # A log x resets x alone; y keeps its zoom.
    zoom(page, {"xaxis.range": [0.5, 1.5]})
    page.evaluate("Plotly.relayout('plot', {'yaxis.range': [0.2, 0.8]})")
    settle(page)
    ticks = page.locator("#plot .xtick text")
    box = ticks.nth(ticks.count() // 2).bounding_box()
    page.mouse.click(
        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right"
    )
    page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    page.wait_for_function(f"() => {FULL}.xaxis.type === 'log'")
    settle(page)
    assert shown(page, "yaxis") == pytest.approx([0.2, 0.8])
    lo, hi = shown(page, "xaxis")
    assert -6 < lo < hi < 1
    assert errors == []


def test_an_edit_at_the_whole_ranges_asks_no_view(app_page: Page) -> None:
    """An edit of a figure shown whole draws its new overview without a view."""
    page = app_page
    place(page, "x", "x")
    place(page, "y", "y")
    views: list[str] = []
    page.on("request", lambda r: VIEW.search(r.url) and views.append(r.url))
    page.locator('#elements .element[data-element="smooth"]').click()
    settle(page)
    page.locator('#elements .element[data-element="points"]').click()
    settle(page)
    assert views == []


def test_a_reversed_axis_a_dialog_range_and_a_categorical_axis_are_kept(
    app_page: Page,
) -> None:
    """A range typed in the axis dialog stays reversed, and the bands zoomed stay, over an edit."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "color", "y")
    _right_click_tick(page, "x")
    page.locator(".axis-menu").get_by_role("button", name="向きを反転").click()
    page.wait_for_function(f"() => {FULL}.xaxis.range[0] > {FULL}.xaxis.range[1]")
    dialog = open_dialog(page, "x")
    dialog.locator("input[name=min]").fill("-1")
    dialog.locator("input[name=max]").fill("1")
    with page.expect_request(VIEW):
        dialog.get_by_role("button", name="OK").click()
    settle(page)
    zoom(page, {"yaxis.range": [-0.5, 1.5]})

    with page.expect_request(VIEW) as request:
        place(page, "facet", "color")
    body = request.value.post_data_json
    assert body["x_ranges"] == [pytest.approx([-1, 1])]
    assert body["y_ranges"] == [pytest.approx([-0.5, 1.5])]
    assert shown(page, "xaxis") == pytest.approx([1, -1])
    assert shown(page, "yaxis") == pytest.approx([-0.5, 1.5])
    assert errors == []


def test_a_pan_while_an_edit_is_aggregated_wins(app_page: Page) -> None:
    """The ranges on screen when the edited result comes are those it shows; edits in a row end at the last."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    zoom(page, {"xaxis.range": X_ZOOM, "yaxis.range": Y_ZOOM})
    held: list[Route] = []

    holding = [True]

    def hold(route: Route) -> None:
        if holding[0]:
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/plot", hold)
    page.locator('#elements .element[data-element="smooth"]').click()
    page.wait_for_function(
        "() => document.getElementById('plot').classList.contains('busy')"
    )
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [0, 2]})")
    # A second edit supersedes the first.
    page.locator('#elements .element[data-element="smooth"]').click()
    while len(held) < 2:
        page.wait_for_timeout(50)
    holding[0] = False
    with page.expect_request(VIEW) as request:
        for route in held:
            route.continue_()
    body = request.value.post_data_json
    assert body["x_ranges"] == [pytest.approx([0, 2])]
    assert body["y_ranges"] == [pytest.approx(Y_ZOOM)]
    settle(page)
    assert shown(page, "xaxis") == pytest.approx([0, 2])
    expect(page.locator('#elements .element[data-element="smooth"]')).to_have_attribute(
        "aria-pressed", "false"
    )
    assert errors == []
