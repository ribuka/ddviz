"""Tests of spreading a layer's pixels into marker shapes."""

from __future__ import annotations

import numpy as np

from ddviz.compute.shapes import spread
from ddviz.shared.shapes import SHAPES, kernel


def test_spread_draws_the_shape_upright_around_each_pixel() -> None:
    """A pixel becomes the shape centered on it; the layer's row 0 is the bottom."""
    layer = np.zeros((2, 9, 9), dtype=bool)
    layer[1, 4, 4] = True
    shape = kernel(SHAPES.index("triangle-up-filled"), 5)
    out = spread(layer, shape)
    assert not out[0].any()
    # The top of the shape lands on the layer's higher rows.
    assert np.array_equal(out[1, 2:7, 2:7], shape[::-1])
    assert out[1].sum() == shape.sum()


def test_spread_is_cut_at_the_panel_edges() -> None:
    """A shape at a corner keeps only its part inside the panel."""
    layer = np.zeros((1, 4, 4), dtype=bool)
    layer[0, 0, 0] = True
    out = spread(layer, kernel(SHAPES.index("square-filled"), 3))
    assert np.argwhere(out[0]).tolist() == [[0, 0], [0, 1], [1, 0], [1, 1]]


def test_spread_of_grays_keeps_each_pixel_and_takes_the_largest() -> None:
    """Where shapes overlap the larger gray wins; a pixel with rows keeps its own."""
    layer = np.zeros((1, 1, 5), dtype=np.uint8)
    layer[0, 0, 1] = 200
    layer[0, 0, 2] = 10
    out = spread(layer, kernel(SHAPES.index("square-filled"), 3))
    assert out[0, 0].tolist() == [200, 200, 10, 10, 0]
