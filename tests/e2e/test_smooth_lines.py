"""E2E: smoothing lines carry a white edge and lie over every marker (Issue #88)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.test_scatter import PAINTED_PIXEL, SETTLED, place

pytestmark = pytest.mark.e2e


@pytest.fixture
def browser_context_args(browser_context_args: dict) -> dict:
    """Draw at a device pixel ratio of 2, so that a 1 CSS px edge holds whole pixels."""
    return {**browser_context_args, "device_scale_factor": 2}


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write dense rows of one color level around a flat trend: the points fill the line's surroundings in its own color."""
    rng = np.random.default_rng(0)
    n = 20000
    frame = pl.DataFrame(
        {"x": rng.uniform(0, 1, n), "y": rng.normal(0, 0.3, n), "c": ["a"] * n}
    )
    path = tmp_path / "dense.parquet"
    frame.write_parquet(path)
    return path


# Returns the runs of the image layers' pixels down the middle column of the
# first panel: [kind, length, [r, g, b, a] of the run's middle pixel], where
# kind is "none" (transparent), "white" (opaque white) or "color".
COLUMN = """() => {
  const full = document.getElementById("plot")._fullLayout;
  const canvas = document.querySelector("canvas.image-layers");
  const dpr = canvas.width / full.width;
  const x = Math.round((full.xaxis._offset + full.xaxis._length / 2) * dpr);
  const top = Math.ceil(full.yaxis._offset * dpr);
  const height = Math.floor(full.yaxis._length * dpr);
  const { data } = canvas.getContext("2d").getImageData(x, top, 1, height);
  const kind = (i) => {
    const [r, g, b, a] = data.slice(i * 4, i * 4 + 4);
    if (a === 0) return "none";
    return a === 255 && r >= 240 && g >= 240 && b >= 240 ? "white" : "color";
  };
  const runs = [];
  for (let i = 0; i < height; i++) {
    const k = kind(i);
    if (runs.length && runs[runs.length - 1][0] === k) runs[runs.length - 1][1]++;
    else runs.push([k, 1, i]);
  }
  return runs.map(([k, n, start]) => {
    const m = start + Math.floor(n / 2);
    return [k, n, Array.from(data.slice(m * 4, m * 4 + 4))];
  });
}"""


def wait_line(page: Page, rgb: tuple[int, int, int]) -> None:
    """Wait until the middle column shows a line of color `rgb` between white edges."""
    page.wait_for_function(
        f"""() => {{
          const runs = ({COLUMN})();
          return runs.some((run, i) => i > 0 && i < runs.length - 1
            && run[0] === "color" && run[1] >= 3 && run[1] <= 6
            && runs[i - 1][0] === "white" && runs[i + 1][0] === "white"
            && run[2][3] === 255 && Math.abs(run[2][0] - {rgb[0]}) <= 2
            && Math.abs(run[2][1] - {rgb[1]}) <= 2 && Math.abs(run[2][2] - {rgb[2]}) <= 2);
        }}"""
    )


def test_the_line_shows_its_white_edge_over_dense_points_and_a_selection(
    app_page: Page,
) -> None:
    """Over dense points of its own color the line keeps a white edge, before and after a box selection's layer comes, and follows a picked color."""
    page = app_page
    expect(page.locator("#columns .column").filter(has_text="y")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "c", "color")
    page.wait_for_function(PAINTED_PIXEL)
    # Without the line no pixel is white: the points are blue, the rest clear.
    assert all(kind != "white" for kind, _, _ in page.evaluate(COLUMN))
    page.locator("#elements .element").nth(2).click()
    page.wait_for_function(SETTLED)
    wait_line(page, (31, 119, 180))

    # The selected rows are drawn again at full opacity: first in the box,
    # until the server answers, then from the selection's layer.
    held: list[Route] = []
    page.route("**/api/selection", lambda route: held.append(route))
    page.evaluate(
        "() => { window.decoded = 0; const make = window.createImageBitmap;"
        " window.createImageBitmap = (...a) => make(...a).then((b) => { window.decoded++; return b; }); }"
    )
    full = page.evaluate(
        """() => {
          const gd = document.getElementById("plot");
          const { xaxis, yaxis } = gd._fullLayout;
          const rect = gd.getBoundingClientRect();
          return { x: rect.left + xaxis._offset + xaxis._length / 2,
                   y: rect.top + yaxis._offset + yaxis._length / 2 };
        }"""
    )
    page.evaluate("Plotly.relayout('plot', {dragmode: 'select'})")
    page.mouse.move(full["x"] - 60, full["y"] - 80)
    page.mouse.down()
    with page.expect_request("**/api/selection"):
        page.mouse.move(full["x"] + 60, full["y"] + 80, steps=5)
        page.mouse.up()
    wait_line(page, (31, 119, 180))
    assert len(held) == 1
    assert page.evaluate("window.decoded") == 0
    held[0].continue_()
    page.unroute("**/api/selection")
    page.wait_for_function("() => window.decoded > 0")
    wait_line(page, (31, 119, 180))

    # A picked color moves the line to it, still between white edges.
    marker = page.locator("#legend .legend-marker").first
    marker.click(button="right")
    page.locator(".shape-menu").get_by_text("色", exact=True).hover()
    page.locator('.color-panel .color-cell[title="#000000"]').click()
    wait_line(page, (0, 0, 0))

    # A zoom and a smaller window keep the edge (the overview's line is reused).
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [0.3, 0.7]})")
    page.wait_for_function(SETTLED)
    wait_line(page, (0, 0, 0))
    size = page.viewport_size
    page.set_viewport_size(
        {"width": size["width"] - 200, "height": size["height"] - 100}
    )
    wait_line(page, (0, 0, 0))
