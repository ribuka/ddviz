"""Spreading of a layer's pixels into their markers (`ddviz.shared.shapes.marker`).

Each pixel with rows becomes the marker of its series, centered on it: the
shape of its symbol level, or a filled circle without a symbol. Where the
points are dense, the markers merge into a filled area, as plotly's markers
do. On a 4K plot area, spreading one boolean layer took 10 to 25ms (16 to
49 pixels in the shape).
"""

from __future__ import annotations

import numpy as np


def spread(layer: np.ndarray, shape: np.ndarray) -> np.ndarray:
    """Spread each non-empty pixel of a layer into a shape centered on it.

    A pixel that the shapes of several pixels cover takes the largest
    value, its own pixel's among them when the shape covers its center.
    Shapes are cut at the edges of a panel.

    Parameters
    ----------
    layer : numpy.ndarray
        Boolean or unsigned integer array of shape ``(..., height, width)``,
        0 or False where empty; the last two axes are a panel, row 0 at the
        bottom.
    shape : numpy.ndarray
        The shape (`ddviz.shared.shapes.marker`), row 0 at the top.

    Returns
    -------
    numpy.ndarray
        The spread layer, of the same shape and dtype.
    """
    height, width = layer.shape[-2:]
    # The layer's row 0 is the bottom, the shape's the top.
    shape = shape[::-1]
    half_h, half_w = shape.shape[0] // 2, shape.shape[1] // 2
    out = np.zeros_like(layer)
    for dy, dx in zip(*np.nonzero(shape), strict=True):
        oy, ox = int(dy) - half_h, int(dx) - half_w
        target = (
            ...,
            slice(max(oy, 0), height + min(oy, 0)),
            slice(max(ox, 0), width + min(ox, 0)),
        )
        source = (
            ...,
            slice(max(-oy, 0), height + min(-oy, 0)),
            slice(max(-ox, 0), width + min(-ox, 0)),
        )
        np.maximum(out[target], layer[source], out=out[target])
    return out


def spread_top(
    pixel: np.ndarray,
    values: np.ndarray,
    rows: np.ndarray,
    layer_shape: tuple[int, ...],
    shape: np.ndarray,
) -> np.ndarray:
    """Spread pixels of values into a shape each, the point of the largest row on top.

    Where the shapes of several points overlap, the pixel takes the value of
    the point whose row has the largest index, as where they share a pixel
    (the representative row of a bin): plotly draws later rows above earlier
    ones.

    Parameters
    ----------
    pixel : numpy.ndarray
        Flat position of each point in the layer
        (`ddviz.compute.raster.pixels`).
    values : numpy.ndarray
        uint8 value of each point, above 0.
    rows : numpy.ndarray
        Row index of each point, distinct.
    layer_shape : tuple of int
        Shape of the layer, ``(..., height, width)``.
    shape : numpy.ndarray
        The shape (`ddviz.shared.shapes.marker`), row 0 at the top.

    Returns
    -------
    numpy.ndarray
        uint8 array of `layer_shape`, 0 where empty.
    """
    order = np.argsort(rows, kind="stable")
    # Rank 1 is the smallest row; 0 is an empty pixel.
    rank = np.zeros(int(np.prod(layer_shape)), dtype=np.uint32)
    rank[pixel[order]] = np.arange(1, len(order) + 1, dtype=np.uint32)
    top = spread(rank.reshape(layer_shape), shape)
    lookup = np.concatenate([np.zeros(1, dtype=np.uint8), values[order]])
    return lookup[top]
