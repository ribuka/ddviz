"""Tests of the aggregation key space."""

from __future__ import annotations

import numpy as np

from ddviz.shared.keys import BinGrid


def test_pack_unpack_round_trip_and_dense_order() -> None:
    """Keys unpack to their parts and index a dense (panel, series, by, bx) array."""
    grid = BinGrid(n_panels=3, n_series=4, width=5, height=6)
    keys = np.arange(grid.size)
    panel, series, by, bx = grid.unpack(keys)
    assert (grid.pack(panel, series, by, bx) == keys).all()
    dense = keys.reshape(3, 4, 6, 5)
    assert dense[2, 1, 4, 3] == grid.pack(2, 1, 4, 3)
