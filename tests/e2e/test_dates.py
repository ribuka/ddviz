"""E2E: a datetime column on an axis, in the hover and in the filter pane."""

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


@pytest.fixture
def temporal_frame() -> pl.DataFrame:
    """Return rows one minute apart, with y their index and took their seconds."""
    return pl.DataFrame(
        {
            "at": [
                START + dt.timedelta(minutes=i, microseconds=i) for i in range(ROWS)
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


def test_a_duration_chip_names_its_seconds(app_page: Page) -> None:
    """A duration placed on an axis is named with its unit, seconds."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="took")).to_be_visible()
    page.locator("#columns .column").filter(
        has=page.get_by_text("took", exact=True)
    ).drag_to(page.locator('.zone[data-role="x"]'))
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text("took (s)")
