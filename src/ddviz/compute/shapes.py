"""Spreading of a layer's pixels into the marker shapes of the overlay levels (`ddviz.shared.shapes`).

Each pixel with rows becomes the shape of its overlay level, centered on it:
where the points are dense, the shapes merge into a filled area, as plotly's
markers do. On a 4K plot area, spreading one layer took 10 to 25ms (16 to 49
pixels in the shape).
"""

from __future__ import annotations

import numpy as np


def spread(layer: np.ndarray, shape: np.ndarray) -> np.ndarray:
    """Spread each non-empty pixel of a layer into a shape centered on it.

    A pixel that the shapes of several pixels cover takes the largest value;
    a non-empty pixel keeps its own. Shapes are cut at the edges of a panel.

    Parameters
    ----------
    layer : numpy.ndarray
        Boolean or uint8 array of shape ``(..., height, width)``, 0 or False
        where empty; the last two axes are a panel, row 0 at the bottom.
    shape : numpy.ndarray
        The shape (`ddviz.shared.shapes.kernel`), row 0 at the top.

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
    return np.where(layer != 0, layer, out)
