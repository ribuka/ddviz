"""E2E: the continuous axes follow the local filter, and the lock at the bottom left keeps their ranges (Issue #228)."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.test_axis_direction import _reverse
from tests.e2e.test_axis_menu import _right_click_tick, add_second_y
from tests.e2e.test_kept_ranges import settle, shown
from tests.e2e.test_scatter import place, wait_idle, watch_errors

pytestmark = pytest.mark.e2e

ROWS = 1001
# Naive, as a Parquet datetime without a time zone.
START = dt.datetime(2026, 11, 1)  # noqa: DTZ001
LOCK = "#axis-freeze"
# The whole x (0 to 100) with its 2% margin, and x filtered to 20..40.
WHOLE_X = [-2.0, 102.0]
NARROW_X = [19.6, 40.4]


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Serve x from 0 to 100 by 0.1, y = 2x, a datetime a minute apart, and two groups."""
    path = tmp_path / "freeze.parquet"
    pl.DataFrame(
        {
            "x": [i / 10 for i in range(ROWS)],
            "y": [i / 5 for i in range(ROWS)],
            "at": [START + dt.timedelta(minutes=i) for i in range(ROWS)],
            "g": [f"g{i % 2}" for i in range(ROWS)],
        }
    ).write_parquet(path)
    return path


def epoch_ms(at: dt.datetime) -> float:
    """Return a naive datetime as milliseconds since the epoch, read as UTC."""
    return (at - dt.datetime(1970, 1, 1)).total_seconds() * 1000  # noqa: DTZ001


def add_filter(page: Page, column: str) -> None:
    """Drop a column on the filter pane and wait for its card."""
    page.locator("#columns .column").filter(
        has=page.get_by_text(column, exact=True)
    ).drag_to(page.locator("#filters"))
    expect(card(page, column).locator(".filter-range input").first).to_be_visible()


def card(page: Page, column: str) -> object:
    """Return the filter card of a column."""
    return page.locator(".filter-card").filter(
        has=page.locator(".filter-card-name", has_text=column)
    )


def set_range(page: Page, column: str, low: str, high: str) -> None:
    """Type both ends of a numeric card, as the user does, and wait for the result."""
    inputs = card(page, column).locator(".filter-range input")
    for field, value in ((inputs.first, low), (inputs.last, high)):
        field.fill(value)
        field.press("Enter")
    settle(page)


def whole_range(page: Page, column: str) -> None:
    """Take a card back to its whole range, and wait for the result."""
    card(page, column).get_by_role("button", name="全範囲").click()
    settle(page)


def hold(page: Page, pattern: str) -> Callable[[], None]:
    """Hold the requests of `pattern` from now on; return the function that releases them, one by one, and every one that comes later.

    `page.unroute` after the release would leave a gap in which a request that
    comes in is held for ever.
    """
    held: list[Route] = []
    state = {"open": False}

    def handler(route: Route) -> None:
        if state["open"]:
            route.continue_()
        else:
            held.append(route)

    page.route(pattern, handler)

    def release() -> None:
        state["open"] = True
        # In the order they were held, each one reaching the server before the
        # next (the server answers 409 to the one it finds older than another
        # it has seen, and a page awaits the answer of its latest request).
        for route in held:
            route.continue_()
            page.wait_for_timeout(300)

    return release


def lock(page: Page) -> None:
    """Press the lock and wait for what it starts."""
    page.locator(LOCK).click()
    wait_idle(page)


def reset_axes(page: Page) -> None:
    """Click Reset axes of the mode bar."""
    page.locator("#plot").hover()
    page.locator('.modebar-btn[data-attr="zoom"][data-val="reset"]').click()


def near(range_: list[float], expected: list[float], tol: float = 0.05) -> bool:
    """Whether two ranges are equal within `tol` of the expected span."""
    span = abs(expected[1] - expected[0]) * tol
    return all(abs(a - b) <= span for a, b in zip(range_, expected, strict=True))


