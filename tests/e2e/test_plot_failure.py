"""E2E: a drop whose plot fails keeps the drawn graph, its figure and its selection (Issue #101)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import APIResponse, Page, Route, expect

from tests.e2e.test_scatter import PAINTED_PIXEL, SETTLED, placed_names, watch_errors

pytestmark = pytest.mark.e2e

# Levels of the categorical month column: more than Color's limit of 100
# (`plot.max_levels`), within that of X and Y (`plot.max_axis_levels`).
MONTHS = 420


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write a numeric period, a month of 420 levels, two numeric and two categorical columns."""
    rng = np.random.default_rng(0)
    n = 4 * MONTHS
    period = np.arange(n) % MONTHS
    frame = pl.DataFrame(
        {
            "period": period,
            "month": [f"m{p:03d}" for p in period],
            "y": rng.normal(0, 1, n),
            "z": rng.normal(0, 1, n),
            "color": rng.choice(["a", "b", "c"], n),
            "facet": rng.choice(["p", "q"], n),
        }
    )
    path = tmp_path / "periods.parquet"
    frame.write_parquet(path)
    return path


@pytest.fixture(autouse=True)
def toasts_let_drops_through(app_page: Page) -> None:
    """Let the pointer through the error toasts (`test_notice.py` tests them).

    Each failure opens one at the top right, over the zones there: a drag
    onto them would wait for it to close.
    """
    app_page.add_style_tag(content="#toasts, #toasts * { pointer-events: none !important; }")


LAYOUT = "() => JSON.stringify(document.getElementById('plot').layout)"
# The element icons: name, pressed, and whether they can be pressed.
ELEMENTS = """() => [...document.querySelectorAll('#elements .element')].map(
  (b) => [b.dataset.element, b.getAttribute('aria-pressed'), b.disabled])"""
X_RANGE = "() => document.getElementById('plot')._fullLayout.xaxis.range.slice()"
# plotly's boxes of the selection: their axes and their bounds, ascending.
SELECTIONS = """() => (document.getElementById('plot').layout.selections ?? []).map(
  (s) => [s.xref, s.yref, [s.x0, s.x1].sort((a, b) => a - b), [s.y0, s.y1].sort((a, b) => a - b)])"""


def zone(page: Page, role: str):  # noqa: ANN201 - a playwright Locator
    """Return a role's drop zone."""
    return page.locator(f'.zone[data-role="{role}"]')


def drop(page: Page, column: str, role: str, at: float | None = None) -> None:
    """Drag a column of the list onto a role's zone, at a share `at` along an axis zone.

    It does not wait for the chip: a failed plot takes it back.
    """
    source = page.locator("#columns .column").filter(has=page.get_by_text(column, exact=True))
    target = zone(page, role)
    if at is None:
        source.drag_to(target)
        return
    box = target.bounding_box()
    assert box is not None
    position = (
        {"x": box["width"] * at, "y": box["height"] / 2}
        if role == "x"
        else {"x": box["width"] / 2, "y": box["height"] * at}
    )
    source.drag_to(target, target_position=position)


def move(page: Page, role: str, target: str) -> None:
    """Drag the first chip of a role onto another zone, or the column list (`#columns`)."""
    chip = zone(page, role).locator(".chip").first
    chip.drag_to(page.locator("#columns") if target == "#columns" else zone(page, target))


def draw(page: Page, column: str, role: str) -> None:
    """Drop a column on a role's zone and wait for its plot."""
    drop(page, column, role)
    expect(zone(page, role).locator(".chip-name")).to_contain_text([column])
    page.wait_for_function(SETTLED)


def plot_bodies(page: Page) -> list[dict]:
    """Collect the bodies of the plot requests from now on."""
    bodies: list[dict] = []
    page.on(
        "request",
        lambda r: bodies.append(r.post_data_json) if r.url.endswith("/api/plot") else None,
    )
    return bodies


def failing(page: Page) -> list[int]:
    """Fail every plot request from now on, numbering its error; return the count."""
    count: list[int] = []

    def fail(route: Route) -> None:
        count.append(1)
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({"detail": f"集約に失敗した {len(count)}"}),
        )

    page.route("**/api/plot", fail)
    return count


