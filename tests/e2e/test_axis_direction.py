"""E2E: the menu of an axis's tick labels reverses its column's axes and back, on the page alone."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_axis_menu import FULL, _right_click_tick, _settled
from tests.e2e.test_scatter import (
    BOXES,
    PAINTED_PIXEL,
    SCROLL_AND_SETTLE,
    place,
    watch_errors,
)

pytestmark = pytest.mark.e2e

# The requests that aggregate, draw or select: a reversal makes none.
AGGREGATING = re.compile(r"/api/(plot|view|overview|selection)\b")

# The x or y axes of plotly's layout, by key: their offset and whether they
# are reversed (their range descends).
AXES = """(letter) => {
  const full = document.getElementById("plot")._fullLayout;
  const out = {};
  for (const [key, axis] of Object.entries(full)) {
    if (!new RegExp(`^${letter}axis\\\\d*$`).test(key)) continue;
    const [a, b] = axis.range.map((v) => axis.r2l(v));
    out[key] = { offset: axis._offset, reversed: b < a, range: [a, b] };
  }
  return out;
}"""


def _record(page: Page) -> list[str]:
    """Record the URLs of the requests that aggregate, draw or select."""
    urls: list[str] = []
    page.on(
        "request",
        lambda request: AGGREGATING.search(request.url) and urls.append(request.url),
    )
    return urls


def _reverse(page: Page, side: str, heading: str, checked: bool = False) -> None:
    """Pick 向きを反転 in the menu of the middle tick of `side`'s first axis."""
    _right_click_tick(page, side)
    menu = page.locator(".axis-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text(heading)
    item = menu.get_by_role("button", name="向きを反転")
    expect(item).to_be_enabled()
    if checked:
        expect(item).to_have_class("scale-menu-item checked")
    else:
        expect(item).not_to_have_class("scale-menu-item checked")
    item.click()
    expect(menu).to_have_count(0)


def _range(page: Page, key: str) -> list[float]:
    """Return the range of plotly's axis `key`, in linear units, in plotly's order."""
    return page.evaluate(
        f"() => {{ const a = {FULL}.{key}; return a.range.map((v) => a.r2l(v)); }}"
    )


def test_the_tick_menu_reverses_x_and_y_without_a_request(app_page: Page) -> None:
    """X, Y and both turn at the shown range, keep the hover on the drawn points, and turn back; no request aggregates."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    # The conversions of `axisdirection.js` at their edges.
    checks = page.evaluate(
        """async () => {
          const { ascending, oriented } = await import("/static/js/axisdirection.js");
          return [
            ascending([1, 2]), ascending([2, 1]), ascending([3, 3]),
            oriented([1, 2], true), oriented([2, 1], true), oriented([2, 1], false),
            oriented([-5e-324, 5e-324], true), oriented([3, 3], true),
          ];
        }"""
    )
    assert checks[0] == [1, 2] and checks[1] == [1, 2] and checks[2] == [3, 3]
    assert checks[3:6] == [[2, 1], [2, 1], [1, 2]]
    assert checks[6] == [5e-324, -5e-324] and checks[7] == [3, 3]

    # A zoom, which the reversal keeps.
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [-1, 1.5]})")
    _settled(page)
    page.wait_for_function(
        "() => !document.querySelector('#plot').classList.contains('pending')"
    )
    urls = _record(page)

    _reverse(page, "x", "X 軸: x")
    page.wait_for_function(f"() => {FULL}.xaxis.range[0] > {FULL}.xaxis.range[1]")
    assert _range(page, "xaxis") == [pytest.approx(1.5), pytest.approx(-1)]
    assert not page.evaluate(AXES, "y")["yaxis"]["reversed"]

    # The hover finds the row under a drawn point: the images turned with the axis.
    page.wait_for_timeout(200)
    pixel = page.wait_for_function(PAINTED_PIXEL).json_value()
    with page.expect_request(lambda r: "/api/hover" in r.url) as hover:
        page.mouse.move(pixel["x"], pixel["y"])
    # Pixels per bin stay positive on a reversed axis.
    query = parse_qs(urlparse(hover.value.url).query)
    assert float(query["sx"][0]) > 0 and float(query["sy"][0]) > 0
    label = page.locator("#hover-label")
    expect(label).to_contain_text("行番号: ")
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    at = page.evaluate(
        """([px, py]) => {
          const full = document.getElementById("plot")._fullLayout;
          const rect = document.getElementById("plot").getBoundingClientRect();
          const xa = full.xaxis, ya = full.yaxis;
          return {
            x: xa.p2l(px - rect.left - xa._offset), y: ya.p2l(py - rect.top - ya._offset),
            dx: Math.abs(xa.range[1] - xa.range[0]) / xa._length,
            dy: Math.abs(ya.range[1] - ya.range[0]) / ya._length,
          };
        }""",
        [pixel["x"], pixel["y"]],
    )
    # Within the 20px of the nearest row's search.
    assert abs(float(lines["x"]) - at["x"]) <= 21 * at["dx"]
    assert abs(float(lines["y"]) - at["y"]) <= 21 * at["dy"]
    page.mouse.move(0, 0)

    _reverse(page, "y", "Y 軸: y")
    page.wait_for_function(f"() => {FULL}.yaxis.range[0] > {FULL}.yaxis.range[1]")
    assert page.evaluate(AXES, "x")["xaxis"]["reversed"]

    # Back: the same ranges, ascending.
    _reverse(page, "x", "X 軸: x", checked=True)
    page.wait_for_function(f"() => {FULL}.xaxis.range[0] < {FULL}.xaxis.range[1]")
    assert _range(page, "xaxis") == [pytest.approx(-1), pytest.approx(1.5)]
    _reverse(page, "y", "Y 軸: y", checked=True)
    page.wait_for_function(f"() => {FULL}.yaxis.range[0] < {FULL}.yaxis.range[1]")
    page.wait_for_timeout(300)
    assert urls == []
    assert errors == []


def test_a_reversed_axis_zooms_selects_and_resets_in_ascending_values(
    app_page: Page,
) -> None:
    """On reversed axes, a zoom and a box send ascending ranges; the selection stays through a reversal; Reset axes keeps it."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    _reverse(page, "x", "X 軸: x")
    _reverse(page, "y", "Y 軸: y")
    page.wait_for_function(f"() => {FULL}.yaxis.range[0] > {FULL}.yaxis.range[1]")

    # A zoom of plotly's (descending, as plotly keeps it) sends ascending values.
    with page.expect_request("**/api/view") as request:
        page.evaluate("Plotly.relayout('plot', {'xaxis.range': [1, -1]})")
    (x_range,) = request.value.post_data_json["x_ranges"]
    assert x_range == [pytest.approx(-1), pytest.approx(1)]
    _settled(page)
    page.wait_for_function(
        "() => !document.querySelector('#plot').classList.contains('pending')"
    )
    # The view drawn keeps the direction.
    assert _range(page, "xaxis") == [pytest.approx(1), pytest.approx(-1)]

    # A Box Select drag sends the ascending values under the box's edges.
    page.evaluate("Plotly.relayout('plot', {dragmode: 'select'})")
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    x0, x1 = box["x"] + box["width"] * 0.2, box["x"] + box["width"] * 0.8
    y0, y1 = box["y"] + box["height"] * 0.2, box["y"] + box["height"] * 0.8
    expected = page.evaluate(
        """([a, b, c, d]) => {
          const full = document.getElementById("plot")._fullLayout;
          const rect = document.querySelector("#plot .nsewdrag").getBoundingClientRect();
          const x = [a, b].map((p) => full.xaxis.p2l(p - rect.left)).sort((u, v) => u - v);
          const y = [c, d].map((p) => full.yaxis.p2l(p - rect.top)).sort((u, v) => u - v);
          return { x, y };
        }""",
        [x0, x1, y0, y1],
    )
    with page.expect_request("**/api/selection") as request:
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=5)
        page.mouse.up()
    sent = request.value.post_data_json
    assert sent["x_range"] == [pytest.approx(v, abs=0.05) for v in expected["x"]]
    assert sent["y_range"] == [pytest.approx(v, abs=0.05) for v in expected["y"]]
    table = page.locator("#table")
    expect(table).to_be_visible()

    # A reversal back keeps the selection and its table, with no request.
    urls = _record(page)
    _reverse(page, "y", "Y 軸: y", checked=True)
    page.wait_for_function(f"() => {FULL}.yaxis.range[0] < {FULL}.yaxis.range[1]")
    page.wait_for_timeout(300)
    expect(table).to_be_visible()
    assert urls == []
    _reverse(page, "y", "Y 軸: y")
    page.wait_for_function(f"() => {FULL}.yaxis.range[0] > {FULL}.yaxis.range[1]")

    # Reset axes goes back to the overview, still reversed.
    page.evaluate("Plotly.relayout('plot', {dragmode: 'zoom'})")
    plot = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.click(
        plot["x"] + plot["width"] / 2, plot["y"] + plot["height"] / 2, button="right"
    )
    page.locator(".plot-menu").get_by_role("button", name="Reset axes").click()
    _settled(page)
    page.wait_for_timeout(300)
    x_axis = page.evaluate(AXES, "x")["xaxis"]
    y_axis = page.evaluate(AXES, "y")["yaxis"]
    assert x_axis["reversed"] and y_axis["reversed"]
    # The overview's range: wider than the zoom.
    assert x_axis["range"][0] > 1 and x_axis["range"][1] < -1
    # A new size (the overview aggregated again) keeps it too.
    page.set_viewport_size({"width": 1100, "height": 760})
    page.wait_for_timeout(600)
    _settled(page)
    assert page.evaluate(AXES, "x")["xaxis"]["reversed"]
    assert errors == []


