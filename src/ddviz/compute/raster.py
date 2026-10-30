"""Rasterization of aggregated bins into series layers and a pixel occupancy map.

Nothing here holds every series at once: with an overlay, the series are the
pairs of a color level and an overlay level, up to thousands of them, and a
4K plot area takes 8MB per series.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from ddviz.shared.keys import BinGrid


def pixels(keys: np.ndarray, grid: BinGrid) -> np.ndarray:
    """Return the pixel of each key in a panel-major array of every panel's pixels.

    Parameters
    ----------
    keys : numpy.ndarray
        Keys of the non-empty bins.
    grid : BinGrid
        Key space of the bins.

    Returns
    -------
    numpy.ndarray
        ``(panel * height + by) * width + bx`` of each key: its index in an
        array of shape ``(n_panels, height, width)`` flattened.
    """
    panel, _, by, bx = grid.unpack(keys)
    return (panel * grid.height + by) * grid.width + bx


def by_series(keys: np.ndarray, grid: BinGrid) -> Iterator[tuple[int, np.ndarray]]:
    """Yield the positions of the keys of each series with bins, in series order.

    Parameters
    ----------
    keys : numpy.ndarray
        Keys of the non-empty bins.
    grid : BinGrid
        Key space of the bins.

    Yields
    ------
    tuple of int and numpy.ndarray
        A series and the positions in `keys` of its keys.
    """
    if len(keys) == 0:
        return
    _, series, _, _ = grid.unpack(keys)
    order = np.argsort(series, kind="stable")
    ordered = series[order]
    starts = np.flatnonzero(np.diff(ordered, prepend=-1))
    ends = np.append(starts[1:], len(order))
    for start, end in zip(starts, ends, strict=True):
        yield int(ordered[start]), order[start:end]


def series_layer(
    pixel: np.ndarray, grid: BinGrid, values: np.ndarray | None = None
) -> np.ndarray:
    """Return a layer of every panel with the given pixels set.

    Parameters
    ----------
    pixel : numpy.ndarray
        Pixels (`pixels`) of one series' keys.
    grid : BinGrid
        Key space of the bins.
    values : numpy.ndarray, optional
        uint8 value of each pixel; True without.

    Returns
    -------
    numpy.ndarray
        Boolean (or uint8) array of shape ``(n_panels, height, width)``.
    """
    dtype = bool if values is None else np.uint8
    dense = np.zeros(grid.n_panels * grid.height * grid.width, dtype=dtype)
    dense[pixel] = True if values is None else values
    return dense.reshape(grid.n_panels, grid.height, grid.width)


def atlas(panel_masks: np.ndarray, ncol: int) -> np.ndarray:
    """Lay the masks of one series' panels out as tiles of one image.

    Parameters
    ----------
    panel_masks : numpy.ndarray
        Array of shape ``(n_panels, height, width)``, such as a `series_layer`.
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


def occupancy(keys: np.ndarray, grid: BinGrid) -> np.ndarray:
    """Return which pixels hold rows of any series.

    The hover finds the series of an occupied pixel among the keys
    (`ddviz.server.hover.HoverIndex`).

    Parameters
    ----------
    keys : numpy.ndarray
        Keys of the non-empty bins.
    grid : BinGrid
        Key space of the bins.

    Returns
    -------
    numpy.ndarray
        Boolean array of shape ``(n_panels, height, width)``.
    """
    return series_layer(pixels(keys, grid), grid)
