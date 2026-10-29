"""The series images of a plot or a selection layer, all in one file of the task."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.png import encode_levels, encode_mask
from ddviz.compute.raster import atlas
from ddviz.shared.keys import BinGrid
from ddviz.shared.manifest import IMAGES


def write_images(
    out: Path, bin_masks: np.ndarray, ncol: int, colors: list[str]
) -> list[list[int] | None]:
    """Write one PNG per series into the images file; return where each lies.

    One PNG per series holds all its panels as tiles: the page decodes 5
    images instead of 500 (about 45ms instead of 120ms for 10 x 10 panels).
    All PNGs go into one file: the first read of each freshly written file
    costs about 0.6ms on Windows (the virus scan, we assume).

    Parameters
    ----------
    out : pathlib.Path
        Directory of the task.
    bin_masks : numpy.ndarray
        Masks of the bins (`ddviz.compute.raster.masks`).
    ncol : int
        Panels to a row of tiles.
    colors : list of str
        Color of each series.

    Returns
    -------
    list
        ``[offset, length]`` of each series' PNG in the file, or None for a
        series without bins.
    """
    images: list[list[int] | None] = []
    offset = 0
    with open(out / IMAGES, "wb") as file:
        for s, color in enumerate(colors):
            series_masks = bin_masks[:, s]
            if not series_masks.any():
                images.append(None)
                continue
            png = encode_mask(atlas(series_masks, ncol), color)
            file.write(png)
            images.append([offset, len(png)])
            offset += len(png)
    return images


def write_gradient(
    out: Path,
    keys: np.ndarray,
    values: pl.Series,
    grid: BinGrid,
    ncol: int,
    color_range: tuple[float, float],
) -> list[list[int] | None]:
    """Write the one PNG of a gradient into the images file; return where it lies.

    Each pixel's gray is its representative row's color value over
    `color_range`, from 1 to 255 (0 is an empty pixel); the page maps the
    grays to the colors of its color scale.

    Parameters
    ----------
    out : pathlib.Path
        Directory of the task.
    keys : numpy.ndarray
        Keys of the non-empty bins of the single series.
    values : polars.Series
        Color value of each bin's representative row.
    grid : BinGrid
        Key space of the bins.
    ncol : int
        Panels to a row of tiles.
    color_range : tuple of float
        Values of gray 1 and gray 255.

    Returns
    -------
    list
        ``[[offset, length]]``, or ``[None]`` without bins.
    """
    if len(keys) == 0:
        (out / IMAGES).write_bytes(b"")
        return [None]
    lo, hi = color_range
    scaled = values.cast(pl.Float64).to_numpy()
    scaled = (scaled - lo) / (hi - lo) if hi > lo else np.full_like(scaled, 0.5)
    dense = np.zeros(grid.size, dtype=np.uint8)
    dense[keys] = 1 + np.rint(np.clip(scaled, 0, 1) * 254).astype(np.uint8)
    tiles = dense.reshape(grid.n_panels, grid.height, grid.width)
    png = encode_levels(atlas(tiles, ncol))
    (out / IMAGES).write_bytes(png)
    return [[0, len(png)]]
