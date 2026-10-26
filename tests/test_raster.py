"""Tests of the rasterization of bins."""

from __future__ import annotations

import numpy as np

from ddviz.keys import BinGrid
from ddviz.raster import masks, occupancy


def test_occupancy_sets_one_bit_per_series() -> None:
    """A pixel's occupancy has bit s set exactly when series s has a bin there."""
    grid = BinGrid(n_panels=2, n_series=3, width=4, height=2)
    keys = np.array(
        [grid.pack(0, 0, 1, 2), grid.pack(0, 2, 1, 2), grid.pack(1, 1, 0, 0)]
    )
    occ = occupancy(masks(keys, grid))
    assert occ.dtype == np.uint8
    assert occ[0, 1, 2] == 0b101
    assert occ[1, 0, 0] == 0b010
    assert occ.sum() == 0b101 + 0b010