def start(page: Page) -> None:
    """Draw period on X and y on Y."""
    expect(page.locator("#columns .column").filter(has_text="month")).to_be_visible()
    drop(page, "period", "x")
    draw(page, "y", "y")


def test_a_refused_level_limit_keeps_the_plot_and_can_be_tried_again(app_page: Page) -> None:
    """Month (420 levels) on Color hits the real limit: the empty Color, the figure and the next request stay as they were, and the same drop can be tried again."""
    page = app_page
    errors = watch_errors(page)
    start(page)
    bodies = plot_bodies(page)
    layout = page.evaluate(LAYOUT)
    before = placed_names(page)
    status = page.locator("#status")

    for attempt in range(2):
        with page.expect_response("**/api/plot") as response:
            drop(page, "month", "color")
        assert not response.value.ok
        assert bodies[-1]["encoding"]["color"] == "month"
        assert len(bodies) == attempt + 1
        expect(status).to_contain_text("上限")
        expect(status).to_have_class("notice-error")
        expect(zone(page, "color").locator(".chip-name")).to_have_count(0)
        assert placed_names(page) == before
        assert page.evaluate(LAYOUT) == layout
    # The same error again replaces its toast.
    expect(page.locator("#toasts .toast")).to_have_count(1)

    with page.expect_response("**/api/plot") as response:
        drop(page, "color", "color")
    assert response.value.ok
    assert bodies[-1]["encoding"]["color"] == "color"
    assert bodies[-1]["encoding"]["x"] == ["period"]
    page.wait_for_function(SETTLED)
    expect(status).not_to_have_class("notice-error")
    assert errors == []


def test_a_failed_drop_on_any_role_comes_back_whole(app_page: Page) -> None:
    """A failed plot takes back the whole drop: an n-th axis, a replacement, a move, a swap, the facets Wrap removes, a removal and the elements turned off."""
    page = app_page
    errors = watch_errors(page)
    start(page)
    draw(page, "facet", "col")
    draw(page, "color", "color")
    page.locator('#elements .element[data-element="smooth"]').click()
    page.wait_for_function(SETTLED)
    status = page.locator("#status")
    layout = page.evaluate(LAYOUT)
    before = placed_names(page)
    elements = page.evaluate(ELEMENTS)
    assert ["smooth", "true", False] in elements

    count = failing(page)
    edits: list[Callable[[], None]] = [
        lambda: drop(page, "z", "y", at=0.9),  # a second Y axis
        lambda: drop(page, "z", "x", at=0.1),  # a second X axis, before the first
        lambda: drop(page, "month", "x"),  # a categorical X turns the smoothing lines off
        lambda: drop(page, "z", "color"),
        lambda: move(page, "color", "symbol"),
        lambda: move(page, "x", "y"),  # X and Y swap
        lambda: drop(page, "month", "wrap"),  # Wrap removes Group X
        lambda: move(page, "col", "row"),
        lambda: move(page, "col", "#columns"),  # removed, still drawable
    ]
    for i, edit in enumerate(edits, 1):
        edit()
        expect(status).to_have_text(f"エラー: 集約に失敗した {i}")
        assert placed_names(page) == before, i
        assert page.evaluate(ELEMENTS) == elements, i
        assert page.evaluate(LAYOUT) == layout, i
    assert len(count) == len(edits)

    # A plot that succeeds commits its drop: the next failure comes back to it.
    page.unroute("**/api/plot")
    draw(page, "z", "color")
    expect(status).not_to_have_class("notice-error")
    committed = placed_names(page)
    assert committed["color"] == ["z"]
    failing(page)
    move(page, "col", "row")
    expect(status).to_have_text("エラー: 集約に失敗した 1")
    assert placed_names(page) == committed
    assert errors == []


