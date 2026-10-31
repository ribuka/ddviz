"""Tests of spreading a layer's pixels into marker shapes."""

from __future__ import annotations

import numpy as np

from ddviz.compute.shapes import spread, spread_top
from ddviz.shared.shapes import SHAPES, kernel, marker


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


def test_spread_top_puts_the_point_of_the_largest_row_on_top() -> None:
    """Where shapes overlap, even over a point's own pixel, the largest row's value wins."""
    shape = kernel(SHAPES.index("square-filled"), 3)
    pixel = np.array([1, 2])
    values = np.array([200, 10], dtype=np.uint8)
    out = spread_top(pixel, values, np.array([5, 9]), (1, 1, 5), shape)
    assert out[0, 0].tolist() == [200, 10, 10, 10, 0]
    out = spread_top(pixel, values, np.array([9, 5]), (1, 1, 5), shape)
    assert out[0, 0].tolist() == [200, 200, 200, 10, 0]


def test_marker_covers_its_center_and_is_a_circle_without_an_overlay() -> None:
    """An outline covers its own pixel; without an overlay the marker is a filled circle."""
    assert marker(0, 2, 7)[3, 3]
    assert not kernel(0, 7)[3, 3]
    circle = marker(5, 0, 5)
    assert circle.tolist() == [
        [False, True, True, True, False],
        [True, True, True, True, True],
        [True, True, True, True, True],
        [True, True, True, True, True],
        [False, True, True, True, False],
    ]
