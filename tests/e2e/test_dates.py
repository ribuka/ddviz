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

from tests.e2e.test_axis_menu import menu_at, y_margins
from tests.e2e.test_left_margin import assert_whole, settle, y_labels
from tests.e2e.test_scatter import (
    PAINTED_PIXEL,
    SCROLL_AND_SETTLE,
    SETTLED,
    dialog_at,
    place,
    wait_apart,
    wait_idle,
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
    place(page, "at", "x")
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
def test_a_reversed_datetime_axis_under_a_second_keeps_its_range(
    app_page: Page, temporal_frame: pl.DataFrame
) -> None:
    """Datetimes within a second on X draw their points, on an axis of their range, and hover them; reversed, the axis keeps its very range and sends a zoom as ascending milliseconds."""
    page = app_page
    errors: list[object] = []
    page.on("pageerror", lambda error: errors.append(error))
    place(page, "at", "x")
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

    # A range typed in the dialog (its fields ascending) keeps the axis reversed.
    dialog = open_dialog(page, "x")
    texts = [
        dialog.locator(f"input[name={name}]").input_value() for name in ["min", "max"]
    ]
    assert texts == sorted(texts)
    dialog.locator("input[name=min]").fill("2026-10-31 00:00:00.1")
    dialog.locator("input[name=max]").fill("2026-10-31 00:00:00.300001")
    with page.expect_request("**/api/view"):
        dialog.get_by_role("button", name="OK").click()
    page.wait_for_function(SETTLED)
    expected = [at_ms("2026-10-31 00:00:00.300001"), at_ms("2026-10-31 00:00:00.1")]
    assert page.evaluate(SHOWN_X_RANGE) == pytest.approx(expected, abs=1e-3)
    assert errors == []


def test_the_left_margin_of_a_temporal_y_opens_its_menu_and_dialog(
    app_page: Page,
) -> None:
    """A datetime or duration y's margin opens its menu (log as on its tick labels), and a double click there its dialog."""
    page = app_page
    place(page, "y", "x")
    zone = page.locator('.zone[data-role="y"]')
    for column, chip, loggable in [("at", "at", False), ("took", "took (s)", True)]:
        page.locator("#columns .column").filter(
            has=page.get_by_text(column, exact=True)
        ).drag_to(zone)
        expect(zone.locator(".chip-name")).to_have_text(chip)
        wait_idle(page)
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


def put(page: Page, column: str, role: str) -> None:
    """Drag a column onto a role's zone (a duration's chip names its seconds), and wait for what it starts to be drawn (`wait_idle`)."""
    zone = page.locator(f'.zone[data-role="{role}"]')
    page.locator("#columns .column").filter(
        has=page.get_by_text(column, exact=True)
    ).drag_to(zone)
    name = re.compile(rf"^{re.escape(column)}( \(s\))?$")
    expect(zone.locator(".chip-name").filter(has_text=name)).to_have_count(1)
    wait_idle(page)


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
    wait_apart(page)
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
    wait_apart(page)
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator("#status")).not_to_contain_text("表示範囲に")
    page.wait_for_function(SETTLED)


def at_ms(text: str) -> float:
    """Return a naive datetime written as text as milliseconds since the epoch."""
    at = dt.datetime.fromisoformat(text)
    return (at - dt.datetime(1970, 1, 1)) // dt.timedelta(microseconds=1) / 1000  # noqa: DTZ001


# For a datetime and a duration column (every kind's texts:
# `tests/js/test_temporal.py`, `tests/js/test_axisdialog.py`): the ends and
# the reference line typed, the range
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


@pytest.mark.parametrize(("column", "role"), [("at", "x"), ("took", "y")])
def test_a_temporal_axis_sets_its_range_and_reference_lines(
    app_page: Page, column: str, role: str
) -> None:
    """A double click on a temporal axis opens its column's dialog at the range shown; the range and the line typed land on their axis's coordinates, and the overview keeps the line."""
    page = app_page
    errors = watch_errors(page)
    put(page, column, role)
    if column == "took":
        # A duration's chip names its seconds; its tooltip is the column's own name.
        chip = page.locator(f'.zone[data-role="{role}"] .chip')
        expect(chip.locator(".chip-name")).to_have_text("took (s)")
        expect(chip).to_have_attribute("title", "took")
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


def test_temporal_ticks_draw_on_every_panel_and_stay(app_page: Page) -> None:
    """An interval of a unit and a line draw on every panel of the column without aggregating, and stay through the overview and a new plot (the ticks themselves: `tests/js/test_axisdialog.py`)."""
    page = app_page
    errors = watch_errors(page)
    put(page, "clock", "x")
    put(page, "y", "y")
    put(page, "group", "col")
    urls = record(page)
    dialog = open_dialog(page, "x")
    dialog.locator("input[name=dtick]").fill("1")
    dialog.locator("select[name=unit]").select_option("week")
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
    assert errors == []


def test_finer_ticks_of_a_temporal_y_widen_its_margin(app_page: Page) -> None:
    """A line alone asks nothing; ticks of milliseconds on a time y need wider labels, and the margin follows them."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    put(page, "y", "x")
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


def test_calendar_ticks_of_a_zoned_y_stay_on_its_local_years(
    app_page: Page,
) -> None:
    """Every 2 years with yearly minor ticks on a zoned datetime y: January 1st of even years at its local time, through a reversed axis, a pan, a zoom and a new plot, on every panel and the strip."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 800, "height": 600})
    put(page, "y", "x")
    put(page, "zoned", "y")
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
    wait_apart(page)
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


def test_a_zoomed_datetime_axis_keeps_its_range_over_an_edit(app_page: Page) -> None:
    """A datetime x zoomed keeps its milliseconds when a color column is added, and asks the view at them."""
    page = app_page
    errors = watch_errors(page)
    place(page, "at", "x")
    place(page, "y", "y")
    low, high = page.evaluate(SHOWN_X_RANGE)
    third = (high - low) / 3
    zoomed = [low + third, high - third]
    with page.expect_request("**/api/view"):
        page.evaluate(
            """([a, b]) => import("/static/js/temporal.js").then((m) =>
              Plotly.relayout("plot", {"xaxis.range": [m.dateText(a), m.dateText(b)]}))""",
            zoomed,
        )
    page.wait_for_function(SETTLED)
    wait_idle(page)
    with page.expect_request("**/api/view") as request:
        place(page, "group", "color")
    (x_range,) = request.value.post_data_json["x_ranges"]
    assert x_range == [pytest.approx(v, abs=1e-3) for v in zoomed]
    assert page.evaluate(f"{FULL}.xaxis.type") == "date"
    assert page.evaluate(SHOWN_X_RANGE) == pytest.approx(zoomed, abs=1e-3)
    assert errors == []
