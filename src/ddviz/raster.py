"""Rasterization of aggregated bins into series masks and a pixel occupancy map."""

from __future__ import annotations

import numpy as np

from ddviz.keys import BinGrid

# Occupancy bitmask dtypes by the largest number of series they hold.
_OCCUPANCY_DTYPES = [(8, np.uint8), (16, np.uint16), (32, np.uint32), (64, np.uint64)]


def masks(keys: np.ndarray, grid: BinGrid) -> np.ndarray:
    """Return which bins hold rows.

    Parameters
    ----------
    keys : numpy.ndarray
        Keys of the non-empty bins.
    grid : BinGrid
        Key space of the bins.

    Returns
    -------
    numpy.ndarray
        Boolean array of shape ``(n_panels, n_series, height, width)``.
    """
    dense = np.zeros(grid.size, dtype=bool)
    dense[keys] = True
    return dense.reshape(grid.n_panels, grid.n_series, grid.height, grid.width)


def atlas(panel_masks: np.ndarray, ncol: int) -> np.ndarray:
    """Lay the masks of one series' panels out as tiles of one image.

    Parameters
    ----------
    panel_masks : numpy.ndarray
        Array of shape ``(n_panels, height, width)``, such as ``masks(...)[:, s]``.
    ncol : int
        Tiles per row; panel ``p`` is the tile at row ``p // ncol``, column
        ``p % ncol``. A short last row is filled with empty tiles.

    Returns
    -------
    numpy.ndarray
        Array of shape ``(nrow * height, ncol * width)``; each tile keeps its
        panel's rows in order (row 0 is the bottom bin).
    """
    n_panels, height, width = panel_masks.shape
    nrow = -(-n_panels // ncol)
    tiles = np.zeros((nrow * ncol, height, width), dtype=panel_masks.dtype)
    tiles[:n_panels] = panel_masks
    return (
        tiles.reshape(nrow, ncol, height, width)
        .transpose(0, 2, 1, 3)
        .reshape(nrow * height, ncol * width)
    )


def occupancy(bin_masks: np.ndarray) -> np.ndarray:
    """Return, per pixel, a bitmask of the series with rows there.

    Parameters
    ----------
    bin_masks : numpy.ndarray
        Output of `masks`.

    Returns
    -------
    numpy.ndarray
        Array of shape ``(n_panels, height, width)`` whose bit ``s`` is set
        where series ``s`` has rows.

    Raises
    ------
    ValueError
        With more than 64 series.
    """
    n_series = bin_masks.shape[1]
    dtype = next((t for n, t in _OCCUPANCY_DTYPES if n_series <= n), None)
    if dtype is None:
        raise ValueError(f"at most 64 series are supported, got {n_series}")
    out = np.zeros((bin_masks.shape[0], *bin_masks.shape[2:]), dtype=dtype)
    for s in range(n_series):
        out |= bin_masks[:, s].astype(dtype) << dtype(s)
    return out