def test_first_network_image_failures_and_a_removal(app_page: Page) -> None:
    """A failed first plot leaves no figure; a lost request and images that do not come keep the figure; a removal that leaves nothing to draw is no failure."""
    page = app_page
    errors = watch_errors(page)
    status = page.locator("#status")
    expect(page.locator("#columns .column").filter(has_text="month")).to_be_visible()
    drop(page, "period", "x")

    # The first plot fails: back to the half-built graph and no figure.
    page.route("**/api/plot", lambda route: route.abort())
    drop(page, "y", "y")
    expect(status).to_contain_text("描画の要求に失敗した")
    expect(zone(page, "y").locator(".chip")).to_have_count(0)
    expect(zone(page, "x").locator(".chip-name")).to_have_text(["period"])
    expect(page.locator("#empty")).to_be_visible()
    page.unroute("**/api/plot")
    draw(page, "y", "y")
    expect(status).not_to_have_class("notice-error")

    # The answer is lost after the server took the plot: the drawn graph is
    # plotted again, so that the server's results are its; the error stays.
    layout = page.evaluate(LAYOUT)
    before = placed_names(page)
    bodies = plot_bodies(page)
    lost: list[int] = []

    def lose(route: Route) -> None:
        if lost:
            route.continue_()
            return
        lost.append(1)
        route.fetch()
        route.abort()

    page.route("**/api/plot", lose)
    with page.expect_response(
        lambda r: r.url.endswith("/api/plot") and r.request.post_data_json["encoding"]["color"] is None
    ) as restored:
        drop(page, "color", "color")
    assert restored.value.ok
    expect(status).to_contain_text("描画の要求に失敗した")
    assert placed_names(page) == before
    page.wait_for_function(PAINTED_PIXEL)
    assert page.evaluate(LAYOUT) == layout
    expect(status).to_contain_text("描画の要求に失敗した")
    # The server's overview is the drawn graph's again.
    overview = page.evaluate(
        """async () => (await (await fetch('/api/overview', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({width: 300, height: 200, filters: []})})).json()).meta.color.column"""
    )
    assert overview is None
    assert [b["encoding"]["color"] for b in bodies] == ["color", None]
    page.unroute("**/api/plot")

    # The images of the new figure do not come: the server's results are the
    # new graph's, so the drawn graph is plotted again; its error stays.
    bodies = plot_bodies(page)
    failed_task: list[str] = []

    def images(route: Route) -> None:
        if not failed_task:
            failed_task.append(route.request.url.rsplit("/", 1)[1].split("?")[0])
            route.fulfill(status=500, body="gone")
        else:
            route.continue_()

    page.route("**/api/images/*", images)
    drop(page, "color", "color")
    expect(status).to_contain_text("図の画像を読み込めなかった")
    assert placed_names(page) == before
    page.wait_for_function(PAINTED_PIXEL)
    assert [b["encoding"]["color"] for b in bodies] == ["color", None]
    expect(status).to_contain_text("図の画像を読み込めなかった")
    page.unroute("**/api/images/*")

    # Removing Y leaves nothing to draw: the figure goes, with no error.
    zone(page, "y").locator(".chip-remove").click()
    expect(page.locator("#empty")).to_be_visible()
    expect(zone(page, "y").locator(".chip")).to_have_count(0)
    expect(status).not_to_have_class("notice-error")
    # The page logs only the failures this test made: the lost requests and the images.
    assert [e.splitlines()[0] for e in errors] == [
        "TypeError: Failed to fetch",
        "TypeError: Failed to fetch",
        f"Error: images of task {failed_task[0]}: 500",
    ]


