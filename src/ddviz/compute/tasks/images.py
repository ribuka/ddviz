"""The series images of a plot or a selection layer, all in one file of the task."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.png import encode_levels, encode_mask
from ddviz.compute.raster import atlas, by_series, pixels, series_layer
from ddviz.compute.shapes import spread, spread_top
from ddviz.shared.keys import BinGrid
from ddviz.shared.manifest import IMAGES
from ddviz.shared.shapes import marker


def write_images(
    out: Path,
    keys: np.ndarray,
    grid: BinGrid,
    ncol: int,
    colors: list[str],
    shapes: int,
    sizes: list[int],
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
    keys : numpy.ndarray
        Keys of the non-empty bins.
    grid : BinGrid
        Key space of the bins.
    ncol : int
        Panels to a row of tiles.
    colors : list of str
        Color of each series.
    shapes : int
        Number of overlay levels: each pixel of series ``s`` spreads into
        the shape of overlay level ``s % shapes``, or into a filled circle
        with 0, without an overlay (`ddviz.shared.shapes.marker`).
    sizes : list of int
        Size of the markers in pixels: series ``s`` takes item
        ``s % len(sizes)``, one per overlay level
        (`ddviz.shared.scatter.ScatterSpec.marker_sizes`).

    Returns
    -------
    list
        ``[offset, length]`` of each series' PNG in the file, or None for a
        series without bins.
    """
    images: list[list[int] | None] = [None] * grid.n_series
    pixel = pixels(keys, grid)
    offset = 0
    with open(out / IMAGES, "wb") as file:
        for s, at in by_series(keys, grid):
            layer = spread(
                series_layer(pixel[at], grid), marker(s, shapes, sizes[s % len(sizes)])
            )
            png = encode_mask(atlas(layer, ncol), colors[s])
            file.write(png)
            images[s] = [offset, len(png)]
            offset += len(png)
    return images


def gradient_grays(values: pl.Series, color_range: tuple[float, float]) -> np.ndarray:
    """Return the gray of each value of a gradient's color column, from 1 to 255 over `color_range`.

    Parameters
    ----------
    values : polars.Series
        Color values.
    color_range : tuple of float
        Values of gray 1 and gray 255; the middle gray for all when empty.

    Returns
    -------
    numpy.ndarray
        uint8 grays.
    """
    lo, hi = color_range
    scaled = values.cast(pl.Float64).to_numpy()
    scaled = (scaled - lo) / (hi - lo) if hi > lo else np.full_like(scaled, 0.5)
    return 1 + np.rint(np.clip(scaled, 0, 1) * 254).astype(np.uint8)


def write_gradient(
    out: Path,
    keys: np.ndarray,
    values: pl.Series,
    rows: np.ndarray,
    grid: BinGrid,
    ncol: int,
    color_range: tuple[float, float],
    shapes: int,
    sizes: list[int],
) -> list[list[int] | None]:
    """Write the PNGs of a gradient into the images file, one per series; return where each lies.

    Each pixel's gray is its representative row's color value over
    `color_range`, from 1 to 255 (0 is an empty pixel); the page maps the
    grays to the colors of its color scale. A gradient has a single color,
    so its series are the overlay levels, or one without an overlay.

    Parameters
    ----------
    out : pathlib.Path
        Directory of the task.
    keys : numpy.ndarray
        Keys of the non-empty bins.
    values : polars.Series
        Color value of each bin's representative row.
    rows : numpy.ndarray
        Index of each bin's representative row.
    grid : BinGrid
        Key space of the bins.
    ncol : int
        Panels to a row of tiles.
    color_range : tuple of float
        Values of gray 1 and gray 255.
    shapes : int
        Number of overlay levels, as in `write_images`.
    sizes : list of int
        Size of the markers, as in
        `write_images`; where the markers of a series overlap, the point of
        the largest row is on top (`ddviz.compute.shapes.spread_top`).

    Returns
    -------
    list
        ``[offset, length]`` of each series' PNG, or None for one without
        bins.
    """
    grays = gradient_grays(values, color_range)
    images: list[list[int] | None] = [None] * grid.n_series
    pixel = pixels(keys, grid)
    offset = 0
    with open(out / IMAGES, "wb") as file:
        for s, at in by_series(keys, grid):
            layer = spread_top(
                pixel[at],
                grays[at],
                rows[at],
                (grid.n_panels, grid.height, grid.width),
                marker(s, shapes, sizes[s % len(sizes)]),
            )
            png = encode_levels(atlas(layer, ncol))
            file.write(png)
            images[s] = [offset, len(png)]
            offset += len(png)
    return images
