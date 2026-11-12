"""JS: smooth.js draws each line with a 1 CSS px white edge, clipped to its panel (Issue #88)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


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
    js_page: Page, dpr: int
) -> None:
    """The colored stroke is 2 CSS px and the white edge 1 CSS px on each side at any ratio; nothing leaks out of the panel."""
    # Down the column x = 50.5 in device pixels: the line covers y 49..51,
    # the edge 48..49 and 51..52.
    ys = [y / dpr + 0.5 / dpr for y in range(47 * dpr, 53 * dpr)]
    samples = [[50.5, y] for y in ys]
    # Left of the panel (x < 10) and along a line just above it, at y = 9.
    samples += [[9.5, 50.5], [50.5, 7.5], [50.5, 9.5], [50.5, 10.5]]
    pixels = js_page.evaluate(
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
    js_page: Page, order: list[int], center: list[int], edge: list[int]
) -> None:
    """Where lines cross, the later one in the order lies on top with its white edge and its color as a pair."""
    # At the crossing, and on the horizontal red line beside the vertical
    # line's color, inside its white edge (x 48..49).
    pixels = js_page.evaluate(
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
    js_page: Page,
) -> None:
    """An inactive line's white edge fades with its color, and vanishes with it at 0; a series without a color draws gray."""
    samples = [[50.5, 50.25], [50.5, 48.5]]
    args = {"dpr": 2, "lines": [ACROSS], "colors": [], "order": [0], "samples": samples}
    center, edge = js_page.evaluate(DRAW, {**args, "opacity": 1})
    assert center == [0x44, 0x44, 0x44, 255]
    assert edge == WHITE
    center, edge = js_page.evaluate(DRAW, {**args, "opacity": 0.35})
    assert abs(edge[3] - 0.35 * 255) <= 2
    assert abs(center[3] - (1 - 0.65 * 0.65) * 255) <= 2
    assert js_page.evaluate(DRAW, {**args, "opacity": 0}) == [CLEAR, CLEAR]
