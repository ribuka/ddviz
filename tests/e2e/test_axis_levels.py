"""E2E: a categorical axis of hundreds to thousands of levels draws, its ticks thinned to labels that read."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import place

pytestmark = pytest.mark.e2e

MONTHS = [f"{y}-{m:02d}" for y in range(1990, 2025) for m in range(1, 13)]
ROWS = 20_000

# The tick labels drawn on the x axis: their text and box, left to right.
TICKS = """() => [...document.querySelectorAll("#plot .xtick text")].map((t) => {
  const r = t.getBoundingClientRect();
  return { text: t.textContent, left: r.left, right: r.right };
})"""


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write a file of 420 months, by row (overrides the shared data)."""
    rng = np.random.default_rng(102)
    path = tmp_path / "levels.parquet"
    pl.DataFrame(
        {
            "month": [MONTHS[i % 420] for i in range(ROWS)],
            "v": rng.normal(size=ROWS),
        }
    ).write_parquet(path)
    return path


def ticks(page: Page) -> list[dict]:
    """Return the tick labels drawn on the x axis, each with its level's index (``at``)."""
    drawn = page.evaluate(TICKS)
    at = page.evaluate("() => document.getElementById('plot')._fullLayout.xaxis.tickvals")
    assert len(at) == len(drawn)
    return [{**t, "at": i} for t, i in zip(drawn, at, strict=True)]


def assert_readable(drawn: list[dict], levels: list[str]) -> None:
    """Check that the labels name their levels whole, evenly spaced, none over the next (the ticks themselves: `tests/js/test_bandticks.py`)."""
    assert 5 <= len(drawn) <= 100
    for t in drawn:
        assert t["text"] == levels[t["at"]]
    steps = {b["at"] - a["at"] for a, b in pairwise(drawn)}
    assert len(steps) == 1, steps
    for a, b in pairwise(drawn):
        assert a["right"] <= b["left"]


def test_420_levels_on_x_tick_what_reads_and_name_every_band_zoomed_in(
    app_page: Page,
) -> None:
    """Months on X draw with thinned, whole labels; zoomed to 10 bands, each band is named."""
    page = app_page
    place(page, "v", "y")
    place(page, "month", "x")
    assert_readable(ticks(page), MONTHS)

    page.evaluate(
        "() => Plotly.relayout(document.getElementById('plot'), {'xaxis.range': [9.5, 19.5]})"
    )
    page.wait_for_function(
        """(names) => { const t = [...document.querySelectorAll("#plot .xtick text")].map((e) => e.textContent);
          return t.length === names.length && t.every((s, i) => s === names[i]); }""",
        arg=MONTHS[10:20],
    )
    expect(page.locator("#status")).to_contain_text("表示範囲に ")
    assert [t["text"] for t in ticks(page)] == MONTHS[10:20]
