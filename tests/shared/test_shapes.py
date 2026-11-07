"""Tests of the marker shapes of the symbol levels."""

from __future__ import annotations

import numpy as np
import pytest

from ddviz.shared.shapes import AUTO_SHAPES, SHAPES, default_shape, kernel


@pytest.mark.parametrize("size", [3, 7, 15])
def test_every_shape_is_centered_and_distinct(size: int) -> None:
    """Each shape fits its size, covers its center or a ring around it, and differs from the others."""
    kernels = [kernel(name, size) for name in SHAPES]
    for k in kernels:
        assert k.shape == (size, size) and k.dtype == bool
        assert k.any()
        # Symmetric left to right.
        assert np.array_equal(k, k[:, ::-1])
    if size >= 7:
        assert len({k.tobytes() for k in kernels}) == len(SHAPES)


def test_shapes_cycle_and_point_the_right_way() -> None:
    """The levels cycle over the shapes but the x (the missing level's); a triangle up is wide at the bottom."""
    assert [default_shape(i) for i in range(len(AUTO_SHAPES))] == list(AUTO_SHAPES)
    assert "x" not in AUTO_SHAPES and set(AUTO_SHAPES) | {"x"} == set(SHAPES)
    assert default_shape(len(AUTO_SHAPES) + 1) == AUTO_SHAPES[1]
    up = kernel("triangle-up-filled", 7)
    assert up[0].sum() == 1 and up[-1].sum() == 7
    down = kernel("triangle-down-filled", 7)
    assert np.array_equal(down, up[::-1])
    # An outline leaves its middle empty.
    assert not kernel("square", 7)[3, 3]


def test_an_unknown_shape_is_refused() -> None:
    """Only the names of `SHAPES` are shapes."""
    with pytest.raises(ValueError, match="unknown shape"):
        kernel("star", 7)
