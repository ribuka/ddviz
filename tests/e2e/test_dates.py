"""E2E: a datetime column on an axis, in the hover and in the filter pane.

The browser runs in Asia/Tokyo: plotly reads a number on a date axis at the
browser's local time, and the axes must show the data's (UTC) times anyway.
"""

from __future__ import annotations

import datetime as dt
import itertools
import re
from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_axis_menu import add_second_y, menu_at, y_margins
from tests.e2e.test_left_margin import assert_whole, settle, y_labels
from tests.e2e.test_scatter import (
    BOXES,
    PAINTED_PIXEL,
    SCROLL_AND_SETTLE,
    SETTLED,
    dialog_at,
    place,
    watch_errors,
)

pytestmark = pytest.mark.e2e

# Naive, as a Parquet datetime without a time zone.
START = dt.datetime(2026, 10, 31)  # noqa: DTZ001
ROWS = 1000
# Returns the range of the x axis on screen, as milliseconds.
SHOWN_X_RANGE = """() => {
  const axis = document.getElementById("plot")._fullLayout.xaxis;
  return axis.range.map((v) => axis.r2l(v));
}"""
FULL = "document.getElementById('plot')._fullLayout"


def epoch_ms(at: dt.datetime) -> float:
    """Return a naive datetime as milliseconds since the epoch, read as UTC."""
    return (at - dt.datetime(1970, 1, 1)).total_seconds() * 1000  # noqa: DTZ001


@pytest.fixture
def browser_context_args(browser_context_args: dict) -> dict:
    """Run the browser 9 hours off UTC."""
    return {**browser_context_args, "timezone_id": "Asia/Tokyo"}


@pytest.fixture
def step() -> dt.timedelta:
    """Return the time between two rows."""
    return dt.timedelta(minutes=1)


@pytest.fixture
def temporal_frame(step: dt.timedelta) -> pl.DataFrame:
    """Return rows `step` (and a microsecond) apart, with y their index, took their seconds, day their index's day, clock their time of day and group one of two."""
    return pl.DataFrame(
        {
            "at": [
                START + i * step + dt.timedelta(microseconds=i) for i in range(ROWS)
            ],
            "took": [dt.timedelta(seconds=i) for i in range(ROWS)],
            "y": [float(i) for i in range(ROWS)],
            "day": [START.date() + dt.timedelta(days=i) for i in range(ROWS)],
            "clock": [(START + i * step).time() for i in range(ROWS)],
            "group": [f"g{i % 2}" for i in range(ROWS)],
        }
    )


@pytest.fixture
def scatter_path(tmp_path: Path, temporal_frame: pl.DataFrame) -> Path:
    """Serve the temporal rows instead of the scatter fixture's, with zoned every third day at New York's time.

    Zoned is only in the file: reading its values back in Python needs the
    time zone database, which Windows lacks without `tzdata`.
    """
    path = tmp_path / "temporal.parquet"
    zoned = pl.Series([START + dt.timedelta(days=3 * i) for i in range(ROWS)])
    temporal_frame.with_columns(
        zoned=zoned.dt.replace_time_zone("America/New_York")
    ).write_parquet(path)
    return path


