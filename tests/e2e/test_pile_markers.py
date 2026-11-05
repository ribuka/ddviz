"""E2E test of the piles of a categorical axis: drawn with their rows, hovered, and turned into points by a zoom."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_scatter import SETTLED, place

pytestmark = pytest.mark.e2e

# Rows of the pile: more than four bands' width holds, fewer than one band's.
PILE = 60


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write a pile of `PILE` equal rows in level a, among rows alone in four levels."""
    frame = pl.DataFrame(
        {
            "g": ["a"] * PILE + ["a", "b", "c", "d"] * 5,
            "y": [1.0] * PILE + [float(v) for v in range(2, 22)],
            "label": [f"r{i}" for i in range(PILE + 20)],
        }
    )
    path = tmp_path / "piles.parquet"
    frame.write_parquet(path)
    return path


# Returns where value (x, y) of the first panel lies on the screen.
AT = """([x, y]) => {
  const gd = document.getElementById("plot");
  const full = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  return {
    x: rect.left + full.xaxis._offset + full.xaxis.l2p(x),
    y: rect.top + full.yaxis._offset + full.yaxis.l2p(y),
  };
}"""


def test_a_pile_hovers_with_its_rows_and_a_zoom_parts_it(app_page: Page) -> None:
    """Equal rows past their band's room show one marker of all their rows; zoomed in on their band, they are points again."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="label")).to_be_visible()
    place(page, "g", "x", plots=False)
    place(page, "y", "y")
    expect(page.locator("#plot .xtick text")).to_have_text(["a", "b", "c", "d"])

    at = page.evaluate(AT, [0, 1.0])
    page.mouse.move(at["x"], at["y"])
    label = page.locator("#hover-label")
    expect(label).to_contain_text(f"重なる点の集まり（{PILE} 行）")
    expect(label).to_contain_text("g: a")
    expect(label).not_to_contain_text("行番号")

    page.mouse.move(at["x"], at["y"] - 200)
    with page.expect_response("**/api/view") as response:
        page.evaluate(
            """() => Plotly.relayout(
              document.getElementById("plot"), {"xaxis.range": [-0.5, 0.5]}
            )"""
        )
    assert response.value.ok
    page.wait_for_function(SETTLED)
    at = page.evaluate(AT, [0, 1.0])

    page.mouse.move(at["x"], at["y"])
    expect(label).to_contain_text("行番号: ")
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    assert int(lines["行番号"]) < PILE
    assert lines["y"] == "1"

