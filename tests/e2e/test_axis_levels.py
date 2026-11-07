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
IDS = 10_000
LONG_LEVEL = "level_" + "x" * 100
ROWS = 20_000

# The tick labels drawn on an axis: their text and box, left to right or top to bottom.
TICKS = """(axis) => [...document.querySelectorAll(`#plot .${axis}tick text`)].map((t) => {
  const r = t.getBoundingClientRect();
  return { text: t.textContent, left: r.left, right: r.right, top: r.top, bottom: r.bottom };
})"""


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write a file of 420 months, 10,000 ids and the worst levels, by row (overrides the shared data)."""
    rng = np.random.default_rng(102)
    path = tmp_path / "levels.parquet"
    pl.DataFrame(
        {
            "month": [MONTHS[i % 420] for i in range(ROWS)],
            "id": [f"L{i % IDS}" for i in range(ROWS)],
            "w": [[LONG_LEVEL, "", "<b>bold</b>"][i % 3] for i in range(ROWS)],
            "v": rng.normal(size=ROWS),
        }
    ).write_parquet(path)
    return path


def ticks(page: Page, axis: str) -> list[dict]:
    """Return the tick labels drawn on the x or y axis, each with its level's index (``at``)."""
    drawn = page.evaluate(TICKS, axis)
    at = page.evaluate(
        f"() => document.getElementById('plot')._fullLayout.{axis}axis.tickvals"
    )
    assert len(at) == len(drawn)
    return [{**t, "at": i} for t, i in zip(drawn, at, strict=True)]


def assert_readable(drawn: list[dict], levels: list[str], axis: str) -> None:
    """Check that the labels name their levels (an x label whole, a y label maybe cut to the margin), evenly spaced, none over the next."""
    assert 5 <= len(drawn) <= 100
    for t in drawn:
        name = levels[t["at"]]
        if axis == "x":
            assert t["text"] == name
        else:
            assert t["text"] == name or name.startswith(t["text"].removesuffix("…"))
    steps = {b["at"] - a["at"] for a, b in pairwise(drawn)}
    assert len(steps) == 1, steps
    for a, b in pairwise(drawn):
        if axis == "x":
            assert a["right"] <= b["left"]
        else:
            # The y axis's labels go up with the levels.
            assert b["bottom"] <= a["top"]


def test_420_levels_on_x_tick_what_reads_and_name_every_band_zoomed_in(
    app_page: Page,
) -> None:
    """Months on X draw with thinned, whole labels; zoomed to 10 bands, each band is named."""
    page = app_page
    place(page, "v", "y", plots=False)
    place(page, "month", "x")
    assert_readable(ticks(page, "x"), MONTHS, "x")

    page.evaluate(
        "() => Plotly.relayout(document.getElementById('plot'), {'xaxis.range': [9.5, 19.5]})"
    )
    page.wait_for_function(
        """(names) => { const t = [...document.querySelectorAll("#plot .xtick text")].map((e) => e.textContent);
          return t.length === names.length && t.every((s, i) => s === names[i]); }""",
        arg=MONTHS[10:20],
    )
    expect(page.locator("#status")).to_contain_text("表示範囲に ")
    assert [t["text"] for t in ticks(page, "x")] == MONTHS[10:20]


def test_420_levels_on_y_tick_one_label_a_line(app_page: Page) -> None:
    """Months on Y draw with thinned labels that do not overlap."""
    page = app_page
    place(page, "v", "x", plots=False)
    place(page, "month", "y")
    assert_readable(ticks(page, "y"), MONTHS, "y")


def test_10000_levels_draw_with_tens_of_ticks(app_page: Page) -> None:
    """10,000 levels on X, past the limit of the series roles, draw at once with tens of ticks."""
    page = app_page
    place(page, "v", "y", plots=False)
    place(page, "id", "x")
    levels = [f"L{i}" for i in range(IDS)]
    assert_readable(ticks(page, "x"), levels, "x")
    expect(page.locator("#status")).to_contain_text(f"{ROWS:,} 行")


def test_the_axis_level_limit_holds_for_color(app_page: Page) -> None:
    """The months on X draw, and on Color too are refused by Color's limit of 100."""
    page = app_page
    place(page, "v", "y", plots=False)
    place(page, "month", "x")
    place(page, "month", "color", plots=False)
    expect(page.locator("#status")).to_contain_text(
        "month は 420 個で、Color・Overlay・Group・Wrap の上限は 100 個"
    )


def test_worst_levels_tick_in_their_bands(app_page: Page) -> None:
    """A long level ends in "…" within its band, an empty one shows its placeholder, and markup is shown as text."""
    page = app_page
    place(page, "v", "y", plots=False)
    place(page, "w", "x")
    drawn = ticks(page, "x")
    texts = [t["text"] for t in drawn]
    assert len(texts) == 3
    assert "（空文字列）" in texts
    assert "<b>bold</b>" in texts
    (long,) = [t for t in drawn if t["text"].startswith("level_")]
    assert long["text"].endswith("…")
    for a, b in pairwise(drawn):
        assert a["right"] <= b["left"]