def test_a_datetime_axis_hovers_and_filters_as_dates(
    app_page: Page, temporal_frame: pl.DataFrame
) -> None:
    """A datetime on X draws a date axis, the hover shows the row's datetime, and the filter takes datetimes as text."""
    page = app_page
    errors: list[object] = []
    page.on("pageerror", lambda error: errors.append(error))
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="took")).to_be_visible()
    expect(columns.filter(has_text="at").locator(".column-type")).to_have_text("◷")
    place(page, "at", "x", plots=False)
    place(page, "y", "y")
    pixel = page.wait_for_function(PAINTED_PIXEL).json_value()
    assert (
        page.evaluate("document.getElementById('plot')._fullLayout.xaxis.type")
        == "date"
    )
    expect(page.locator("#plot .xtick text").first).to_contain_text("2026")
    # The axis shows the rows' times, not those 9 hours later, and the page
    # takes it for the overview: nothing is aggregated again.
    low, high = page.evaluate(SHOWN_X_RANGE)
    first, last = temporal_frame["at"][0], temporal_frame["at"][-1]
    assert epoch_ms(first) - 3_600_000 < low <= epoch_ms(first)
    assert epoch_ms(last) <= high < epoch_ms(last) + 3_600_000
    expect(page.locator("#status")).not_to_contain_text("表示範囲")

    page.mouse.move(pixel["x"], pixel["y"])
    label = page.locator("#hover-label")
    expect(label).to_be_visible()
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    row = temporal_frame.row(int(lines["行番号"]), named=True)
    assert lines["at"] == f"{row['at']:%Y-%m-%d %H:%M:%S.%f}"

    # A zoom to the first half (dates on plotly's axis) aggregates its rows.
    half = START + dt.timedelta(minutes=ROWS // 2)
    page.evaluate(
        f"Plotly.relayout('plot', {{'xaxis.range': ['{START:%Y-%m-%d %H:%M}', '{half:%Y-%m-%d %H:%M}']}})"
    )
    expect(page.locator("#status")).to_contain_text("表示範囲")
    page.wait_for_function(SETTLED)
    rows = int(
        re.search(r"([\d,]+) 行", page.locator("#status").inner_text())[1].replace(
            ",", ""
        )
    )
    assert ROWS // 2 - 5 <= rows <= ROWS // 2 + 5
    page.locator("#plot").dblclick()
    page.wait_for_function(SETTLED)

    page.locator("#columns .column").filter(
        has=page.get_by_text("at", exact=True)
    ).drag_to(page.locator("#filters"))
    card = page.locator(".filter-card")
    low = card.locator(".filter-range input").first
    expect(low).to_have_value("2026-10-31 00:00:00.000000")
    low.fill("2026-10-31 15:00")
    low.press("Enter")
    expect(low).to_have_value("2026-10-31 15:00:00.000000")
    expect(page.locator(".filter-summary")).to_contain_text(
        "at: 2026-10-31 15:00:00.000000〜"
    )
    kept = ROWS - 15 * 60
    expect(page.locator("#status")).to_contain_text(f"{kept:,} 行（フィルタ後）")
    assert errors == []


@pytest.mark.parametrize("step", [dt.timedelta(microseconds=500)])
def test_a_datetime_axis_under_a_second_draws_its_points(
    app_page: Page, temporal_frame: pl.DataFrame
) -> None:
    """Datetimes within a second on X draw their points, on an axis of their range, and hover them."""
    page = app_page
    errors: list[object] = []
    page.on("pageerror", lambda error: errors.append(error))
    place(page, "at", "x", plots=False)
    place(page, "y", "y")
    pixel = page.wait_for_function(PAINTED_PIXEL).json_value()
    expect(page.locator("#status")).not_to_contain_text("表示範囲")
    low, high = page.evaluate(SHOWN_X_RANGE)
    first, last = temporal_frame["at"][0], temporal_frame["at"][-1]
    # The axis pads the data's range by a few hundredths of it.
    pad = (epoch_ms(last) - epoch_ms(first)) * 0.1
    assert epoch_ms(first) - pad < low <= epoch_ms(first)
    assert epoch_ms(last) <= high < epoch_ms(last) + pad

    page.mouse.move(pixel["x"], pixel["y"])
    label = page.locator("#hover-label")
    expect(label).to_be_visible()
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    row = temporal_frame.row(int(lines["行番号"]), named=True)
    assert lines["at"] == f"{row['at']:%Y-%m-%d %H:%M:%S.%f}"
    assert errors == []


def test_a_duration_chip_names_its_seconds(app_page: Page) -> None:
    """A duration placed on an axis is named with its unit, seconds."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="took")).to_be_visible()
    page.locator("#columns .column").filter(
        has=page.get_by_text("took", exact=True)
    ).drag_to(page.locator('.zone[data-role="x"]'))
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text("took (s)")


@pytest.mark.parametrize("step", [dt.timedelta(microseconds=500)])
def test_a_reversed_datetime_axis_under_a_second_keeps_its_range(
    app_page: Page,
) -> None:
    """Reversed, a datetime X within a second keeps its very range and sends a zoom as ascending milliseconds."""
    page = app_page
    errors: list[object] = []
    page.on("pageerror", lambda error: errors.append(error))
    place(page, "at", "x", plots=False)
    place(page, "y", "y")
    low, high = page.evaluate(SHOWN_X_RANGE)
    ticks = page.locator("#plot .xtick text")
    box = ticks.nth(ticks.count() // 2).bounding_box()
    page.mouse.click(
        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right"
    )
    page.locator(".axis-menu").get_by_role("button", name="向きを反転").click()
    page.wait_for_function(f"() => ({SHOWN_X_RANGE})()[0] > ({SHOWN_X_RANGE})()[1]")
    # The same milliseconds through plotly's date text (UTC), the other way round.
    assert page.evaluate(SHOWN_X_RANGE) == [high, low]

    third = (high - low) / 3
    with page.expect_request("**/api/view") as request:
        page.evaluate(
            """([a, b]) => {
              return import("/static/js/temporal.js").then((m) =>
                Plotly.relayout("plot", {"xaxis.range": [m.dateText(a), m.dateText(b)]}));
            }""",
            [high - third, low + third],
        )
    (x_range,) = request.value.post_data_json["x_ranges"]
    assert x_range == [
        pytest.approx(low + third, abs=1e-6),
        pytest.approx(high - third, abs=1e-6),
    ]
    page.wait_for_function(SETTLED)
    shown = page.evaluate(SHOWN_X_RANGE)
    assert shown[0] > shown[1]
    assert errors == []


@pytest.mark.parametrize(
    ("column", "chip", "loggable"), [("at", "at", False), ("took", "took (s)", True)]
)
def test_the_left_margin_of_a_temporal_y_opens_its_menu_and_dialog(
    app_page: Page, column: str, chip: str, loggable: bool
) -> None:
    """A datetime or duration y's margin opens its menu (log as on its tick labels), and a double click there its dialog."""
    page = app_page
    place(page, "y", "x", plots=False)
    zone = page.locator('.zone[data-role="y"]')
    page.locator("#columns .column").filter(
        has=page.get_by_text(column, exact=True)
    ).drag_to(zone)
    expect(zone.locator(".chip-name")).to_have_text(chip)
    page.wait_for_function(SETTLED)
    margins = y_margins(page)
    (row,) = margins["rows"]
    point = ((margins["zone"] + row["left"]) / 2, row["between"])
    page.mouse.click(*point, button="right")
    menu = page.locator(".axis-menu")
    expect(menu.locator(".scale-menu-heading")).to_have_text(f"Y 軸: {column}")
    log = menu.get_by_role("button", name="対数表示")
    if loggable:
        expect(log).to_be_enabled()
    else:
        expect(log).to_be_disabled()
    expect(menu.get_by_role("button", name="向きを反転")).to_be_enabled()
    page.keyboard.press("Escape")
    assert menu_at(page, margins["zone"] + 1, row["top"] + 2) == f"Y 軸: {column}"
    assert dialog_at(page, *point) == f"Y 軸: {column}"


# The axis `key` of the plot drawn: its range, ticks and minor ticks in
# linear units (milliseconds on a date axis).
AXIS = """(key) => {
  const a = document.getElementById("plot")._fullLayout[key];
  const minor = a.minor?.showgrid ? a.minor : null;
  return {
    range: a.range.map((v) => a.r2l(v)),
    tickmode: a.tickmode,
    dtick: a.dtick,
    tick0: a.tickmode === "linear" ? a.r2l(a.tick0) : null,
    minor: minor ? minor.dtick : null,
    minor0: minor ? a.r2l(minor.tick0) : null,
  };
}"""

# The reference lines of the plot drawn, as [axis, position in linear units, dash].
LINES = """() => {
  const full = document.getElementById("plot")._fullLayout;
  return (full.shapes ?? []).map((s) => {
    const along = s.xref.endsWith(" domain") ? "y" : "x";
    const ref = s[`${along}ref`];
    const axis = full[ref.replace(/^([xy])/, "$1axis")];
    return [ref, axis.d2l(s[`${along}0`]), s.line.dash];
  });
}"""

AGGREGATING = re.compile(r"/api/(plot|view|overview)\b")
DAY_MS = 86_400_000
# The units of the interval, in milliseconds.
UNIT_MS = {
    "millisecond": 1,
    "second": 1000,
    "minute": 60_000,
    "hour": 3_600_000,
    "day": DAY_MS,
    "week": 7 * DAY_MS,
}


def put(page: Page, column: str, role: str, plots: bool = True) -> None:
    """Drag a column onto a role's zone (a duration's chip names its seconds), and wait for the plot it starts."""
    zone = page.locator(f'.zone[data-role="{role}"]')
    page.locator("#columns .column").filter(
        has=page.get_by_text(column, exact=True)
    ).drag_to(zone)
    name = re.compile(rf"^{re.escape(column)}( \(s\))?$")
    expect(zone.locator(".chip-name").filter(has_text=name)).to_have_count(1)
    if plots:
        page.wait_for_timeout(300)
        page.wait_for_function(SETTLED)


def record(page: Page) -> list[str]:
    """Record the URLs of the requests that aggregate a result from now on."""
    urls: list[str] = []
    page.on(
        "request",
        lambda request: AGGREGATING.search(request.url) and urls.append(request.url),
    )
    return urls


def open_dialog(page: Page, role: str) -> Locator:
    """Double-click the middle tick label of x, or the middle of y's left margin, and return the dialog it opens."""
    page.wait_for_timeout(400)
    if role == "x":
        ticks = page.locator("#plot .xtick text")
        box = ticks.nth(ticks.count() // 2).bounding_box()
        page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    else:
        margins = y_margins(page)
        row = margins["rows"][0]
        page.mouse.dblclick(
            (margins["zone"] + row["left"]) / 2, (row["top"] + row["bottom"]) / 2
        )
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog).to_be_visible()
    return dialog


def reset_axes(page: Page) -> None:
    """Double-click the plot area: back to the overview."""
    page.wait_for_timeout(400)
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator("#status")).not_to_contain_text("表示範囲に")
    page.wait_for_function(SETTLED)


