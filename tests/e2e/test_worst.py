"""E2E: the worst data (long names, empty levels, huge numbers, no rows) keeps the page in shape."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Locator, Page, Route, expect

from tests.e2e.test_scatter import SETTLED, place

pytestmark = pytest.mark.e2e

LONG = "very_long_column_name_without_any_spaces_" * 3 + "end"
LONG_LEVEL = "level_" + "x" * 100


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write a file whose names and values are the worst the page shows (overrides the shared data)."""
    n = 60
    path = tmp_path / "worst.parquet"
    pl.DataFrame(
        {
            "x": [i + 0.5 for i in range(n)],
            "y": [float(i % 7) for i in range(n)],
            LONG: [float(i % 5) for i in range(n)],
            "g": [[LONG_LEVEL, "", "b"][i % 3] for i in range(n)],
            "huge": [[1e300, -1e300, 2e299][i % 3] for i in range(n)],
        }
    ).write_parquet(path)
    return path


def overflows(locator: Locator) -> bool:
    """Whether an element's text is wider than the element (it ends in "…")."""
    return locator.evaluate("e => e.scrollWidth > e.clientWidth")


def inside(inner: Locator, outer: Locator) -> bool:
    """Whether an element lies within another's box."""
    a, b = inner.bounding_box(), outer.bounding_box()
    assert a is not None and b is not None
    return (
        a["x"] >= b["x"] - 0.5
        and a["y"] >= b["y"] - 0.5
        and a["x"] + a["width"] <= b["x"] + b["width"] + 0.5
        and a["y"] + a["height"] <= b["y"] + b["height"] + 0.5
    )


def test_long_names_end_in_an_ellipsis_inside_their_boxes(app_page: Page) -> None:
    """A long name on Y, on Group Y and in the legend stays in its box and ends in "…"; an empty level shows its placeholder."""
    page = app_page
    expect(page.locator("#columns .column").first).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, LONG, "y")
    place(page, "g", "color")

    for role in ["y", "row"]:
        if role == "row":
            place(page, LONG, "row")
        zone = page.locator(f'.zone[data-role="{role}"]')
        chip = zone.locator(".chip")
        assert inside(chip, zone)
        assert inside(chip.locator(".chip-remove"), zone)
        assert chip.locator(".chip-name").evaluate("e => e.scrollHeight > e.clientHeight")

    legend = page.locator("#legend")
    title = legend.locator(".legend-title")
    expect(title).to_have_attribute("title", "g")
    names = legend.locator(".legend-name")
    expect(names).to_have_text(["（空文字列）", "b", LONG_LEVEL])
    long_item = legend.locator(".legend-item").nth(2)
    expect(long_item).to_have_attribute("title", LONG_LEVEL)
    assert overflows(names.nth(2))
    assert inside(long_item, page.locator("#side"))


def test_huge_numbers_stay_short_and_no_rows_are_told(app_page: Page) -> None:
    """A filter card writes 1e300 in a few digits; a filter that leaves no rows says so over the empty plot."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.first).to_be_visible()
    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    no_rows = page.locator("#no-rows")
    expect(no_rows).to_be_hidden()

    filters = page.locator("#filters")
    columns.filter(has=page.get_by_text("huge", exact=True)).drag_to(filters)
    note = page.locator(".filter-card .filter-note").first
    expect(note).to_contain_text("最大 1.000e+300")
    assert not overflows(note)

    columns.filter(has=page.get_by_text("x", exact=True)).drag_to(filters)
    card = page.locator(".filter-card").nth(1)
    expect(card.locator(".filter-range input")).to_have_count(2)
    status = page.locator("#status")
    task = status.inner_text()
    lo, hi = card.locator(".filter-range input").all()
    lo.fill("1")
    hi.fill("1.1")
    hi.press("Enter")
    expect(status).not_to_have_text(task)
    page.wait_for_function(SETTLED)
    expect(status).to_contain_text(": 0 行")
    expect(no_rows).to_have_text("フィルタの条件に合う行が無い")
    expect(no_rows).to_be_visible()

    card.get_by_role("button", name="全範囲").click()
    expect(no_rows).to_be_hidden()


def test_a_long_error_keeps_the_status_bar_on_one_line(app_page: Page) -> None:
    """An error with a long path ends in "…" in the status bar, which keeps its height; the toast wraps it whole."""
    page = app_page
    path = "C:\\" + "\\".join(["とても長いフォルダの名前"] * 20) + "\\data.parquet"

    def fail(route: Route) -> None:
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({"detail": f"読めない: {path}"}),
        )

    bar = page.locator("#statusbar")
    expect(page.locator("#columns .column").first).to_be_visible()
    height = bar.bounding_box()["height"]
    page.route("**/api/plot", fail)
    place(page, "x", "x", plots=False)
    place(page, "y", "y", plots=False)
    status = page.locator("#status")
    expect(status).to_have_class("notice-error")
    expect(status).to_have_attribute("title", f"エラー: 読めない: {path}")
    assert overflows(status)
    assert bar.bounding_box()["height"] == height
    assert inside(bar.locator("summary"), page.locator("body"))
    toast = page.locator("#toasts .toast")
    expect(toast).to_contain_text(path)
    # The toast comes in from the right: measure it where it stops.
    page.wait_for_function("() => document.querySelector('#toasts .toast').getAnimations().length === 0")
    viewport = page.viewport_size
    box = toast.bounding_box()
    assert viewport is not None and box is not None
    assert box["x"] >= 0 and box["x"] + box["width"] <= viewport["width"]