def test_facets_turn_together_and_the_other_axes_stay(app_page: Page) -> None:
    """The facets of a column turn together; a second X column and the same column on Y stay as they are."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x", plots=False)
    place(page, "x", "y")
    place(page, "facet", "col")
    _reverse(page, "x", "X 軸: x")
    page.wait_for_function(f"() => {FULL}.xaxis.range[0] > {FULL}.xaxis.range[1]")
    xs = page.evaluate(AXES, "x")
    assert len(xs) == 2 and all(a["reversed"] for a in xs.values())
    assert not any(a["reversed"] for a in page.evaluate(AXES, "y").values())

    # A second X column (y, dropped after x): only x's axes are reversed.
    zone = page.locator('.zone[data-role="x"]')
    box = zone.bounding_box()
    page.locator("#columns .column").filter(
        has=page.get_by_text("y", exact=True)
    ).drag_to(zone, target_position={"x": box["width"] * 0.95, "y": box["height"] / 2})
    expect(zone.locator(".chip-name")).to_have_text(["x", "y"])
    _settled(page)
    page.wait_for_timeout(300)
    xs = sorted(page.evaluate(AXES, "x").values(), key=lambda a: a["offset"])
    assert len(xs) == 4
    # Facet by facet, x then y: the axes of x (the 1st and 3rd from the left) only.
    assert [a["reversed"] for a in xs] == [True, False, True, False]
    assert errors == []


def test_a_categorical_axis_and_the_strips_of_a_scrolled_grid_turn(
    app_page: Page,
) -> None:
    """A categorical X turns its bands; the strips of a scrolled grid open the menu of their column."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 800, "height": 600})
    place(page, "color", "x", plots=False)
    place(page, "y", "y")
    place(page, "facet", "col")
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    page.locator("#scroller").evaluate(SCROLL_AND_SETTLE, 10_000)
    urls = _record(page)
    menu = page.locator(".axis-menu")
    for side, title in [("x", "X 軸: color"), ("y", "Y 軸: y")]:
        before = page.locator(f".sticky-strip .tick.{side}").evaluate_all(BOXES)
        texts = page.locator(f".sticky-strip .tick.{side}").all_inner_texts()
        tick = before[-1]
        page.mouse.click(
            tick["x"] + tick["width"] / 2,
            tick["y"] + tick["height"] / 2,
            button="right",
        )
        expect(menu.locator(".scale-menu-heading")).to_have_text(title)
        expect(page.locator(".plot-menu")).to_have_count(0)
        menu.get_by_role("button", name="向きを反転").click()
        page.wait_for_function(
            f"() => {FULL}.{side}axis.range[0] > {FULL}.{side}axis.range[1]"
        )
        page.locator("#scroller").evaluate(SCROLL_AND_SETTLE, 10_000)
        # The strip's labels follow: the same labels, in the other order on screen.
        after = page.locator(f".sticky-strip .tick.{side}")
        coord = "x" if side == "x" else "y"

        def order(boxes: list[dict], names: list[str], coord: str = coord) -> list[str]:
            pairs = zip([b[coord] for b in boxes], names, strict=True)
            return [n for _, n in sorted(pairs)]

        turned = order(after.evaluate_all(BOXES), after.all_inner_texts())
        assert turned == list(reversed(order(before, texts)))
    page.wait_for_timeout(300)
    assert urls == []
    assert errors == []