def at_ms(text: str) -> float:
    """Return a naive datetime written as text as milliseconds since the epoch."""
    at = dt.datetime.fromisoformat(text)
    return (at - dt.datetime(1970, 1, 1)) // dt.timedelta(microseconds=1) / 1000  # noqa: DTZ001


def unit_of(dtick: float | str, seconds: bool = False) -> str:
    """Return the unit the dialog picks for plotly's interval: the largest up to it; years for a multiple of 12 months, months otherwise."""
    if isinstance(dtick, str):
        assert dtick.startswith("M")
        return "year" if int(dtick[1:]) % 12 == 0 else "month"
    ms = dtick * 1000 if seconds else dtick
    return max(
        (u for u, size in UNIT_MS.items() if size <= ms),
        key=UNIT_MS.get,
        default="millisecond",
    )


# For each temporal column: the ends and the reference line typed, the range
# and the line's position they stand for (milliseconds, or seconds of a
# duration), the text of the line in the list, and the shape of the text of
# the ends written when the dialog opens.
CASES = {
    "at": (
        "2026-10-31 01:00:00.123456",
        "2026-10-31T02:00:00.5",
        "2026-10-31 01:30:00.25",
        [at_ms("2026-10-31 01:00:00.123456"), at_ms("2026-10-31 02:00:00.500000")],
        at_ms("2026-10-31 01:30:00.250000"),
        "2026-10-31 01:30:00.25",
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d{1,6})?",
    ),
    "day": (
        "2026-11-01 12:30",
        "2026-11-03",
        "2026-11-02",
        [at_ms("2026-11-01 12:30"), at_ms("2026-11-03 00:00")],
        at_ms("2026-11-02 00:00"),
        "2026-11-02",
        r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2}(\.\d{1,6})?)?",
    ),
    "clock": (
        "-00:01:00",
        "24:01:00",
        "12:00",
        [-60_000, DAY_MS + 60_000],
        12 * 3_600_000,
        "12:00:00",
        r"-?\d{2,}:\d{2}:\d{2}(\.\d{1,6})?",
    ),
    "took": (
        "-5",
        "100.5",
        "-0.25",
        [-5, 100.5],
        -0.25,
        "-0.25",
        r"-?\d+(\.\d+)?(e[+-]\d+)?",
    ),
}