def test_a_failure_keeps_the_zoom_and_the_selection(app_page: Page) -> None:
    """A zoomed view with a box selected stays as it was after a failed drop; zooming, saving and filtering then work on it."""
    page = app_page
    errors = watch_errors(page)
    status = page.locator("#status")
    start(page)
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [100, 300]})")
    expect(status).to_contain_text("表示範囲")
    page.wait_for_function(SETTLED)
    page.evaluate("Plotly.relayout('plot', {dragmode: 'select'})")
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    assert box is not None
    with page.expect_response("**/api/selection") as selected:
        page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.8, steps=5)
        page.mouse.up()
    rows = selected.value.json()["rows"]
    table = page.locator("#table")
    expect(table).to_be_visible()
    expect(status).to_contain_text("選んだ行")
    shown = page.evaluate(X_RANGE)
    selections = page.evaluate(SELECTIONS)
    layout = page.evaluate(LAYOUT)
    before = placed_names(page)

    failing(page)
    drop(page, "color", "color")
    expect(status).to_have_text("エラー: 集約に失敗した 1")
    assert placed_names(page) == before
    assert page.evaluate(X_RANGE) == shown
    assert page.evaluate(SELECTIONS) == selections
    assert page.evaluate(LAYOUT) == layout
    expect(table).to_be_visible()
    expect(table).to_contain_text(f"{rows:,}")
    page.unroute("**/api/plot")

    # The images of the new figure do not come: the server's results are the
    # new graph's, so the drawn graph is plotted again at the same view, with
    # the same box selecting the same rows.
    failed: list[int] = []

    def images(route: Route) -> None:
        if failed:
            route.continue_()
        else:
            failed.append(1)
            route.fulfill(status=500, body="gone")

    page.route("**/api/images/*", images)
    with page.expect_response("**/api/selection") as reselected:
        drop(page, "color", "color")
    assert reselected.value.json()["rows"] == rows
    expect(status).to_contain_text("図の画像を読み込めなかった")
    assert placed_names(page) == before
    assert page.evaluate(X_RANGE) == pytest.approx(shown)
    assert page.evaluate(SELECTIONS) == selections
    expect(table).to_be_visible()
    expect(table).to_contain_text(f"{rows:,}")
    page.unroute("**/api/images/*")

    # A zoom aggregates the view of the drawn plot, with its selection.
    with page.expect_response("**/api/view") as view:
        page.evaluate("Plotly.relayout('plot', {'xaxis.range': [150, 250]})")
    assert view.value.ok
    with page.expect_response("**/api/selection") as again:
        page.wait_for_function(SETTLED)
    assert again.value.ok
    assert again.value.request.post_data_json == {"task": view.value.json()["meta"]["task"]}

    # The plot's data is the drawn overview's.
    page.locator('#plot .modebar-btn[data-title^="データを保存"]').click()
    with page.expect_download() as download:
        page.locator(".data-menu").get_by_role("button", name="CSV").click()
    assert pl.read_csv(download.value.path()).columns[0] == "index"

    # A filter narrows the drawn view.
    page.locator("#columns .column").filter(has=page.get_by_text("color", exact=True)).drag_to(
        page.locator("#filters")
    )
    level = page.locator(".filter-level").filter(has=page.get_by_text("a", exact=True))
    with page.expect_response("**/api/view") as filtered:
        level.locator("input").check()
    assert filtered.value.ok
    expect(status).to_contain_text("（フィルタ後）")
    # The page logs only the images this test failed.
    assert [e.splitlines()[0].split(" of task")[0] for e in errors] == ["Error: images"]


def hold_first(page: Page, answer: Callable[[Route, int], None]) -> list[Route]:
    """Hold the first plot request; pass each later one to `answer` with its number (from 2)."""
    held: list[Route] = []
    count: list[int] = []

    def handle(route: Route) -> None:
        count.append(1)
        if len(count) == 1:
            held.append(route)
        else:
            answer(route, len(count))

    page.route("**/api/plot", handle)
    return held


def fail_with(route: Route, text: str, status: int = 500) -> None:
    """Answer a plot request with an error."""
    route.fulfill(status=status, content_type="application/json", body=json.dumps({"detail": text}))


def settle(page: Page) -> None:
    """Let the page handle the answers given so far."""
    page.evaluate("() => new Promise((resolve) => setTimeout(resolve, 300))")


