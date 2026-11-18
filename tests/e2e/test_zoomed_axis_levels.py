"""E2E: a categorical x zoomed by hand takes its automatic range when a filter changes its levels, and keeps its range otherwise, in any order of the answers (Issue #280)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_color_levels import (
    HOLD_TEXT,
    LEGEND_NAMES,
    add_filter,
    box,
    card,
    scatter_path,  # noqa: F401  (g of 150 levels, half, x 0 to 2999)
    settle,
    tick,
    toasts_let_drops_through,  # noqa: F401
    zoom,
)
from tests.e2e.test_column_menu import pick
from tests.e2e.test_kept_ranges import shown
from tests.e2e.test_scatter import SETTLED, place, wait_idle, watch_errors

pytestmark = pytest.mark.e2e

# The bands of g1 to g150, and of the 50 levels of the rows x <= 49.
EVERY = [-0.5, 149.5]
FIFTY = [-0.5, 49.5]


def g_over_y(page: Page) -> None:
    """Draw g on x over y, with the lock off."""
    expect(page.locator("#columns .column").filter(has_text="half")).to_be_visible()
    place(page, "g", "x")
    place(page, "y", "y")


def x_filter(page: Page) -> Locator:
    """Add x to the filter pane and return the inputs of its range."""
    pick(page, "x", "Add to Local filter")
    inputs = card(page, "x").locator(".filter-range input")
    expect(inputs.first).to_be_visible()
    return inputs


def enter(field: Locator, value: str, path: str) -> None:
    """Type a bound of a range filter and wait for the answer it asks for."""
    with field.page.expect_response(path) as answered:
        field.fill(value)
        field.press("Enter")
    assert answered.value.ok, answered.value.text()


def edit_color(page: Page) -> None:
    """Put v on Color (an edit of the graph) and wait for what it draws."""
    with page.expect_response("**/api/plot"):
        place(page, "v", "color")
    page.wait_for_function(SETTLED)
    wait_idle(page)


def test_a_filter_that_changes_the_levels_takes_the_automatic_range(
    app_page: Page,
) -> None:
    """A filter that leaves g1 to g80 spans their bands; one that keeps every level keeps the zoom."""
    page = app_page
    errors = watch_errors(page)
    g_over_y(page)
    zoom(page, 0, 3)
    add_filter(page, "half")
    tick(page, "half", ["lo"], "**/api/view")
    settle(page)
    assert shown(page, "xaxis") == pytest.approx([-0.5, 79.5])
    assert errors == []


def test_a_filter_that_keeps_the_levels_keeps_the_zoom(app_page: Page) -> None:
    """A numeric filter that leaves every level of g keeps the zoom of x."""
    page = app_page
    errors = watch_errors(page)
    g_over_y(page)
    inputs = x_filter(page)
    zoom(page, 0, 3)
    enter(inputs.last, "2000", "**/api/view")
    page.wait_for_function(SETTLED)
    settle(page)
    assert shown(page, "xaxis") == pytest.approx([0, 3])
    assert errors == []


def refused_with_colors(page: Page) -> None:
    """Draw g on x and on Color under half = lo, and zoom x."""
    g_over_y(page)
    add_filter(page, "half")
    tick(page, "half", ["lo"])
    place(page, "g", "color")
    expect(page.locator(LEGEND_NAMES)).to_have_count(80)
    zoom(page, 0, 3)


def test_a_refused_filter_keeps_the_zoom(app_page: Page) -> None:
    """A filter refused for its color levels keeps the zoom of x, and so does an edit of the graph after it."""
    page = app_page
    errors = watch_errors(page)
    refused_with_colors(page)
    with page.expect_response("**/api/view") as refused:
        box(page, "half", "hi").check()
    assert refused.value.json()["error"] == "filtered_levels"
    settle(page)
    expect(box(page, "half", "hi")).not_to_be_checked()
    assert shown(page, "xaxis") == pytest.approx([0, 3])
    edit_color(page)
    assert shown(page, "xaxis") == pytest.approx([0, 3])
    assert errors == []


def test_refusals_one_after_another_keep_the_zoom(app_page: Page) -> None:
    """A second filter refused while the text of the first refusal is held keeps the zoom of x."""
    page = app_page
    errors = watch_errors(page)
    refused_with_colors(page)
    page.evaluate(HOLD_TEXT, "/api/view")
    with page.expect_response("**/api/view") as first:
        box(page, "half", "hi").check()
    assert first.value.status == 400
    page.wait_for_function("() => Boolean(window.releaseText)")
    with page.expect_response("**/api/view") as second:
        card(page, "half").locator(".filter-card-remove").click()
    assert second.value.status == 400
    page.evaluate("() => window.releaseText()")
    settle(page)
    expect(box(page, "half", "hi")).not_to_be_checked()
    assert shown(page, "xaxis") == pytest.approx([0, 3])
    edit_color(page)
    assert shown(page, "xaxis") == pytest.approx([0, 3])
    assert errors == []


def test_an_edit_drawn_before_a_new_filter_takes_its_levels(app_page: Page) -> None:
    """An edit of the graph drawn while the result of a filter that changes the levels is held spans the bands of that filter."""
    page = app_page
    errors = watch_errors(page)
    g_over_y(page)
    inputs = x_filter(page)
    zoom(page, 0, 3)
    page.evaluate(HOLD_TEXT, "/api/view")
    enter(inputs.last, "49", "**/api/view")
    page.wait_for_function("() => Boolean(window.releaseText)")
    edit_color(page)
    page.evaluate("() => window.releaseText()")
    settle(page)
    page.wait_for_function(SETTLED)
    assert shown(page, "xaxis") == pytest.approx(FIFTY)
    # The view the edit superseded lost its images to the edit's result.
    assert [e for e in errors if ": 404" not in e] == []


def test_a_zoom_under_a_new_filter_survives_an_edit(app_page: Page) -> None:
    """X zoomed under a filter drawn as a view, the overview still of the old filter, keeps its range through an edit of the graph."""
    page = app_page
    errors = watch_errors(page)
    g_over_y(page)
    inputs = x_filter(page)
    # y set by hand keeps the overview of the old filter: the new one is a view.
    with page.expect_response("**/api/view"):
        page.evaluate("Plotly.relayout('plot', {'yaxis.range': [0, 3]})")
    page.wait_for_function(SETTLED)
    enter(inputs.last, "49", "**/api/view")
    page.wait_for_function(SETTLED)
    settle(page)
    assert shown(page, "xaxis") == pytest.approx(FIFTY)
    zoom(page, 0, 3)
    edit_color(page)
    assert shown(page, "xaxis") == pytest.approx([0, 3])
    assert errors == []


def test_an_edit_back_to_an_old_filter_keeps_no_range_of_another(
    app_page: Page,
) -> None:
    """Back to the filter x was first zoomed under, an edit drawn before that filter's result keeps no range zoomed under the other filter."""
    page = app_page
    errors = watch_errors(page)
    g_over_y(page)
    inputs = x_filter(page)
    high = inputs.last.input_value()
    zoom(page, 0, 3)
    enter(inputs.last, "49", "**/api/view")
    page.wait_for_function(SETTLED)
    settle(page)
    assert shown(page, "xaxis") == pytest.approx(FIFTY)
    zoom(page, 10, 20)
    page.evaluate(HOLD_TEXT, "/api/view")
    enter(inputs.last, high, "**/api/view")
    page.wait_for_function("() => Boolean(window.releaseText)")
    edit_color(page)
    page.evaluate("() => window.releaseText()")
    settle(page)
    page.wait_for_function(SETTLED)
    assert shown(page, "xaxis") == pytest.approx(EVERY)
    # The view the edit superseded lost its images to the edit's result.
    assert [e for e in errors if ": 404" not in e] == []