@pytest.mark.parametrize("role", ["x", "y"])
@pytest.mark.parametrize("column", list(CASES))
def test_a_temporal_axis_sets_its_range_and_reference_lines(
    app_page: Page, column: str, role: str
) -> None:
    """A double click on a temporal axis opens its column's dialog at the range shown; the range and the line typed land on their axis's coordinates, and the overview keeps the line."""
    page = app_page
    errors = watch_errors(page)
    put(page, column, role, plots=False)
    put(page, "y", "x" if role == "y" else "y")
    # A date y widens the margin once drawn.
    settle(page)
    key = f"{role}axis"
    shown = page.evaluate(AXIS, key)["range"]
    urls = record(page)
    dialog = open_dialog(page, role)
    expect(dialog.locator("h2")).to_have_text(f"{role.upper()} 軸: {column}")
    low, high, line, expected, at, listed, shape = CASES[column]
    for name in ["min", "max"]:
        assert re.fullmatch(shape, dialog.locator(f"input[name={name}]").input_value())
    if column == "took":
        expect(dialog.locator(".axis-dialog-unit")).to_have_text(["秒", "秒", "秒"])
    # Left alone, the range applied moves no axis and asks nothing.
    dialog.get_by_role("button", name="適用").click()
    page.wait_for_timeout(300)
    assert page.evaluate(AXIS, key)["range"] == shown
    assert urls == []

    dialog.locator("input[name=min]").fill(low)
    dialog.locator("input[name=max]").fill(high)
    dialog.locator("input[name=line]").fill(line)
    dialog.get_by_role("button", name="追加").click()
    expect(dialog.locator(".axis-dialog-line-value")).to_have_text([listed])
    with page.expect_request("**/api/view") as request:
        dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    page.wait_for_function(SETTLED)
    (sent,) = request.value.post_data_json[f"{role}_ranges"]
    assert sent == pytest.approx(expected, abs=1e-3)
    assert page.evaluate(AXIS, key)["range"] == pytest.approx(expected, abs=1e-3)
    assert page.evaluate(LINES) == [[role, pytest.approx(at, abs=1e-3), "dash"]]

    # Back to the overview: the range goes, the line stays.
    reset_axes(page)
    assert page.evaluate(AXIS, key)["range"] == pytest.approx(shown)
    assert page.evaluate(LINES) == [[role, pytest.approx(at, abs=1e-3), "dash"]]
    assert errors == []


