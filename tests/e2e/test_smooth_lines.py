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


# Draws fixed lines with smooth.js on a canvas of 100 × 100 CSS px at ratio
# `dpr`, its one panel spanning 10..90 in both directions (data = CSS px −
# 10), and returns the pixels asked for as [r, g, b, a].
DRAW = """async ({ dpr, lines, colors, opacity, order, samples }) => {
  const { drawSmooths } = await import("/static/js/smooth.js");
  const canvas = document.createElement("canvas");
  canvas.width = 100 * dpr;
  canvas.height = 100 * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const axis = { _offset: 10, _length: 80, l2p: (v) => v };
  const full = { xaxis: axis, yaxis: axis };
  const meta = { panels: [{ xaxis: "x", yaxis: "y", smooths: lines }] };
  drawSmooths(ctx, full, meta, colors, () => opacity, order);
  const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
  return samples.map(([x, y]) => {
    const i = (Math.floor(y * dpr) * canvas.width + Math.floor(x * dpr)) * 4;
    return Array.from(data.slice(i, i + 4));
  });
}"""

RED = [255, 0, 0, 255]
BLUE = [0, 0, 255, 255]
WHITE = [255, 255, 255, 255]
CLEAR = [0, 0, 0, 0]
# A horizontal line at CSS y = 50 (series 0) and a vertical one at x = 50
# (series 1), both running past the panel.
ACROSS = [0, [-30, 100], [40, 40]]
DOWN = [1, [40, 40], [-30, 100]]


@pytest.mark.parametrize("dpr", [1, 2])
def test_the_white_edge_is_one_css_pixel_each_side_and_clipped(
    app_page: Page, dpr: int
) -> None:
    """The colored stroke is 2 CSS px and the white edge 1 CSS px on each side at any ratio; nothing leaks out of the panel."""
    # Down the column x = 50.5 in device pixels: the line covers y 49..51,
    # the edge 48..49 and 51..52.
    ys = [y / dpr + 0.5 / dpr for y in range(47 * dpr, 53 * dpr)]
    samples = [[50.5, y] for y in ys]
    # Left of the panel (x < 10) and along a line just above it, at y = 9.
    samples += [[9.5, 50.5], [50.5, 7.5], [50.5, 9.5], [50.5, 10.5]]
    pixels = app_page.evaluate(
        DRAW,
        {
            "dpr": dpr,
            "lines": [ACROSS, [0, [-30, 100], [-1, -1]]],
            "colors": ["#ff0000"],
            "opacity": 1,
            "order": [0],
            "samples": samples,
        },
    )
    column = pixels[: len(ys)]
    expected = (
        [CLEAR] * dpr
        + [WHITE] * dpr
        + [RED] * (2 * dpr)
        + [WHITE] * dpr
        + [CLEAR] * dpr
    )
    assert column == expected
    assert pixels[len(ys) :] == [CLEAR, CLEAR, CLEAR, WHITE]


@pytest.mark.parametrize(
    ("order", "center", "edge"), [([0, 1], BLUE, WHITE), ([1, 0], RED, RED)]
)
def test_a_later_line_covers_an_earlier_one_with_its_edge_and_color(
    app_page: Page, order: list[int], center: list[int], edge: list[int]
) -> None:
    """Where lines cross, the later one in the order lies on top with its white edge and its color as a pair."""
    # At the crossing, and on the horizontal red line beside the vertical
    # line's color, inside its white edge (x 48..49).
    pixels = app_page.evaluate(
        DRAW,
        {
            "dpr": 2,
            "lines": [ACROSS, DOWN],
            "colors": ["#ff0000", "#0000ff"],
            "opacity": 1,
            "order": order,
            "samples": [[50.25, 50.25], [48.5, 50.25]],
        },
    )
    assert pixels == [center, edge]


def test_the_opacity_applies_to_the_edge_and_a_gradient_line_is_gray(
    app_page: Page,
) -> None:
    """An inactive line's white edge fades with its color, and vanishes with it at 0; a series without a color draws gray."""
    samples = [[50.5, 50.25], [50.5, 48.5]]
    args = {"dpr": 2, "lines": [ACROSS], "colors": [], "order": [0], "samples": samples}
    center, edge = app_page.evaluate(DRAW, {**args, "opacity": 1})
    assert center == [0x44, 0x44, 0x44, 255]
    assert edge == WHITE
    center, edge = app_page.evaluate(DRAW, {**args, "opacity": 0.35})
    assert abs(edge[3] - 0.35 * 255) <= 2
    assert abs(center[3] - (1 - 0.65 * 0.65) * 255) <= 2
    assert app_page.evaluate(DRAW, {**args, "opacity": 0}) == [CLEAR, CLEAR]
