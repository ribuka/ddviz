"""E2E: the (null) row of a filter card keeps or leaves out the missing rows (Issue #255)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_color_levels import card
from tests.e2e.test_filter_cards import add_cards
from tests.e2e.test_scatter import SETTLED, drawn_task, new_result, place

pytestmark = pytest.mark.e2e

ROWS = 600


@pytest.fixture
def scatter_frame() -> pl.DataFrame:
    """Return finite x and y, a categorical g with nulls and a float v with nulls and NaNs."""
    rng = np.random.default_rng(0)
    v = rng.uniform(0, 10, ROWS)
    v[::7] = np.nan
    return pl.DataFrame(
        {
            "x": rng.normal(0, 1, ROWS),
            "y": rng.normal(0, 1, ROWS),
            "g": [None if i % 5 == 0 else f"g{i % 3}" for i in range(ROWS)],
            "v": [None if i % 11 == 0 else float(x) for i, x in enumerate(v)],
        },
        schema_overrides={"v": pl.Float64},
    )


@pytest.fixture
def scatter_path(tmp_path: Path, scatter_frame: pl.DataFrame) -> Path:
    """Write `scatter_frame`."""
    path = tmp_path / "nulls.parquet"
    scatter_frame.write_parquet(path)
    return path


def _rows_after(page: Page, task: str, rows: int) -> None:
    """Wait for a result after `task` and check it draws `rows` rows of the filter."""
    new_result(page, task)
    page.wait_for_function(SETTLED)
    expect(page.locator("#status")).to_have_text(f"{rows:,} 行（フィルタ後）")


def test_the_null_rows_of_a_categorical_and_a_numeric_card(
    app_page: Page, scatter_frame: pl.DataFrame
) -> None:
    """(null) alone keeps the missing rows of g; a narrowed range of v keeps its missing rows (null and NaN) while (null) is ticked, and only the range once unticked."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="v")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    add_cards(page, "g", "v")
    g, v = card(page, "g"), card(page, "v")
    null_g = g.locator(".filter-null")
    expect(null_g.locator(".filter-level-name")).to_have_text("(null)")
    missing_g = scatter_frame["g"].null_count()
    expect(null_g.locator(".filter-level-count")).to_have_text(f"{missing_g:,}")

    task = drawn_task(page)
    null_g.locator("input").check()
    _rows_after(page, task, missing_g)
    expect(page.locator(".filter-summary")).to_have_text("（1）g: null")

    task = drawn_task(page)
    g.locator(".filter-note .filter-reset").click()
    new_result(page, task)
    page.wait_for_function(SETTLED)
    expect(page.locator("#status")).to_have_text(f"{ROWS:,} 行")

    value = scatter_frame["v"]
    missing = value.is_null() | value.is_nan()
    null_v = v.locator(".filter-null")
    expect(null_v.locator(".filter-level-count")).to_have_text(f"{missing.sum():,}")
    expect(null_v.locator("input")).to_be_checked()
    task = drawn_task(page)
    low, high = v.locator(".filter-range input").all()
    low.fill("2")
    low.press("Enter")
    high.fill("6")
    high.press("Enter")
    within = value.is_between(2, 6).fill_null(False)
    _rows_after(page, task, int((within | missing).sum()))
    expect(page.locator(".filter-summary")).to_have_text("（1）v: 2〜6+null")

    task = drawn_task(page)
    null_v.locator("input").uncheck()
    _rows_after(page, task, int((within & ~missing).sum()))
    expect(page.locator(".filter-summary")).to_have_text("（1）v: 2〜6")