def test_a_range_left_as_written_keeps_a_deep_zoom_and_a_reversed_axis_its_direction(
    app_page: Page,
) -> None:
    """Applied as written, the range of a zoom within milliseconds stays the very same and asks nothing; a range typed on a reversed axis keeps it reversed."""
    page = app_page
    errors = watch_errors(page)
    put(page, "at", "x", plots=False)
    put(page, "y", "y")
    low, high = page.evaluate(SHOWN_X_RANGE)
    start = low + (high - low) / 3 + 0.000123
    with page.expect_request("**/api/view"):
        page.evaluate(
            """([a, b]) => import("/static/js/temporal.js").then((m) =>
              Plotly.relayout("plot", {"xaxis.range": [m.dateText(a), m.dateText(b)]}))""",
            [start, start + 3.0004567],
        )
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    shown = page.evaluate(SHOWN_X_RANGE)
    urls = record(page)
    dialog = open_dialog(page, "x")
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    page.wait_for_timeout(300)
    assert page.evaluate(SHOWN_X_RANGE) == shown
    assert urls == []

    ticks = page.locator("#plot .xtick text")
    box = ticks.nth(ticks.count() // 2).bounding_box()
    page.mouse.click(
        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right"
    )
    page.locator(".axis-menu").get_by_role("button", name="向きを反転").click()
    page.wait_for_function(f"() => ({SHOWN_X_RANGE})()[0] > ({SHOWN_X_RANGE})()[1]")
    dialog = open_dialog(page, "x")
    # The fields are ascending.
    texts = [
        dialog.locator(f"input[name={name}]").input_value() for name in ["min", "max"]
    ]
    assert texts == sorted(texts)
    dialog.locator("input[name=min]").fill("2026-10-31 02:00")
    dialog.locator("input[name=max]").fill("2026-10-31 03:00:00.000001")
    with page.expect_request("**/api/view"):
        dialog.get_by_role("button", name="OK").click()
    page.wait_for_function(SETTLED)
    expected = [at_ms("2026-10-31 03:00:00.000001"), at_ms("2026-10-31 02:00")]
    assert page.evaluate(SHOWN_X_RANGE) == pytest.approx(expected, abs=1e-3)
    assert urls == [urls[0]]
    assert errors == []


def test_wrong_fields_of_a_temporal_axis_tell_why_and_change_nothing(
    app_page: Page,
) -> None:
    """Dates that do not exist, wrong times, empty ends, a minimum not below the maximum, wrong intervals and splits, and a wrong line are each refused beside their field."""
    page = app_page
    put(page, "at", "x", plots=False)
    put(page, "y", "y")
    shown = page.evaluate(SHOWN_X_RANGE)
    urls = record(page)
    dialog = open_dialog(page, "x")
    errors = dialog.locator(".axis-dialog-error")

    def ok(min: str, max: str, dtick: str, minor: str, why: list[str]) -> None:
        for name, value in [
            ("min", min),
            ("max", max),
            ("dtick", dtick),
            ("minor", minor),
        ]:
            dialog.locator(f"input[name={name}]").fill(value)
        dialog.get_by_role("button", name="OK").click()
        expect(errors).to_have_text([*why, ""])

    ok(
        "2026-02-30",
        "2026-10-31 24:00",
        "0",
        "5",
        [
            "存在しない日付です",
            "時刻が正しくありません",
            "0 より大きくしてください",
            "",
        ],
    )
    ok(
        "",
        "2026-10-31 12:00Z",
        "abc",
        "11",
        [
            "値を入れてください",
            "タイムゾーンは付けられません",
            "数値を入れてください",
            "2〜10 の整数にしてください",
        ],
    )
    ok(
        "2026-10-31 12:00",
        "2026-10-31 12:00:00.0",
        "",
        "2",
        ["", "最小値より大きくしてください", "", "間隔を入れたときだけ使えます"],
    )
    for minor in ["1", "1.5"]:
        ok(
            "2026-10-31 12:61",
            "2026-10-31",
            "1",
            minor,
            ["時刻が正しくありません", "", "", "2〜10 の整数にしてください"],
        )
    dialog.locator("input[name=line]").fill("2026-13-01")
    dialog.get_by_role("button", name="追加").click()
    expect(errors.nth(4)).to_have_text("存在しない日付です")
    expect(dialog.locator(".axis-dialog-line")).to_have_count(0)
    dialog.get_by_role("button", name="適用").click()
    expect(dialog).to_be_visible()
    page.wait_for_timeout(300)
    assert page.evaluate(SHOWN_X_RANGE) == shown
    assert page.evaluate(f"{FULL}.xaxis.tickmode") == "auto"
    assert urls == []
    dialog.get_by_role("button", name="キャンセル").click()

    # A time past the dates plotly draws (infinite, or past the year 9999)
    # is refused, as an end and as a line.
    put(page, "clock", "x")
    urls.clear()
    dialog = open_dialog(page, "x")
    errors = dialog.locator(".axis-dialog-error")
    huge = ["9" * 309 + ":00", "100000000000000:00", "-100000000000000:00"]
    for text in huge:
        dialog.locator("input[name=max]").fill(text)
        dialog.get_by_role("button", name="OK").click()
        expect(errors.nth(1)).to_have_text("時間が大きすぎます")
        dialog.locator("input[name=line]").fill(text)
        dialog.get_by_role("button", name="追加").click()
        expect(errors.nth(4)).to_have_text("時間が大きすぎます")
    expect(dialog.locator(".axis-dialog-line")).to_have_count(0)
    expect(dialog).to_be_visible()
    assert page.evaluate(LINES) == []
    assert urls == []


def test_temporal_ticks_and_their_minor_splits_draw_on_every_panel_and_stay(
    app_page: Page,
) -> None:
    """Fixed intervals of a unit and their minor splits draw on every panel of the column without aggregating, stay through the overview and a new plot, and cleared go back to plotly's ticks."""
    page = app_page
    errors = watch_errors(page)
    put(page, "clock", "x", plots=False)
    put(page, "y", "y")
    put(page, "group", "col")
    urls = record(page)
    dialog = open_dialog(page, "x")
    drawn = page.evaluate(f"{FULL}.xaxis.dtick")
    expect(dialog.locator("input[name=dtick]")).to_have_value("")
    expect(dialog.locator("select[name=unit]")).to_have_value(unit_of(drawn))
    # Every panel of the column: 15 minutes split by 3, from midnight.
    dialog.locator("input[name=dtick]").fill("15")
    dialog.locator("select[name=unit]").select_option("minute")
    dialog.locator("input[name=minor]").fill("3")
    dialog.get_by_role("button", name="適用").click()
    expect(dialog.locator(".axis-dialog-error").nth(3)).to_have_text("")
    axes = [page.evaluate(AXIS, key) for key in ["xaxis", "xaxis2"]]
    for axis in axes:
        assert axis["tickmode"] == "linear"
        assert (axis["dtick"], axis["tick0"]) == (900_000, 0)
        assert (axis["minor"], axis["minor0"]) == (300_000, 0)
    for parts in ["2", "10"]:
        dialog.locator("input[name=minor]").fill(parts)
        dialog.get_by_role("button", name="適用").click()
        expect(dialog.locator(".axis-dialog-error").nth(3)).to_have_text("")
        assert page.evaluate(AXIS, "xaxis2")["minor"] == 900_000 / int(parts)
    # A week is 7 days.
    dialog.locator("input[name=dtick]").fill("1")
    dialog.locator("select[name=unit]").select_option("week")
    dialog.locator("input[name=minor]").fill("")
    dialog.locator("input[name=line]").fill("12:00")
    dialog.get_by_role("button", name="追加").click()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    for key in ["xaxis", "xaxis2"]:
        assert page.evaluate(AXIS, key)["dtick"] == 7 * DAY_MS
    lines = [["x", 12 * 3_600_000, "dash"], ["x2", 12 * 3_600_000, "dash"]]
    assert page.evaluate(LINES) == lines
    # Ticks and lines alone aggregate nothing.
    assert urls == []

    # Opened again, the dialog shows the interval and its unit.
    dialog = open_dialog(page, "x")
    expect(dialog.locator("input[name=dtick]")).to_have_value("1")
    expect(dialog.locator("select[name=unit]")).to_have_value("week")
    expect(dialog.locator(".axis-dialog-line-value")).to_have_text(["12:00:00"])
    dialog.get_by_role("button", name="キャンセル").click()

    # The overview and a new plot keep them.
    page.evaluate(
        "Plotly.relayout('plot', {'xaxis.range': ['1970-01-01 01:00', '1970-01-01 03:00']})"
    )
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    reset_axes(page)
    put(page, "took", "y")
    assert page.evaluate(AXIS, "xaxis2")["dtick"] == 7 * DAY_MS
    assert page.evaluate(LINES) == lines

    # A unit alone, without an interval, keeps plotly's ticks; cleared ticks
    # and lines are plotly's own again.
    dialog = open_dialog(page, "x")
    dialog.locator("input[name=dtick]").fill("")
    dialog.locator("select[name=unit]").select_option("hour")
    dialog.get_by_role("button", name="削除").click()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    for key in ["xaxis", "xaxis2"]:
        assert page.evaluate(AXIS, key)["tickmode"] == "auto"
    assert page.evaluate(LINES) == []
    dialog = open_dialog(page, "x")
    drawn = page.evaluate(f"{FULL}.xaxis.dtick")
    expect(dialog.locator("select[name=unit]")).to_have_value(unit_of(drawn))
    dialog.get_by_role("button", name="キャンセル").click()
    assert errors == []


def test_the_unit_of_an_automatic_interval_follows_the_ticks_drawn(
    app_page: Page,
) -> None:
    """Without an interval set, the unit picked follows plotly's ticks of the zoom: seconds, days, months or years; a duration's are seconds."""
    page = app_page
    put(page, "at", "x", plots=False)
    put(page, "y", "y")
    start = epoch_ms(START)
    picked = []
    for span in [30_000, 10 * DAY_MS, 3 * 365 * DAY_MS]:
        page.evaluate(
            """([a, b]) => import("/static/js/temporal.js").then((m) =>
              Plotly.relayout("plot", {"xaxis.range": [m.dateText(a), m.dateText(b)]}))""",
            [start, start + span],
        )
        page.wait_for_timeout(300)
        page.wait_for_function(SETTLED)
        drawn = page.evaluate(f"{FULL}.xaxis.dtick")
        dialog = open_dialog(page, "x")
        expect(dialog.locator("input[name=dtick]")).to_have_value("")
        expect(dialog.locator("select[name=unit]")).to_have_value(unit_of(drawn))
        dialog.get_by_role("button", name="キャンセル").click()
        picked.append((unit_of(drawn), drawn))
    assert [unit for unit, _ in picked][:2] == ["second", "day"]
    assert picked[-1][0] in {"month", "year"}
    assert str(picked[-1][1]).startswith("M")

    put(page, "took", "x")
    drawn = page.evaluate(f"{FULL}.xaxis.dtick")
    dialog = open_dialog(page, "x")
    expect(dialog.locator("select[name=unit]")).to_have_value(
        unit_of(drawn, seconds=True)
    )
    dialog.get_by_role("button", name="キャンセル").click()


def test_a_log_duration_hides_its_settings_until_linear_again(app_page: Page) -> None:
    """A duration on a log axis opens no dialog and draws none of its settings; linear again, it draws them."""
    page = app_page
    put(page, "y", "x", plots=False)
    put(page, "took", "y")
    dialog = open_dialog(page, "y")
    dialog.locator("input[name=dtick]").fill("100")
    dialog.locator("select[name=unit]").select_option("second")
    dialog.locator("input[name=line]").fill("500")
    dialog.get_by_role("button", name="追加").click()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    assert page.evaluate(AXIS, "yaxis")["dtick"] == 100
    assert page.evaluate(LINES) == [["y", 500, "dash"]]
    margins = y_margins(page)
    (row,) = margins["rows"]
    point = (margins["zone"] + 1, (row["top"] + row["bottom"]) / 2)

    for log in [True, False]:
        page.mouse.click(*point, button="right")
        page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
        kind = "log" if log else "linear"
        page.wait_for_function(f"() => {FULL}.yaxis.type === '{kind}'")
        page.wait_for_timeout(300)
        page.wait_for_function(SETTLED)
        if log:
            assert page.evaluate(LINES) == []
            assert page.evaluate(AXIS, "yaxis")["tickmode"] == "auto"
            assert dialog_at(page, *point) is None
    assert page.evaluate(AXIS, "yaxis")["dtick"] == 100
    assert page.evaluate(LINES) == [["y", 500, "dash"]]
    assert dialog_at(page, *point) == "Y 軸: took"


def test_the_strips_and_the_rows_of_temporal_axes_open_their_columns(
    app_page: Page,
) -> None:
    """Scrolled, the strips' tick labels open the dialogs of the temporal x and y; the margin of each y row opens its column's."""
    page = app_page
    page.set_viewport_size({"width": 800, "height": 600})
    put(page, "at", "x", plots=False)
    put(page, "clock", "y", plots=False)
    put(page, "group", "col")
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    page.locator("#scroller").evaluate(SCROLL_AND_SETTLE, 10_000)
    assert page.locator("#scroller").evaluate("(s) => s.scrollLeft") > 0
    for side, title in [("y", "Y 軸: clock"), ("x", "X 軸: at")]:
        tick = page.locator(f".sticky-strip .tick.{side}").evaluate_all(BOXES)[-1]
        assert (
            dialog_at(
                page, tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2
            )
            == title
        )

    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_timeout(600)
    page.wait_for_function(SETTLED)
    add_second_y(page, "took")
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    margins = y_margins(page)
    titles = [
        dialog_at(page, (margins["zone"] + row["left"]) / 2, row["between"])
        for row in margins["rows"]
    ]
    assert titles == ["Y 軸: clock", "Y 軸: took"]


def test_finer_ticks_of_a_temporal_y_widen_its_margin(app_page: Page) -> None:
    """A line alone asks nothing; ticks of milliseconds on a time y need wider labels, and the margin follows them."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    put(page, "y", "x", plots=False)
    put(page, "clock", "y")
    page.evaluate(
        "Plotly.relayout('plot', {'yaxis.range': ['1970-01-01 10:00:00', '1970-01-01 10:00:30']})"
    )
    settle(page)
    before = y_labels(page)["margin"]
    shown = page.evaluate(AXIS, "yaxis")["range"]
    urls = record(page)
    dialog = open_dialog(page, "y")
    dialog.locator("input[name=line]").fill("10:00:10")
    dialog.get_by_role("button", name="追加").click()
    dialog.get_by_role("button", name="適用").click()
    page.wait_for_timeout(600)
    assert urls == []
    dialog.locator("input[name=dtick]").fill("500")
    dialog.locator("select[name=unit]").select_option("millisecond")
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    settle(page)
    labels = y_labels(page)
    assert labels["margin"] > before
    assert_whole(labels)
    # The view is aggregated again for the new margin, at the same range.
    assert urls, urls
    axis = page.evaluate(AXIS, "yaxis")
    assert axis["range"] == pytest.approx(shown)
    assert axis["dtick"] == 500
    assert errors == []


# The ticks drawn on the axis `key`, in linear units: the major ones and the
# minor ones (plotly's `_vals`), and the texts of the major ones.
TICKS = """(key) => {
  const a = document.getElementById("plot")._fullLayout[key];
  const major = a._vals.filter((t) => !t.minor);
  return {
    major: major.map((t) => t.x),
    minor: a._vals.filter((t) => t.minor).map((t) => t.x),
    text: major.map((t) => t.text),
  };
}"""
EPOCH = dt.datetime(1970, 1, 1)  # noqa: DTZ001
COUNT_ERROR = "有効な正の整数を入力してください"


def month_of(ms: float) -> int:
    """Return the months since 1970-01 of a tick at midnight on the 1st of a month (read as UTC)."""
    at = EPOCH + dt.timedelta(milliseconds=ms)
    assert (at.day, at.time()) == (1, dt.time()), at
    return (at.year - 1970) * 12 + at.month - 1


def assert_calendar(ticks: dict, every: int, minor: int | None) -> None:
    """Check major ticks every `every` months from 1970-01, and minor ones every `minor` months between them, none on a major tick."""
    majors = sorted(month_of(x) for x in ticks["major"])
    assert len(majors) >= 2, majors
    assert all(m % every == 0 for m in majors), majors
    assert all(b - a == every for a, b in itertools.pairwise(majors))
    minors = sorted(month_of(x) for x in ticks["minor"])
    if minor is None:
        assert minors == []
        return
    assert not set(minors) & set(majors)
    for a, b in itertools.pairwise(majors):
        between = [m for m in minors if a < m < b]
        assert between == list(range(a + minor, b, minor)), (a, b, minors)


def test_calendar_ticks_of_a_date_x_follow_the_months(app_page: Page) -> None:
    """Every 5 months with monthly minor ticks on a date x: the 1st of each month across a common and a leap February, without aggregating."""
    page = app_page
    errors = watch_errors(page)
    put(page, "day", "x", plots=False)
    put(page, "y", "y")
    urls = record(page)
    dialog = open_dialog(page, "x")
    units = dialog.locator("select[name=unit] option").evaluate_all(
        "(options) => options.map((o) => o.value)"
    )
    assert units == [*UNIT_MS, "month", "year"]
    dialog.locator("input[name=dtick]").fill("5")
    dialog.locator("select[name=unit]").select_option("month")
    expect(dialog.locator("input[name=minor]")).to_be_hidden()
    check = dialog.locator("input[name=calendar-minor]")
    expect(
        dialog.locator(".axis-dialog-check:has([name=calendar-minor])")
    ).to_have_text("1か月ごとに補助目盛りを表示")
    expect(check).not_to_be_checked()
    check.check()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    axis = page.evaluate(AXIS, "xaxis")
    assert (axis["tickmode"], axis["dtick"], axis["tick0"]) == ("linear", "M5", 0)
    assert (axis["minor"], axis["minor0"]) == ("M1", 0)
    ticks = page.evaluate(TICKS, "xaxis")
    assert_calendar(ticks, 5, 1)
    every = {*ticks["major"], *ticks["minor"]}
    for month in ["2027-02-01", "2027-03-01", "2028-02-01", "2028-03-01"]:
        assert at_ms(month) in every, month
    page.wait_for_timeout(300)
    assert urls == []

    # Opened again: the interval, its unit and the check.
    dialog = open_dialog(page, "x")
    expect(dialog.locator("input[name=dtick]")).to_have_value("5")
    expect(dialog.locator("select[name=unit]")).to_have_value("month")
    expect(dialog.locator("input[name=calendar-minor]")).to_be_checked()
    dialog.get_by_role("button", name="キャンセル").click()
    assert errors == []


def test_calendar_ticks_of_a_zoned_y_stay_on_its_local_years(
    app_page: Page,
) -> None:
    """Every 2 years with yearly minor ticks on a zoned datetime y: January 1st of even years at its local time, through a reversed axis, a pan, a zoom and a new plot, on every panel and the strip."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 800, "height": 600})
    put(page, "y", "x", plots=False)
    put(page, "zoned", "y", plots=False)
    put(page, "group", "col")
    dialog = open_dialog(page, "y")
    dialog.locator("input[name=dtick]").fill("2")
    dialog.locator("select[name=unit]").select_option("year")
    check = dialog.locator("input[name=calendar-minor]")
    expect(
        dialog.locator(".axis-dialog-check:has([name=calendar-minor])")
    ).to_have_text("1年ごとに補助目盛りを表示")
    check.check()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)

    def assert_years() -> None:
        for key in ["yaxis", "yaxis2"]:
            axis = page.evaluate(AXIS, key)
            assert (axis["dtick"], axis["tick0"]) == ("M24", 0)
            assert (axis["minor"], axis["minor0"]) == ("M12", 0)
            assert_calendar(page.evaluate(TICKS, key), 24, 12)

    assert_years()
    # The axis is at the column's local time: its first value is New York's
    # midnight of 2026-10-31, at that very coordinate.
    low = min(page.evaluate(AXIS, "yaxis")["range"])
    assert low < at_ms("2026-10-31") < low + 400 * DAY_MS

    # Reversed, panned and zoomed, the ticks keep the calendar.
    margins = y_margins(page)
    row = margins["rows"][0]
    page.wait_for_timeout(400)
    page.mouse.click(
        (margins["zone"] + row["left"]) / 2, row["between"], button="right"
    )
    page.locator(".axis-menu").get_by_role("button", name="向きを反転").click()
    page.wait_for_function(
        "() => { const r = document.getElementById('plot')._fullLayout.yaxis.range;"
        " return r[0] > r[1]; }"
    )
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    assert_years()
    for a, b in [("2029-03-05 07:00", "2036-07-09"), ("2027-06-01", "2032-02-01")]:
        page.evaluate(f"Plotly.relayout('plot', {{'yaxis.range': ['{b}', '{a}']}})")
        page.wait_for_timeout(300)
        page.wait_for_function(SETTLED)
        assert_years()
    put(page, "took", "x")
    assert_years()

    # The strip of a scrolled grid shows the panels' major ticks.
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    page.locator("#scroller").evaluate(SCROLL_AND_SETTLE, 10_000)
    texts = page.evaluate(TICKS, "yaxis")["text"]
    strip = page.locator(".sticky-labels:not([hidden]) .sticky-strip .tick.y")
    assert strip.all_text_contents() == texts
    assert errors == []


