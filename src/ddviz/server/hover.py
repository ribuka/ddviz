"""Looks up the row under the cursor in the hover files a plot task wrote."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ddviz.shared.keys import BinGrid
from ddviz.shared.manifest import read_manifest

# Hover distance in screen pixels, as plotly's default `hoverdistance`.
HOVER_DISTANCE = 20
# Cap on the search window in bins, for views zoomed out so far that a bin
# is much smaller than a pixel.
_MAX_WINDOW = 256


class HoverIndex:
    """Memory-mapped hover files of one plot task.

    Parameters
    ----------
    out : pathlib.Path
        The task's output directory.
    """

    def __init__(self, out: Path) -> None:
        self.out = out
        self.manifest = read_manifest(out)
        self.grid = BinGrid(**self.manifest["grid"])
        self._keys = np.load(out / "keys.npy", mmap_mode="r")
        self._count = np.load(out / "count.npy", mmap_mode="r")
        self._index = np.load(out / "index.npy", mmap_mode="r")
        self._occupancy = np.load(out / "occupancy.npy", mmap_mode="r")
        self._columns = [
            (c["name"], np.load(out / c["file"], mmap_mode="r"), c["labels"])
            for c in self.manifest["columns"]
        ]

    def close(self) -> None:
        """Drop the memory maps, so that the files can be deleted."""
        self._keys = self._count = self._index = self._occupancy = None
        self._columns = []

    def _find(self, key: int) -> int | None:
        """Return the position of a key, or None if its bin is empty."""
        i = int(np.searchsorted(self._keys, key))
        if i < len(self._keys) and self._keys[i] == key:
            return i
        return None

    def _nearest_pixel(
        self, panel: int, fx: float, fy: float, sx: float, sy: float
    ) -> tuple[int, int] | None:
        """Return the occupied bin nearest the cursor within the hover distance."""
        grid = self.grid
        cx, cy = math.floor(fx), math.floor(fy)
        if (
            0 <= cx < grid.width
            and 0 <= cy < grid.height
            and self._occupancy[panel, cy, cx]
        ):
            return cx, cy
        rx = min(math.ceil(HOVER_DISTANCE / sx), _MAX_WINDOW)
        ry = min(math.ceil(HOVER_DISTANCE / sy), _MAX_WINDOW)
        x0, x1 = max(cx - rx, 0), min(cx + rx + 1, grid.width)
        y0, y1 = max(cy - ry, 0), min(cy + ry + 1, grid.height)
        if x0 >= x1 or y0 >= y1:
            return None
        ys, xs = np.nonzero(self._occupancy[panel, y0:y1, x0:x1])
        if len(xs) == 0:
            return None
        d2 = ((xs + x0 + 0.5 - fx) * sx) ** 2 + ((ys + y0 + 0.5 - fy) * sy) ** 2
        best = int(np.argmin(d2))
        if d2[best] > HOVER_DISTANCE**2:
            return None
        return int(xs[best] + x0), int(ys[best] + y0)

    def _value(self, array: np.ndarray, labels: list | None, i: int) -> object:
        """Return a hover value as JSON-ready Python."""
        value = array[i].item()
        if labels is not None:
            return labels[value] if value >= 0 else None
        if isinstance(value, float) and math.isnan(value):
            return None
        return value

    def lookup(
        self, panel: int, fx: float, fy: float, sx: float, sy: float, order: list[int]
    ) -> dict | None:
        """Return the row plotly would show under the cursor.

        That is the topmost drawn point under the cursor, or else at the
        nearest occupied pixel within `HOVER_DISTANCE`: of the series there,
        the first in `order`, and of its rows, the one with the largest index.

        Parameters
        ----------
        panel : int
            Panel under the cursor.
        fx, fy : float
            Cursor position in bins: bin ``i`` spans ``[i, i + 1)``.
        sx, sy : float
            Screen pixels per bin along x and y.
        order : list of int
            Series from the top drawn layer down.

        Returns
        -------
        dict or None
            The series, the bin, the row index, the rows in the bin and in
            the whole pixel, and the hover values; None when no point is near.
        """
        pixel = self._nearest_pixel(panel, fx, fy, sx, sy)
        if pixel is None:
            return None
        bx, by = pixel
        bits = int(self._occupancy[panel, by, bx])
        present = [s for s in order if bits >> s & 1]
        if not present:
            present = [s for s in reversed(range(self.grid.n_series)) if bits >> s & 1]
        series = present[0]
        found = {s: self._find(self.grid.pack(panel, s, by, bx)) for s in present}
        i = found[series]
        return {
            "series": series,
            "bx": bx,
            "by": by,
            "row": int(self._index[i]),
            "count": int(self._count[i]),
            "pixel_count": sum(int(self._count[j]) for j in found.values()),
            "values": {
                name: self._value(array, labels, i)
                for name, array, labels in self._columns
            },
        }
