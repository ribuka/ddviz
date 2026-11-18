"""E2E: a categorical axis has the bands of the levels of the rows of the local filter."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Page

from tests.e2e.test_color_levels import add_filter, tick
from tests.e2e.test_kept_ranges import settle, shown
from tests.e2e.test_scatter import place, watch_errors

pytestmark = pytest.mark.e2e

ROWS = 600
TICKS = "() => document.getElementById('plot')._fullLayout.xaxis.ticktext"


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Serve g cycling over g0 to g5 and c over a, b, c: the rows of a have g0 and g3, those of b g1 and g4."""
    path = tmp_path / "bands.parquet"
    pl.DataFrame(
        {
            "g": [f"g{i % 6}" for i in range(ROWS)],
            "c": [["a", "b", "c"][i % 3] for i in range(ROWS)],
            "y": [float(i) for i in range(ROWS)],
        }
    ).write_parquet(path)
    return path


def test_a_categorical_axis_follows_the_filter(app_page: Page) -> None:
    """Filtered by another categorical column, the x has the bands of the rows left; a wider filter has those of its rows."""
    page = app_page
    errors = watch_errors(page)
    place(page, "g", "x")
    place(page, "y", "y")
    settle(page)
    assert page.evaluate(TICKS) == [f"g{i}" for i in range(6)]
    assert shown(page, "xaxis") == pytest.approx([-0.5, 5.5])

    add_filter(page, "c")
    tick(page, "c", ["a"])
    settle(page)
    assert page.evaluate(TICKS) == ["g0", "g3"]
    assert shown(page, "xaxis") == pytest.approx([-0.5, 1.5])

    # The bands are those of a and b.
    tick(page, "c", ["b"])
    settle(page)
    assert page.evaluate(TICKS) == ["g0", "g1", "g3", "g4"]
    assert shown(page, "xaxis") == pytest.approx([-0.5, 3.5])
    assert errors == []