def test_wrong_calendar_intervals_and_the_minor_check(app_page: Page) -> None:
    """A calendar interval takes positive integers whose months are safe; 1 or none turns the minor ticks off; the minor splits and the check are kept apart."""
    page = app_page
    errors = watch_errors(page)
    put(page, "day", "x", plots=False)
    put(page, "y", "y")
    urls = record(page)
    dialog = open_dialog(page, "x")
    dtick = dialog.locator("input[name=dtick]")
    unit = dialog.locator("select[name=unit]")
    check = dialog.locator("input[name=calendar-minor]")
    minor = dialog.locator("input[name=minor]")
    error = dialog.locator(".axis-dialog-error").nth(2)
    dialog.locator("input[name=line]").fill("2027-01-01")
    dialog.get_by_role("button", name="追加").click()
    for which, text in [
        ("month", "0"),
        ("month", "-1"),
        ("month", "1.5"),
        ("month", "1e2"),
        ("month", "9007199254740992"),
        ("year", "750599937895083"),
    ]:
        unit.select_option(which)
        dtick.fill(text)
        expect(check).to_be_disabled()
        dialog.get_by_role("button", name="適用").click()
        expect(error).to_have_text(COUNT_ERROR)
        assert page.evaluate(LINES) == []
        assert page.evaluate(AXIS, "xaxis")["tickmode"] == "auto"
    dtick.fill(" 750599937895082 ")
    expect(check).to_be_enabled()
    dtick.fill(" 3 ")
    unit.select_option("month")
    check.check()
    dialog.get_by_role("button", name="適用").click()
    expect(error).to_have_text("")
    axis = page.evaluate(AXIS, "xaxis")
    assert (axis["dtick"], axis["minor"]) == ("M3", "M1")
    assert len(page.evaluate(LINES)) == 1

    # Disabled for a while, the check comes back as it was.
    dtick.fill("1")
    expect(check).to_be_disabled()
    expect(check).to_be_checked()
    dtick.fill("")
    expect(check).to_be_disabled()
    dtick.fill("3")
    expect(check).to_be_enabled()
    expect(check).to_be_checked()
    # Weeks take minor splits; their field and the check stay apart.
    unit.select_option("week")
    expect(check).to_be_hidden()
    expect(minor).to_have_value("")
    minor.fill("7")
    dtick.fill("1")
    dialog.get_by_role("button", name="適用").click()
    axis = page.evaluate(AXIS, "xaxis")
    assert (axis["dtick"], axis["minor"]) == (7 * DAY_MS, DAY_MS)
    unit.select_option("month")
    dtick.fill("3")
    expect(check).to_be_checked()
    dialog.get_by_role("button", name="適用").click()
    assert page.evaluate(AXIS, "xaxis")["minor"] == "M1"
    unit.select_option("week")
    expect(minor).to_have_value("7")
    unit.select_option("month")

    # Unchecked, an interval of 1 or none: no minor grid lines are left.
    check.uncheck()
    dialog.get_by_role("button", name="適用").click()
    axis = page.evaluate(AXIS, "xaxis")
    assert (axis["dtick"], axis["minor"]) == ("M3", None)
    check.check()
    dialog.get_by_role("button", name="適用").click()
    assert page.evaluate(AXIS, "xaxis")["minor"] == "M1"
    dtick.fill("1")
    dialog.get_by_role("button", name="適用").click()
    expect(error).to_have_text("")
    axis = page.evaluate(AXIS, "xaxis")
    assert (axis["dtick"], axis["minor"]) == ("M1", None)
    assert page.evaluate(TICKS, "xaxis")["minor"] == []
    dtick.fill("3")
    expect(check).not_to_be_checked()
    check.check()
    dialog.get_by_role("button", name="適用").click()
    assert page.evaluate(AXIS, "xaxis")["minor"] == "M1"
    dtick.fill("")
    dialog.get_by_role("button", name="適用").click()
    axis = page.evaluate(AXIS, "xaxis")
    assert (axis["tickmode"], axis["minor"]) == ("auto", None)
    dtick.fill("3")
    expect(check).not_to_be_checked()

    # 12 months set open again as 12 months.
    dtick.fill("12")
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    assert page.evaluate(AXIS, "xaxis")["dtick"] == "M12"
    dialog = open_dialog(page, "x")
    expect(dialog.locator("input[name=dtick]")).to_have_value("12")
    expect(dialog.locator("select[name=unit]")).to_have_value("month")
    dialog.get_by_role("button", name="キャンセル").click()
    page.wait_for_timeout(300)
    assert urls == []
    assert errors == []


