"""Tests of the rasterization of bins."""

from __future__ import annotations

import numpy as np

from ddviz.compute.raster import atlas, masks, occupancy
from ddviz.shared.keys import BinGrid


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


def test_atlas_puts_each_panel_in_its_tile() -> None:
    """Panel p is the tile at row p // ncol, column p % ncol; a short row is padded."""
    panel_masks = np.zeros((3, 2, 4), dtype=bool)
    panel_masks[0, 0, 1] = True
    panel_masks[1, 1, 3] = True
    panel_masks[2, 0, 0] = True
    out = atlas(panel_masks, ncol=2)
    assert out.shape == (4, 8)
    assert np.argwhere(out).tolist() == [[0, 1], [1, 7], [2, 0]]