def test_the_lock_sits_in_the_corner_and_toggles(app_page: Page) -> None:
    """Off at first and unusable without a continuous axis, the lock fits the cell left of X and below Y, and toggles by click, Enter and Space."""
    page = app_page
    errors = watch_errors(page)
    button = page.locator(LOCK)
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("aria-pressed", "false")
    expect(button).to_have_attribute("aria-label", "軸範囲を固定")
    # Two categorical axes: nothing to lock.
    place(page, "g", "x")
    place(page, "g", "y")
    expect(button).to_be_disabled()
    # A categorical x and a numeric y in its place: the lock is of y.
    place(page, "y", "y")
    expect(button).to_be_enabled()
    box = button.bounding_box()
    x_zone = page.locator('.zone[data-role="x"]').bounding_box()
    y_zone = page.locator('.zone[data-role="y"]').bounding_box()
    assert (box["width"], box["height"]) == (30, 30)
    assert box["x"] + box["width"] <= x_zone["x"]
    assert box["y"] >= y_zone["y"] + y_zone["height"]
    assert box["x"] >= y_zone["x"] - 0.5
    assert box["y"] <= x_zone["y"] + 0.5
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    expect(button).to_have_attribute("title", "軸範囲の固定を解除して自動調整する")
    button.focus()
    page.keyboard.press("Enter")
    expect(button).to_have_attribute("aria-pressed", "false")
    expect(button).to_have_attribute("title", "軸範囲を固定する")
    page.keyboard.press("Space")
    expect(button).to_have_attribute("aria-pressed", "true")
    wait_idle(page)
    assert errors == []


def test_a_filter_narrows_the_axes_unless_locked(app_page: Page) -> None:
    """Off, a filter narrows both axes to its rows and its removal widens them; locked, the axes stay while the rows change."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    assert near(shown(page, "xaxis"), WHOLE_X)
    add_filter(page, "x")
    set_range(page, "x", "20", "40")
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    assert near(shown(page, "yaxis"), [39.2, 80.8], 0.01)
    expect(page.locator("#status")).to_contain_text("201 行（フィルタ後）")
    whole_range(page, "x")
    assert near(shown(page, "xaxis"), WHOLE_X, 0.01)
    lock(page)
    set_range(page, "x", "20", "40")
    assert near(shown(page, "xaxis"), WHOLE_X, 0.01)
    assert near(shown(page, "yaxis"), [-4.0, 204.0], 0.01)
    expect(page.locator("#status")).to_contain_text("201 行（フィルタ後）")
    # Off again: at once over the automatic ranges of the filter.
    lock(page)
    settle(page)
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    assert errors == []


def test_a_datetime_filter_narrows_its_axis(app_page: Page) -> None:
    """A datetime x filtered to an hour spans that hour, in the data's times."""
    page = app_page
    errors = watch_errors(page)
    place(page, "at", "x")
    place(page, "y", "y")
    add_filter(page, "at")
    set_range(page, "at", "2026-11-01 02:00", "2026-11-01 03:00")
    lo, hi = shown(page, "xaxis")
    first = epoch_ms(START + dt.timedelta(hours=2))
    last = epoch_ms(START + dt.timedelta(hours=3))
    pad = (last - first) * 0.02
    assert lo == pytest.approx(first - pad, abs=1000)
    assert hi == pytest.approx(last + pad, abs=1000)
    expect(page.locator("#status")).to_contain_text("61 行（フィルタ後）")
    # Locked, half the hour keeps the axis over the whole hour.
    lock(page)
    set_range(page, "at", "2026-11-01 02:30", "2026-11-01 03:00")
    assert shown(page, "xaxis") == pytest.approx([lo, hi], abs=1000)
    expect(page.locator("#status")).to_contain_text("31 行（フィルタ後）")
    assert errors == []


