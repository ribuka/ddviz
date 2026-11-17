"""E2E: the color scale of a numeric Color follows the local filter, and the lock keeps it (Issue #264)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_axis_freeze import (
    LOCK,
    add_filter,
    lock,
    set_range,
    whole_range,
)
from tests.e2e.test_kept_ranges import settle
from tests.e2e.test_scatter import apply_color_bins, place, watch_errors

pytestmark = pytest.mark.e2e

ROWS = 1001


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Serve x from 0 to 100 by 0.1, y = 2x, c the values of x in another order, and two groups."""
    path = tmp_path / "scale.parquet"
    pl.DataFrame(
        {
            "x": [i / 10 for i in range(ROWS)],
            "y": [i / 5 for i in range(ROWS)],
            "c": [(i * 37) % ROWS / 10 for i in range(ROWS)],
            "g": [f"g{i % 2}" for i in range(ROWS)],
        }
    ).write_parquet(path)
    return path


def ticks(page: Page) -> list[float]:
    """Return the numbers of the color bar's ticks."""
    texts = page.locator("#legend .colorbar-ticks span").all_inner_texts()
    return [float(t.replace(",", "")) for t in texts]


def names(page: Page) -> list[str]:
    """Return the names of the color legend's items."""
    return page.locator("#legend .legend-name").all_inner_texts()


def test_a_gradient_follows_the_filter_unless_locked(app_page: Page) -> None:
    """Filtered, the color bar spans the rows kept; locked, it stays through a new filter; unlocked, it goes to the latest filter's."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "c", "color")
    settle(page)
    whole = ticks(page)
    assert min(whole) <= 10
    assert max(whole) >= 90
    add_filter(page, "c")
    set_range(page, "c", "20", "40")
    narrow = ticks(page)
    assert narrow != whole
    assert min(narrow) >= 20
    assert max(narrow) <= 40
    lock(page)
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "true")
    # Up from 20..40: the card refuses a low end above its high end.
    whole_range(page, "c")
    set_range(page, "c", "50", "60")
    expect(page.locator("#status")).to_contain_text("101 行（フィルタ後）")
    assert ticks(page) == narrow
    # Off: at once the scale of the latest filter.
    lock(page)
    settle(page)
    latest = ticks(page)
    assert min(latest) >= 50
    assert max(latest) <= 60
    assert errors == []


def test_intervals_follow_the_filter_and_the_lock_keeps_them_through_edits(
    app_page: Page,
) -> None:
    """Intervals are cut over the rows kept; locked, they stay through a new filter and an edit of the same color, and a new number of intervals cuts the filter's rows."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "c", "color")
    settle(page)
    apply_color_bins(page, page.locator("#legend .colorbar"), "2")
    settle(page)
    assert names(page) == ["[0, 50)", "[50, 100]"]
    add_filter(page, "c")
    set_range(page, "c", "20", "40")
    assert names(page) == ["[20, 30)", "[30, 40]"]
    lock(page)
    # Up from 20..40: the card refuses a low end above its high end.
    whole_range(page, "c")
    set_range(page, "c", "50", "60")
    expect(page.locator("#status")).to_contain_text("101 行（フィルタ後）")
    assert names(page) == ["[20, 30)", "[30, 40]"]
    # An edit of the graph that keeps the color as it is cut keeps them.
    page.locator('#elements .element[data-element="smooth"]').click()
    settle(page)
    assert names(page) == ["[20, 30)", "[30, 40]"]
    # Another number of intervals: those of the filter's rows, kept from then on.
    apply_color_bins(page, page.locator("#legend .legend-marker").first, "4")
    settle(page)
    assert names(page) == ["[50, 52.5)", "[52.5, 55)", "[55, 57.5)", "[57.5, 60]"]
    set_range(page, "c", "0", "10")
    assert names(page) == ["[50, 52.5)", "[52.5, 55)", "[55, 57.5)", "[57.5, 60]"]
    lock(page)
    settle(page)
    assert names(page) == ["[0, 2.5)", "[2.5, 5)", "[5, 7.5)", "[7.5, 10]"]
    assert errors == []


def test_the_lock_is_of_use_with_a_numeric_color_alone(app_page: Page) -> None:
    """Without a continuous axis, a numeric color makes the lock usable; a categorical one does not."""
    page = app_page
    errors = watch_errors(page)
    place(page, "g", "x")
    place(page, "g", "y")
    place(page, "g", "color")
    settle(page)
    expect(page.locator(LOCK)).to_be_disabled()
    place(page, "c", "color")
    settle(page)
    expect(page.locator(LOCK)).to_be_enabled()
    expect(page.locator(LOCK)).to_have_attribute("title", "軸と色の範囲を固定する")
    expect(page.locator(LOCK)).to_have_attribute("aria-label", "軸と色の範囲を固定")
    assert errors == []
