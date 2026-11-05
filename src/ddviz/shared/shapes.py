"""Marker shapes of the overlay levels (`ddviz.shared.scatter.ScatterSpec.overlay`), and the circles of the points without one.

The worker spreads each pixel of a series into its shape
(`ddviz.compute.shapes`); the page draws the shapes in the legend.
"""

from __future__ import annotations

import numpy as np

# The shapes in the order the overlay levels take them, cycled: the outlines
# first, which stay apart where they overlap, then the filled ones.
SHAPES = (
    "circle",
    "square",
    "triangle-up",
    "diamond",
    "cross",
    "x",
    "triangle-down",
    "circle-filled",
    "square-filled",
    "triangle-up-filled",
    "diamond-filled",
    "triangle-down-filled",
)
# The shapes the overlay levels take by their place: all but the x, which is
# the missing level's (`ddviz.shared.missing.MISSING_SHAPE`). A level may
# still be given the x by hand (`ddviz.shared.scatter.ScatterSpec.level_shapes`).
AUTO_SHAPES = tuple(s for s in SHAPES if s != "x")


def _filled(name: str, size: int) -> np.ndarray:
    """Return the filled form of a shape, row 0 at the top."""
    c = (size - 1) / 2
    rows, cols = np.mgrid[:size, :size]
    x, y = cols - c, c - rows
    if name == "circle":
        return x**2 + y**2 <= (c + 0.3) ** 2
    if name == "square":
        return np.ones((size, size), dtype=bool)
    if name == "diamond":
        return np.abs(x) + np.abs(y) <= c
    if name == "triangle-up":
        return np.abs(x) <= rows / 2
    if name == "triangle-down":
        return np.abs(x) <= (size - 1 - rows) / 2
    if name == "cross":
        return (x == 0) | (y == 0)
    if name == "x":
        return np.abs(x) == np.abs(y)
    raise ValueError(f"unknown shape: {name}")


def _outline(filled: np.ndarray) -> np.ndarray:
    """Return the pixels of a filled shape that touch a pixel outside it."""
    inside = np.pad(filled, 1)
    interior = (
        inside[:-2, 1:-1] & inside[2:, 1:-1] & inside[1:-1, :-2] & inside[1:-1, 2:]
    )
    return filled & ~interior


def default_shape(level: int) -> str:
    """Return the shape an overlay level takes when none is picked for it.

    Parameters
    ----------
    level : int
        Index of the overlay level; the shapes cycle over `AUTO_SHAPES`.

    Returns
    -------
    str
        One of `AUTO_SHAPES`.
    """
    return AUTO_SHAPES[level % len(AUTO_SHAPES)]


def kernel(name: str, size: int) -> np.ndarray:
    """Return a shape of the overlay levels.

    Parameters
    ----------
    name : str
        One of `SHAPES`.
    size : int
        Width and height in pixels, odd.

    Returns
    -------
    numpy.ndarray
        Boolean array of shape ``(size, size)``, row 0 at the top.
    """
    if name not in SHAPES:
        raise ValueError(f"unknown shape: {name}")
    if name.endswith("-filled"):
        return _filled(name.removesuffix("-filled"), size)
    filled = _filled(name, size)
    if name in ("cross", "x"):
        return filled
    return _outline(filled)


def marker(shape: str | None, size: int) -> np.ndarray:
    """Return the marker a series' points are drawn in.

    Parameters
    ----------
    shape : str or None
        The shape of the series' overlay level, one of `SHAPES`
        (`ddviz.shared.scatter.ScatterSpec.marker_shapes`); None without an
        overlay, whose points are filled circles.
    size : int
        Width and height in pixels, odd.

    Returns
    -------
    numpy.ndarray
        Boolean array of shape ``(size, size)``, row 0 at the top. Its
        center is always set: a point covers its own pixel, even inside an
        outline.
    """
    out = kernel(shape, size) if shape is not None else _filled("circle", size)
    out = out.copy()
    out[size // 2, size // 2] = True
    return out