def test_an_axis_set_by_hand_keeps_its_range_and_reset_keeps_the_lock(
    app_page: Page,
) -> None:
    """A zoom of y alone keeps y through a filter while x follows it; locked, a zoom still works and Reset axes and a double click go back to the filter's automatic ranges, locked; off drops the zoom."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    add_filter(page, "x")
    zoom_y = [50.0, 60.0]
    with page.expect_request("**/api/view"):
        page.evaluate(f"Plotly.relayout('plot', {{'yaxis.range': {zoom_y}}})")
    settle(page)
    with page.expect_request("**/api/view") as request:
        set_range(page, "x", "20", "40")
    body = request.value.post_data_json
    assert body["x_ranges"] == [None]
    assert body["y_ranges"] == [pytest.approx(zoom_y)]
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    assert shown(page, "yaxis") == pytest.approx(zoom_y)

    lock(page)
    with page.expect_request("**/api/view"):
        page.evaluate("Plotly.relayout('plot', {'xaxis.range': [25, 30]})")
    settle(page)
    assert shown(page, "xaxis") == pytest.approx([25, 30])
    reset_axes(page)
    settle(page)
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    assert near(shown(page, "yaxis"), [39.2, 80.8], 0.01)
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "true")
    # Locked, the ranges gone back to stay through the next filter.
    set_range(page, "x", "30", "40")
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    # A double click on the plot area goes back to the latest filter's.
    with page.expect_request("**/api/view"):
        page.evaluate("Plotly.relayout('plot', {'yaxis.range': [70, 75]})")
    settle(page)
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    settle(page)
    assert near(shown(page, "xaxis"), [29.8, 40.2], 0.01)
    assert near(shown(page, "yaxis"), [59.6, 80.4], 0.01)
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "true")

    # Off drops every range kept: a zoom, then off, then a filter.
    with page.expect_request("**/api/view"):
        page.evaluate("Plotly.relayout('plot', {'yaxis.range': [70, 75]})")
    settle(page)
    lock(page)
    settle(page)
    assert near(shown(page, "yaxis"), [59.6, 80.4], 0.01)
    set_range(page, "x", "20", "40")
    assert near(shown(page, "yaxis"), [39.2, 80.8], 0.01)
    assert errors == []


# Records the x range of every draw of the figure, for a test to tell that
# the axes never went through a range.
RECORD_RANGES = """() => {
  window.xRanges = [];
  const gd = document.getElementById("plot");
  const record = () => {
    const a = gd._fullLayout?.xaxis;
    if (a) window.xRanges.push(a.range.map((v) => a.r2l(v)));
  };
  gd.on("plotly_afterplot", record);
  gd.on("plotly_relayout", record);
}"""


def test_reset_after_a_filter_while_zoomed_goes_straight_to_its_ranges(
    app_page: Page,
) -> None:
    """Zoomed, a filter narrows nothing; Reset axes then shows the old overview faded over the filter's automatic ranges until the new one replaces it, never over the old ranges."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    add_filter(page, "x")
    with page.expect_request("**/api/view"):
        page.evaluate(
            "Plotly.relayout('plot', {'xaxis.range': [10, 50], 'yaxis.range': [20, 100]})"
        )
    settle(page)
    set_range(page, "x", "20", "40")
    assert shown(page, "xaxis") == pytest.approx([10, 50])
    held: list[Route] = []
    page.route("**/api/overview", lambda route: held.append(route))
    page.evaluate(RECORD_RANGES)
    task = page.locator("#status").get_attribute("data-task")
    reset_axes(page)
    page.wait_for_function(
        "() => document.getElementById('plot').classList.contains('pending')"
    )
    assert held
    # The old overview stands in, faded, over the filter's automatic ranges.
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    opacity = page.evaluate(
        "() => getComputedStyle(document.querySelector('canvas.image-layers')).opacity"
    )
    assert float(opacity) < 1
    held[0].continue_()
    page.unroute("**/api/overview")
    expect(page.locator("#status")).not_to_have_attribute("data-task", task)
    settle(page)
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    ranges = page.evaluate("window.xRanges")
    assert ranges
    assert not any(near(r, WHOLE_X, 0.01) for r in ranges)
    assert errors == []