def test_an_older_answer_does_not_undo_a_newer_drop(app_page: Page) -> None:
    """An older failure or cancel after a newer success changes nothing; the newer success commits both drops."""
    page = app_page
    errors = watch_errors(page)
    status = page.locator("#status")
    start(page)
    for answer in [
        lambda route: fail_with(route, "古い失敗"),
        lambda route: route.fulfill(status=409, content_type="application/json", body='{"cancelled": true}'),
    ]:
        held = hold_first(page, lambda route, _: route.continue_())
        drop(page, "color", "color")
        page.wait_for_function("() => document.querySelector('#status').textContent.includes('集約中')")
        drop(page, "facet", "col")
        page.wait_for_function(SETTLED)
        answer(held[0])
        settle(page)
        expect(page.locator("#toasts .toast")).to_have_count(0)
        expect(status).not_to_have_class("notice-error")
        names = placed_names(page)
        assert names["color"] == ["color"]
        assert names["col"] == ["facet"]
        page.unroute("**/api/plot")
        # Back to the graph before, for the next answer.
        move(page, "col", "#columns")
        move(page, "color", "#columns")
        page.wait_for_function(SETTLED)
    assert errors == []


def test_a_newer_failure_goes_back_to_the_last_committed_graph(app_page: Page) -> None:
    """Failures in a row go back to the graph last drawn, with the newest error alone; an older plot the server finished meanwhile is plotted over by the drawn graph again."""
    page = app_page
    errors = watch_errors(page)
    status = page.locator("#status")
    start(page)
    before = placed_names(page)
    toasts = page.locator("#toasts .toast")

    # Two failures: the newer one tells; the older one changes nothing.
    held = hold_first(page, lambda route, _: fail_with(route, "新しい失敗"))
    drop(page, "color", "color")
    page.wait_for_function("() => document.querySelector('#status').textContent.includes('集約中')")
    drop(page, "facet", "col")
    expect(status).to_have_text("エラー: 新しい失敗")
    assert placed_names(page) == before
    fail_with(held[0], "古い失敗")
    settle(page)
    expect(toasts).to_have_text(["エラー: 新しい失敗×"])
    assert placed_names(page) == before
    page.unroute("**/api/plot")
    # The pointer passes through the toasts (`toasts_let_drops_through`).
    toasts.get_by_role("button", name="閉じる").dispatch_event("click")

    # The older plot succeeds on the server before the newer one fails: the
    # drawn graph is plotted again, and the error stays.
    bodies = plot_bodies(page)
    answers: list[APIResponse] = []

    def handle(route: Route) -> None:
        if not answers:
            answers.append(route.fetch())
            held.append(route)
        elif len(bodies) == 2:
            fail_with(route, "新しい失敗")
        else:
            route.continue_()

    held.clear()
    page.route("**/api/plot", handle)
    drop(page, "color", "color")
    for _ in range(100):
        if answers:
            break
        page.wait_for_timeout(100)
    assert len(answers) == 1
    drop(page, "facet", "col")
    expect(status).to_have_text("エラー: 新しい失敗")
    assert placed_names(page) == before
    # The drawn graph again: no color and no Group X.
    with page.expect_response(
        lambda r: r.url.endswith("/api/plot")
        and r.request.post_data_json["encoding"]["color"] is None
    ) as restored:
        held[0].fulfill(response=answers[0])
    assert restored.value.ok
    assert bodies[-1]["encoding"]["color"] is None
    assert bodies[-1]["encoding"]["col"] is None
    page.wait_for_function(PAINTED_PIXEL)
    settle(page)
    expect(status).to_have_text("エラー: 新しい失敗")
    assert placed_names(page) == before
    page.unroute("**/api/plot")
    assert errors == []


def test_a_conversion_retries_without_a_failure(app_page: Page) -> None:
    """A plot refused while columns convert (409) is asked again: no error, no rollback."""
    page = app_page
    errors = watch_errors(page)
    start(page)
    refused: list[int] = []

    def handle(route: Route) -> None:
        if len(refused) < 2:
            refused.append(1)
            fail_with(route, "converting", status=409)
        else:
            route.continue_()

    page.route("**/api/plot", handle)
    drop(page, "color", "color")
    expect(zone(page, "color").locator(".chip-name")).to_have_text(["color"])
    page.wait_for_function(SETTLED)
    assert len(refused) == 2
    expect(page.locator("#toasts .toast")).to_have_count(0)
    expect(zone(page, "color").locator(".chip-name")).to_have_text(["color"])
    assert errors == []


