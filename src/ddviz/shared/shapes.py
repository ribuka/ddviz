"""Marker shapes of the overlay levels (`ddviz.shared.scatter.ScatterSpec.overlay`).

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


def kernel(level: int, size: int) -> np.ndarray:
    """Return the shape of an overlay level.

    Parameters
    ----------
    level : int
        Index of the overlay level; the shapes cycle over `SHAPES`.
    size : int
        Width and height in pixels, odd.

    Returns
    -------
    numpy.ndarray
        Boolean array of shape ``(size, size)``, row 0 at the top.
    """
    name = SHAPES[level % len(SHAPES)]
    if name.endswith("-filled"):
        return _filled(name.removesuffix("-filled"), size)
    filled = _filled(name, size)
    if name in ("cross", "x"):
        return filled
    return _outline(filled)