def test_reset_waits_while_the_ranges_of_the_filter_are_not_known(
    app_page: Page,
) -> None:
    """Reset axes while the view of a new filter is held keeps the drawn axes until the overview of the filter comes."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    add_filter(page, "x")
    with page.expect_request("**/api/view"):
        page.evaluate("Plotly.relayout('plot', {'xaxis.range': [10, 50]})")
    settle(page)
    release = hold(page, "**/api/view")
    inputs = card(page, "x").locator(".filter-range input")
    inputs.first.fill("20")
    inputs.first.press("Enter")
    inputs.last.fill("40")
    inputs.last.press("Enter")
    page.wait_for_function(
        "() => document.getElementById('plot').classList.contains('busy')"
    )
    page.evaluate(RECORD_RANGES)
    with page.expect_response("**/api/overview"):
        reset_axes(page)
        # Meanwhile the axes stay as they are.
        assert shown(page, "xaxis") == pytest.approx([10, 50])
    settle(page)
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    ranges = page.evaluate("window.xRanges")
    assert not any(near(r, WHOLE_X, 0.01) for r in ranges)
    release()
    settle(page)
    assert near(shown(page, "xaxis"), NARROW_X, 0.01)
    assert errors == []


def test_the_lock_keeps_the_ranges_through_edits(app_page: Page) -> None:
    """Locked, a whole x and a reversed y keep their ranges through Color, a filter and a second Y; the new Y and an axis put on a log scale take their automatic ranges."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    _reverse(page, "y", "Y 軸: y")
    add_filter(page, "x")
    lock(page)
    set_range(page, "x", "20", "40")
    assert near(shown(page, "xaxis"), WHOLE_X, 0.01)
    # Reversed: plotly's order is descending.
    assert near(shown(page, "yaxis"), [204.0, -4.0], 0.01)
    place(page, "g", "color")
    settle(page)
    assert near(shown(page, "xaxis"), WHOLE_X, 0.01)
    assert near(shown(page, "yaxis"), [204.0, -4.0], 0.01)
    # x on a log axis: its own axis takes the filter's exponents.
    _right_click_tick(page, "x")
    page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    page.wait_for_function(
        "() => document.getElementById('plot')._fullLayout.xaxis.type === 'log'"
    )
    settle(page)
    lo, hi = page.evaluate("document.getElementById('plot')._fullLayout.xaxis.range")
    assert lo == pytest.approx(1.295, abs=0.005)
    assert hi == pytest.approx(1.608, abs=0.005)
    assert near(shown(page, "yaxis"), [204.0, -4.0], 0.01)
    # A second Y: the new axis spans the filter's rows; the others stay.
    add_second_y(page, "x")
    settle(page)
    assert page.evaluate("document.getElementById('plot')._fullLayout.xaxis.range") == [
        pytest.approx(lo),
        pytest.approx(hi),
    ]
    assert near(shown(page, "yaxis"), [204.0, -4.0], 0.01)
    assert near(shown(page, "yaxis2"), NARROW_X, 0.01)
    x_range = page.evaluate("document.getElementById('plot')._fullLayout.xaxis.range")
    # An element of the graph and a wrap keep them too.
    page.locator('#elements .element[data-element="smooth"]').click()
    settle(page)
    assert near(shown(page, "yaxis"), [204.0, -4.0], 0.01)
    assert near(shown(page, "yaxis2"), NARROW_X, 0.01)
    page.locator("#columns .column").filter(
        has=page.get_by_text("g", exact=True)
    ).drag_to(page.locator('.zone[data-role="wrap"]'))
    settle(page)
    assert page.evaluate("document.getElementById('plot')._fullLayout.xaxis.range") == [
        pytest.approx(r) for r in x_range
    ]
    assert near(shown(page, "yaxis"), [204.0, -4.0], 0.01)
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "true")
    assert errors == []


def test_the_lock_leaves_a_categorical_axis_alone(app_page: Page) -> None:
    """Beside a categorical x, the lock keeps the numeric y through a filter, and off it narrows; x keeps its bands."""
    page = app_page
    errors = watch_errors(page)
    place(page, "g", "x")
    place(page, "y", "y")
    bands = shown(page, "xaxis")
    add_filter(page, "y")
    lock(page)
    set_range(page, "y", "100", "200")
    assert near(shown(page, "yaxis"), [-4.0, 204.0], 0.01)
    assert shown(page, "xaxis") == pytest.approx(bands)
    lock(page)
    settle(page)
    assert near(shown(page, "yaxis"), [98.0, 202.0], 0.01)
    assert shown(page, "xaxis") == pytest.approx(bands)
    assert errors == []