def test_a_plot_waiting_for_its_images_is_not_committed(app_page: Page) -> None:
    """A newer drop that fails while an older plot's images load goes back to the graph drawn before both; the older images failing then change nothing."""
    page = app_page
    status = page.locator("#status")
    start(page)
    before = placed_names(page)
    layout = page.evaluate(LAYOUT)
    bodies = plot_bodies(page)
    held: list[Route] = []

    def images(route: Route) -> None:
        if held:
            route.continue_()
        else:
            held.append(route)

    def plots(route: Route) -> None:
        if len(bodies) == 2:
            fail_with(route, "新しい失敗")
        else:
            route.continue_()

    page.route("**/api/images/*", images)
    page.route("**/api/plot", plots)
    drop(page, "color", "color")
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(100)
    assert held
    # The older plot's figure is not drawn while its images load.
    assert page.evaluate(LAYOUT) == layout
    with page.expect_response(
        lambda r: r.url.endswith("/api/plot") and r.request.post_data_json["encoding"]["color"] is None
    ) as restored:
        drop(page, "facet", "col")
    assert restored.value.ok
    expect(status).to_have_text("エラー: 新しい失敗")
    assert placed_names(page) == before
    held[0].fulfill(status=500, body="gone")
    page.wait_for_function(PAINTED_PIXEL)
    settle(page)
    assert placed_names(page) == before
    expect(status).to_have_text("エラー: 新しい失敗")
    assert [b["encoding"]["color"] for b in bodies] == ["color", "color", None]


# Makes the next `Plotly.newPlot` fail once.
BREAK_NEW_PLOT = """() => {
  const original = Plotly.newPlot;
  Plotly.newPlot = () => {
    Plotly.newPlot = original;
    return Promise.reject(new Error("broken"));
  };
}"""


def test_a_figure_that_cannot_be_drawn_keeps_the_legend(app_page: Page) -> None:
    """A figure whose drawing throws plots the drawn graph again with its legend's inactive levels and its view."""
    page = app_page
    status = page.locator("#status")
    start(page)
    draw(page, "color", "color")
    items = page.locator("#legend .legend-item")
    items.first.click()
    expect(items.first).to_have_class(re.compile(r"\binactive\b"))
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [100, 300]})")
    expect(status).to_contain_text("表示範囲")
    page.wait_for_function(SETTLED)
    shown = page.evaluate(X_RANGE)
    before = placed_names(page)
    page.evaluate(BREAK_NEW_PLOT)
    with page.expect_response("**/api/view") as view:
        drop(page, "facet", "color")
    assert view.value.ok
    expect(status).to_contain_text("図を描けなかった（broken）")
    assert placed_names(page) == before
    expect(page.locator("#legend .legend-title")).to_have_text("color")
    expect(items.first).to_have_class(re.compile(r"\binactive\b"))
    expect(items.nth(1)).not_to_have_class(re.compile(r"\binactive\b"))
    assert page.evaluate(X_RANGE) == pytest.approx(shown)


def test_a_zoom_while_the_images_load_waits_for_the_plot(app_page: Page) -> None:
    """A zoom while a plot's images load asks for no view: the plot is drawn and committed, legend and all."""
    page = app_page
    errors = watch_errors(page)
    status = page.locator("#status")
    start(page)
    held: list[Route] = []
    views: list[str] = []
    page.on("request", lambda r: views.append(r.url) if r.url.endswith("/api/view") else None)

    def images(route: Route) -> None:
        if held:
            route.continue_()
        else:
            held.append(route)

    page.route("**/api/images/*", images)
    drop(page, "color", "color")
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(100)
    assert held
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [100, 300]})")
    settle(page)
    assert views == []
    held[0].continue_()
    expect(page.locator("#legend .legend-title")).to_have_text("color")
    page.wait_for_function(SETTLED)
    expect(zone(page, "color").locator(".chip-name")).to_have_text(["color"])
    # Committed: a failure now comes back to it.
    page.unroute("**/api/images/*")
    failing(page)
    drop(page, "facet", "col")
    expect(status).to_have_text("エラー: 集約に失敗した 1")
    assert placed_names(page)["color"] == ["color"]
    expect(page.locator("#legend .legend-title")).to_have_text("color")
    assert errors == []
