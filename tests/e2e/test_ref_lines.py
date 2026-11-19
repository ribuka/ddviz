"""E2E: the axis dialog's reference lines of each panel's mean plus or minus n standard deviations and quantiles (Issue #313)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_axis_format import open_dialog
from tests.e2e.test_axis_freeze import add_filter, set_range
from tests.e2e.test_kept_ranges import settle, zoom
from tests.e2e.test_scatter import place, watch_errors

pytestmark = pytest.mark.e2e

ROWS = 2_000
PLOT = re.compile(r"/api/plot$")
# The lines of the statistics drawn: each one's y axis, place and label.
SHAPES = """() => (document.getElementById('plot').layout.shapes ?? [])
  .filter((s) => s.label)
  .map((s) => [s.yref, s.y0, s.label.text])"""


@pytest.fixture
def scatter_frame() -> pl.DataFrame:
    """Return x, a y whose two Group X levels differ in mean and spread, and a column to filter by."""
    rng = np.random.default_rng(313)
    g = np.where(np.arange(ROWS) % 2 == 0, "g0", "g1")
    y = np.where(g == "g0", rng.normal(10, 2, ROWS), rng.normal(-5, 5, ROWS))
    return pl.DataFrame(
        {"x": rng.random(ROWS) * 10, "y": y, "g": g, "k": rng.random(ROWS)}
    )


@pytest.fixture
def scatter_path(tmp_path: Path, scatter_frame: pl.DataFrame) -> Path:
    """Write `scatter_frame` (overrides the shared data)."""
    path = tmp_path / "ref.parquet"
    scatter_frame.write_parquet(path)
    return path


def expected(frame: pl.DataFrame, n: float, p: float | None = None) -> list:
    """Return the lines of μ ± nσ (and of the percentile p) of each Group X level's y, as `SHAPES` lists them."""
    out = []
    for axis, level in (("y", "g0"), ("y2", "g1")):
        values = frame.filter(pl.col("g") == level)["y"].to_numpy()
        mean, std = values.mean(), values.std(ddof=1)
        out += [
            [axis, pytest.approx(mean + n * std, rel=1e-6), f"+{n}σ"],
            [axis, pytest.approx(mean - n * std, rel=1e-6), f"−{n}σ"],
        ]
        if p is not None:
            out.append([axis, pytest.approx(np.percentile(values, p), rel=1e-6), f"P{p}"])
    return sorted(out, key=lambda line: line[0])


def drawn(page: Page) -> list:
    """Return the lines of the statistics drawn, by their y axis."""
    return sorted(page.evaluate(SHAPES), key=lambda line: line[0])


def add(dialog: Locator, kind: str, text: str) -> None:
    """Add a reference line of a kind in the dialog."""
    dialog.locator("select[name=line-type]").select_option(kind)
    dialog.locator("input[name=line]").fill(text)
    dialog.get_by_role("button", name="追加").click()


def test_lines_of_each_panels_statistics(app_page: Page, scatter_frame: pl.DataFrame) -> None:
    """μ ± 2σ plots once and lies at each panel's own values; another n moves it without a plot; a percentile plots once; a zoom keeps the lines; a filter moves them to its rows."""
    page = app_page
    errors = watch_errors(page)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "g", "col")
    plots: list[str] = []
    page.on("request", lambda r: PLOT.search(r.url) and plots.append(r.url))

    dialog = open_dialog(page, "y")
    add(dialog, "sigma", "2")
    dialog.get_by_role("button", name="適用").click()
    settle(page)
    assert len(plots) == 1
    assert drawn(page) == expected(scatter_frame, 2)

    # Another n is drawn from the statistics the result has.
    dialog.locator(".axis-dialog-line").get_by_role("button", name="削除").click()
    add(dialog, "sigma", "3")
    dialog.get_by_role("button", name="適用").click()
    page.wait_for_function(f"() => ({SHAPES})().some((s) => s[2] === '+3σ')")
    settle(page)
    assert len(plots) == 1
    assert drawn(page) == expected(scatter_frame, 3)

    # A new percentile plots once more.
    add(dialog, "quantile", "95")
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    settle(page)
    assert len(plots) == 2
    assert drawn(page) == expected(scatter_frame, 3, 95)

    # A zoom keeps the lines at their values.
    zoom(page, {"yaxis.range": [0, 12]})
    assert len(plots) == 2
    assert drawn(page) == expected(scatter_frame, 3, 95)

    # A filter moves them to the values of its rows.
    add_filter(page, "k")
    set_range(page, "k", "0", "0.5")
    narrowed = scatter_frame.filter(pl.col("k") <= 0.5)
    assert drawn(page) == expected(narrowed, 3, 95)
    assert len(plots) == 2
    assert errors == []