def test_the_latest_operation_wins_and_a_failure_restores(app_page: Page) -> None:
    """With the answers held, a filter, then a pan: the pan's range and the filter win; the lock turned off over a failing overview goes back on, with the axes as they were."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    add_filter(page, "x")
    release = hold(page, "**/api/*view")
    inputs = card(page, "x").locator(".filter-range input")
    inputs.first.fill("20")
    inputs.first.press("Enter")
    page.wait_for_function(
        "() => document.getElementById('plot').classList.contains('busy')"
    )
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [30, 35]})")
    page.wait_for_timeout(300)
    release()
    settle(page)
    assert shown(page, "xaxis") == pytest.approx([30, 35])
    expect(page.locator("#status")).to_contain_text("（フィルタ後）")
    # Locked over the pan, then off over an overview that fails.
    lock(page)
    page.route(
        "**/api/overview",
        lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({"detail": "boom"}),
        ),
    )
    page.locator(LOCK).click()
    expect(page.locator("#status")).to_contain_text("boom")
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "true")
    assert shown(page, "xaxis") == pytest.approx([30, 35])
    page.unroute("**/api/overview")
    assert errors == []


@pytest.mark.parametrize("zoomed", [False, True])
def test_the_lock_turned_on_while_waiting_keeps_the_ranges_shown(
    app_page: Page, zoomed: bool
) -> None:
    """Locked while the overview (or a view with an automatic axis) of a new filter is held, the axes keep the ranges shown then, under the new filter."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    add_filter(page, "x")
    if zoomed:
        # y set by hand: the filter asks for a view with x automatic.
        with page.expect_request("**/api/view"):
            page.evaluate("Plotly.relayout('plot', {'yaxis.range': [50, 60]})")
        settle(page)
    before = {key: shown(page, key) for key in ("xaxis", "yaxis")}
    release = hold(page, "**/api/*view")
    inputs = card(page, "x").locator(".filter-range input")
    inputs.first.fill("20")
    inputs.first.press("Enter")
    page.wait_for_function(
        "() => document.getElementById('plot').classList.contains('busy')"
    )
    page.locator(LOCK).click()
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(200)
    release()
    settle(page)
    for key, range_ in before.items():
        assert shown(page, key) == pytest.approx(range_)
    expect(page.locator("#status")).to_contain_text("（フィルタ後）")
    assert errors == []


def test_the_lock_turned_off_keeps_a_categorical_zoom(app_page: Page) -> None:
    """Off, the continuous axes go back to their automatic ranges, and a categorical axis zoomed keeps its range."""
    page = app_page
    errors = watch_errors(page)
    place(page, "g", "x")
    place(page, "y", "y")
    with page.expect_request("**/api/view"):
        page.evaluate(
            "Plotly.relayout('plot', {'xaxis.range': [-0.2, 0.2], 'yaxis.range': [50, 60]})"
        )
    settle(page)
    lock(page)
    lock(page)
    settle(page)
    assert shown(page, "xaxis") == pytest.approx([-0.2, 0.2])
    assert near(shown(page, "yaxis"), [-4.0, 204.0], 0.01)
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "false")
    assert errors == []


def test_the_lock_turned_off_during_an_edit_keeps_a_categorical_zoom(
    app_page: Page,
) -> None:
    """Off while an edit's plot is held, the categorical zoom stays, then and once the edit is drawn; the numeric axis takes its automatic range."""
    page = app_page
    errors = watch_errors(page)
    place(page, "g", "x")
    place(page, "y", "y")
    with page.expect_request("**/api/view"):
        page.evaluate(
            "Plotly.relayout('plot', {'xaxis.range': [-0.2, 0.2], 'yaxis.range': [50, 60]})"
        )
    settle(page)
    lock(page)
    release = hold(page, "**/api/plot")
    page.locator("#columns .column").filter(
        has=page.get_by_text("g", exact=True)
    ).drag_to(page.locator('.zone[data-role="color"]'))
    page.wait_for_function(
        "() => document.getElementById('plot').classList.contains('busy')"
    )
    page.locator(LOCK).click()
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "false")
    assert shown(page, "xaxis") == pytest.approx([-0.2, 0.2])
    assert near(shown(page, "yaxis"), [-4.0, 204.0], 0.01)
    release()
    settle(page)
    assert shown(page, "xaxis") == pytest.approx([-0.2, 0.2])
    assert near(shown(page, "yaxis"), [-4.0, 204.0], 0.01)
    assert errors == []