def test_a_reversed_log_axis_stays_log(app_page: Page) -> None:
    """A log axis turns and keeps its scale; a zoom sends ascending values."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    _right_click_tick(page, "x")
    page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    page.wait_for_function(f"() => {FULL}.xaxis.type === 'log'")
    _settled(page)
    lo, hi = page.evaluate(f"{FULL}.xaxis.range")
    _reverse(page, "x", "X 軸: x")
    page.wait_for_function(f"() => {FULL}.xaxis.range[0] > {FULL}.xaxis.range[1]")
    assert page.evaluate(f"{FULL}.xaxis.type") == "log"
    assert page.evaluate(f"{FULL}.xaxis.range") == [
        pytest.approx(hi),
        pytest.approx(lo),
    ]
    expect(page.locator("#log-warning")).to_be_visible()
    with page.expect_request("**/api/view") as request:
        page.evaluate("Plotly.relayout('plot', {'xaxis.range': [0, -1]})")
    (x_range,) = request.value.post_data_json["x_ranges"]
    assert x_range == [pytest.approx(0.1), pytest.approx(1.0)]
    _settled(page)
    page.wait_for_function(
        "() => !document.querySelector('#plot').classList.contains('pending')"
    )
    assert page.evaluate(f"{FULL}.xaxis.range") == [pytest.approx(0), pytest.approx(-1)]
    # Back to linear: still reversed.
    _right_click_tick(page, "x")
    page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    page.wait_for_function(f"() => {FULL}.xaxis.type === 'linear'")
    _settled(page)
    assert page.evaluate(AXES, "x")["xaxis"]["reversed"]
    assert errors == []


def test_the_saved_bins_do_not_change_with_the_direction(app_page: Page) -> None:
    """The CSV of the plot data is the same before and after a reversal of X and Y."""
    page = app_page
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    button = page.locator('#plot .modebar-btn[data-title^="データを保存"]')

    def saved() -> bytes:
        button.click()
        with page.expect_download() as info:
            page.locator(".data-menu").get_by_role("button", name="CSV").click()
        return Path(info.value.path()).read_bytes()

    before = saved()
    _reverse(page, "x", "X 軸: x")
    _reverse(page, "y", "Y 軸: y")
    page.wait_for_function(f"() => {FULL}.yaxis.range[0] > {FULL}.yaxis.range[1]")
    assert saved() == before
