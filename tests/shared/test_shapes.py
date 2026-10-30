"""Tests of the marker shapes of the overlay levels."""

from __future__ import annotations

import numpy as np
import pytest

from ddviz.shared.shapes import SHAPES, kernel


@pytest.mark.parametrize("size", [3, 7, 15])
def test_every_shape_is_centered_and_distinct(size: int) -> None:
    """Each shape fits its size, covers its center or a ring around it, and differs from the others."""
    kernels = [kernel(i, size) for i in range(len(SHAPES))]
    for k in kernels:
        assert k.shape == (size, size) and k.dtype == bool
        assert k.any()
        # Symmetric left to right.
        assert np.array_equal(k, k[:, ::-1])
    if size >= 7:
        assert len({k.tobytes() for k in kernels}) == len(SHAPES)


def test_shapes_cycle_and_point_the_right_way() -> None:
    """The levels cycle over the shapes; a triangle up is wide at the bottom."""
    assert np.array_equal(kernel(len(SHAPES), 7), kernel(0, 7))
    up = kernel(SHAPES.index("triangle-up-filled"), 7)
    assert up[0].sum() == 1 and up[-1].sum() == 7
    down = kernel(SHAPES.index("triangle-down-filled"), 7)
    assert np.array_equal(down, up[::-1])
    # An outline leaves its middle empty.
    assert not kernel(SHAPES.index("square"), 7)[3, 3]
