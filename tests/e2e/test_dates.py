"""E2E: a datetime column on an axis, in the hover and in the filter pane.

The browser runs in Asia/Tokyo: plotly reads a number on a date axis at the
browser's local time, and the axes must show the data's (UTC) times anyway.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import PAINTED_PIXEL, SETTLED, place

pytestmark = pytest.mark.e2e

# Naive, as a Parquet datetime without a time zone.
START = dt.datetime(2026, 10, 31)  # noqa: DTZ001
ROWS = 1000
# Returns the range of the x axis on screen, as milliseconds.
SHOWN_X_RANGE = """() => {
  const axis = document.getElementById("plot")._fullLayout.xaxis;
  return axis.range.map((v) => axis.r2l(v));
}"""


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
    """Return rows `step` (and a microsecond) apart, with y their index and took their seconds."""
    return pl.DataFrame(
        {
            "at": [
                START + i * step + dt.timedelta(microseconds=i) for i in range(ROWS)
            ],
            "took": [dt.timedelta(seconds=i) for i in range(ROWS)],
            "y": [float(i) for i in range(ROWS)],
        }
    )


@pytest.fixture
def scatter_path(tmp_path: Path, temporal_frame: pl.DataFrame) -> Path:
    """Serve the temporal rows instead of the scatter fixture's."""
    path = tmp_path / "temporal.parquet"
    temporal_frame.write_parquet(path)
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
def test_the_left_margin_of_a_temporal_y_opens_its_menu_but_no_dialog(
    app_page: Page, column: str, chip: str, loggable: bool
) -> None:
    """A datetime or duration y's margin opens its menu (log as on its tick labels), and a double click there no dialog."""
    from tests.e2e.test_axis_menu import menu_at, y_margins
    from tests.e2e.test_scatter import dialog_at

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
    assert dialog_at(page, *point) is None
