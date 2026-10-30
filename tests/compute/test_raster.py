"""Tests of the rasterization of bins."""

from __future__ import annotations

import numpy as np

from ddviz.compute.raster import atlas, by_series, occupancy, pixels, series_layer
from ddviz.shared.keys import BinGrid


def test_occupancy_marks_the_pixels_of_any_series() -> None:
    """A pixel is occupied when some series has a bin there."""
    grid = BinGrid(n_panels=2, n_series=3, width=4, height=2)
    keys = np.array(
        [grid.pack(0, 0, 1, 2), grid.pack(0, 2, 1, 2), grid.pack(1, 1, 0, 0)]
    )
    occ = occupancy(keys, grid)
    assert occ.dtype == bool
    assert np.argwhere(occ).tolist() == [[0, 1, 2], [1, 0, 0]]


def test_by_series_groups_the_keys_of_each_series() -> None:
    """Each series with bins comes once, in order, with the positions of its keys."""
    grid = BinGrid(n_panels=2, n_series=70, width=4, height=2)
    keys = np.sort(
        np.array([grid.pack(1, 0, 0, 1), grid.pack(0, 65, 1, 3), grid.pack(0, 0, 1, 0)])
    )
    found = [(s, sorted(keys[at].tolist())) for s, at in by_series(keys, grid)]
    assert found == [
        (0, sorted([grid.pack(1, 0, 0, 1), grid.pack(0, 0, 1, 0)])),
        (65, [grid.pack(0, 65, 1, 3)]),
    ]


def test_series_layer_sets_the_pixels_of_its_keys() -> None:
    """A series' layer holds its bins in every panel, or their values."""
    grid = BinGrid(n_panels=2, n_series=2, width=4, height=2)
    keys = np.array([grid.pack(0, 1, 1, 2), grid.pack(1, 1, 0, 3)])
    layer = series_layer(pixels(keys, grid), grid)
    assert np.argwhere(layer).tolist() == [[0, 1, 2], [1, 0, 3]]
    values = series_layer(pixels(keys, grid), grid, np.array([7, 9], np.uint8))
    assert values[0, 1, 2] == 7 and values[1, 0, 3] == 9 and values.sum() == 16


def test_atlas_puts_each_panel_in_its_tile() -> None:
    """Panel p is the tile at row p // ncol, column p % ncol; a short row is padded."""
    panel_masks = np.zeros((3, 2, 4), dtype=bool)
    panel_masks[0, 0, 1] = True
    panel_masks[1, 1, 3] = True
    panel_masks[2, 0, 0] = True
    out = atlas(panel_masks, ncol=2)
    assert out.shape == (4, 8)
    assert np.argwhere(out).tolist() == [[0, 1], [1, 7], [2, 0]]