@pytest.mark.parametrize(
    ("years", "drawn", "picked"),
    [(2, "M3", "month"), (6, "M12", "year"), (10, "M24", "year")],
)
def test_automatic_calendar_ticks_pick_their_unit(
    app_page: Page, years: int, drawn: str, picked: str
) -> None:
    """Plotly's own ticks of months or years pick that unit with an empty interval; a unit alone keeps them automatic."""
    page = app_page
    put(page, "day", "x", plots=False)
    put(page, "y", "y")
    page.evaluate(
        f"Plotly.relayout('plot', {{'xaxis.range': ['2020-01-01', '{2020 + years}-01-01']}})"
    )
    page.wait_for_timeout(300)
    page.wait_for_function(SETTLED)
    assert page.evaluate(f"{FULL}.xaxis.dtick") == drawn
    dialog = open_dialog(page, "x")
    expect(dialog.locator("input[name=dtick]")).to_have_value("")
    expect(dialog.locator("select[name=unit]")).to_have_value(picked)
    expect(dialog.locator("input[name=calendar-minor]")).to_be_disabled()
    dialog.locator("select[name=unit]").select_option(
        "month" if picked == "year" else "year"
    )
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    assert page.evaluate(AXIS, "xaxis")["tickmode"] == "auto"
    assert page.evaluate(f"{FULL}.xaxis.dtick") == drawn


@pytest.mark.parametrize("column", ["clock", "took"])
def test_times_and_durations_have_no_calendar_units(
    app_page: Page, column: str
) -> None:
    """A time's or a duration's interval takes no months nor years."""
    page = app_page
    put(page, column, "x", plots=False)
    put(page, "y", "y")
    dialog = open_dialog(page, "x")
    units = dialog.locator("select[name=unit] option").evaluate_all(
        "(options) => options.map((o) => o.value)"
    )
    assert units == list(UNIT_MS)
    expect(dialog.locator("input[name=calendar-minor]")).to_have_count(0)
