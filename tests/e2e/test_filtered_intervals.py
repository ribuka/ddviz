"""E2E: the intervals of a numeric Group X and Symbol follow the local filter, and the lock keeps them (Issue #265)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_axis_freeze import LOCK, add_filter, lock, set_range
from tests.e2e.test_kept_ranges import settle
from tests.e2e.test_scatter import place, watch_errors

pytestmark = pytest.mark.e2e

ROWS = 100

# The whole texts of the panels' labels: plotly's annotations, or the
# strips of a grid that scrolls (``static/js/sticky.js``).
STRIPS = """() => {
  const plotted = (document.getElementById("plot").layout.annotations ?? []).map((a) => a.hovertext ?? a.text);
  const stuck = [...document.querySelectorAll(".sticky-strip .facet.col")].map((s) => s.title || s.textContent);
  // The strips stay, hidden, once the grid fits.
  return plotted.length > 0 ? plotted : stuck;
}"""


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Serve x and y from 0 to 99 and g the same integers, one row each."""
    path = tmp_path / "cuts.parquet"
    pl.DataFrame(
        {
            "x": [float(i) for i in range(ROWS)],
            "y": [float(i) for i in range(ROWS)],
            "g": list(range(ROWS)),
        }
    ).write_parquet(path)
    return path


def strips(page: Page) -> list[str]:
    """Return the labels of the panels, in their order."""
    return page.evaluate(STRIPS)


def names(page: Page) -> list[str]:
    """Return the names of the legend's items."""
    return page.locator("#legend .legend-name").all_inner_texts()


def test_group_x_follows_the_filter_unless_locked(app_page: Page) -> None:
    """Filtered, the panels of a numeric Group X are the intervals of the rows kept; locked, they stay through a new filter, those left without rows gone; unlocked, they are the latest filter's."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "g", "col")
    settle(page)
    whole = strips(page)
    assert len(whole) == 5
    add_filter(page, "g")
    set_range(page, "g", "0", "9")
    narrow = strips(page)
    # Before Issue #265, one panel: the first interval of every row.
    assert len(narrow) == 5
    assert narrow != whole
    lock(page)
    expect(page.locator(LOCK)).to_have_attribute("aria-pressed", "true")
    set_range(page, "g", "0", "3")
    expect(page.locator("#status")).to_contain_text("4 行（フィルタ後）")
    kept = strips(page)
    assert 0 < len(kept) < len(narrow)
    assert kept == narrow[: len(kept)]
    # Off: at once the intervals of the latest filter, a panel per value.
    lock(page)
    settle(page)
    assert strips(page) == ["g = 0", "g = 1", "g = 2", "g = 3"]
    assert errors == []


def test_symbol_names_follow_the_filter_unless_locked(app_page: Page) -> None:
    """The legend of a numeric Symbol names the intervals of the rows kept, and the lock keeps them."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "g", "symbol")
    settle(page)
    whole = names(page)
    assert len(whole) == 5
    add_filter(page, "g")
    set_range(page, "g", "0", "3")
    assert names(page) == ["0", "1", "2", "3"]
    lock(page)
    set_range(page, "g", "0", "2")
    assert names(page) == ["0", "1", "2", "3"]
    lock(page)
    settle(page)
    assert names(page) == ["0", "1", "2"]
    assert errors == []
