"""Looks up the row under the cursor in the hover files a plot task wrote."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ddviz.shared.manifest import GRAYS, PlotManifest
from ddviz.shared.shapes import kernel

# Hover distance in screen pixels, as plotly's default `hoverdistance`.
HOVER_DISTANCE = 20
# Cap on the search window in bins, for views zoomed out so far that a bin
# is much smaller than a pixel.
_MAX_WINDOW = 256


class HoverIndex:
    """Memory-mapped hover files of one plot task.

    A result without hover files (`PlotManifest.hover_files`) finds no row.

    Parameters
    ----------
    out : pathlib.Path
        The task's output directory.
    """

    def __init__(self, out: Path) -> None:
        self.out = out
        self.manifest = PlotManifest.read(out)
        self.grid = self.manifest.grid
        self._columns = []
        if not self.manifest.hover_files:
            self._keys = self._count = self._index = self._occupancy = None
            return
        self._keys = np.load(out / "keys.npy", mmap_mode="r")
        self._count = np.load(out / "count.npy", mmap_mode="r")
        self._index = np.load(out / "index.npy", mmap_mode="r")
        self._occupancy = np.load(out / "occupancy.npy", mmap_mode="r")
        self._columns = [
            (c.name, np.load(out / c.file, mmap_mode="r"), c.labels)
            for c in self.manifest.columns
        ]
        # The marker shape of each overlay level, rows from the bottom as
        # the bins: a series' points cover the bins of their shape.
        spec = self.manifest.spec
        self._shapes = []
        if spec.overlay is not None:
            levels = self.manifest.levels["overlay"]
            self._shapes = [
                kernel(i, spec.shape_size)[::-1] for i in range(len(levels))
            ]
        # A gradient's grays, which decide which of a series' overlapping
        # shapes shows.
        self._grays = None
        if (out / GRAYS).exists():
            self._grays = np.load(out / GRAYS, mmap_mode="r")

    def close(self) -> None:
        """Drop the memory maps, so that the files can be deleted."""
        self._keys = self._count = self._index = self._occupancy = None
        self._columns = []
        self._grays = None

    def _series_at(self, panel: int, by: int, bx: int) -> dict[int, int]:
        """Return the position of the key of each series with rows at an occupied pixel."""
        series = np.arange(self.grid.n_series)
        keys = self.grid.pack(panel, series, by, bx)
        found = np.searchsorted(self._keys, keys)
        inside = found < len(self._keys)
        hit = np.zeros(len(keys), dtype=bool)
        hit[inside] = self._keys[found[inside]] == keys[inside]
        return {int(s): int(i) for s, i in zip(series[hit], found[hit], strict=True)}

    def _covering(
        self, panel: int, fx: float, fy: float, order: list[int]
    ) -> tuple[int, int, int] | None:
        """Return the bin and series of the topmost marker shape that covers the cursor's bin, or None.

        Of the series whose shapes cover it, the first in `order` (else the
        last series) wins, and of its bins, the one drawn there
        (`ddviz.compute.shapes.spread`): the cursor's own bin, else for a
        gradient the one of the largest gray; then the one whose row has the
        largest index.
        """
        grid = self.grid
        cx, cy = math.floor(fx), math.floor(fy)
        if not (0 <= cx < grid.width and 0 <= cy < grid.height):
            return None
        half = self._shapes[0].shape[0] // 2
        x0, y0 = max(cx - half, 0), max(cy - half, 0)
        x1, y1 = min(cx + half + 1, grid.width), min(cy + half + 1, grid.height)
        rank = {s: i for i, s in enumerate(order)}
        best = None
        for py, px in np.argwhere(self._occupancy[panel, y0:y1, x0:x1]):
            by, bx = int(py) + y0, int(px) + x0
            for s, i in self._series_at(panel, by, bx).items():
                shape = self._shapes[s % len(self._shapes)]
                # A point keeps its own bin, even inside an outline.
                own = (by, bx) == (cy, cx)
                if not (own or shape[cy - by + half, cx - bx + half]):
                    continue
                score = (
                    -rank.get(s, len(order) + grid.n_series - s),
                    own,
                    self._gray(i),
                    int(self._index[i]),
                )
                if best is None or score > best[0]:
                    best = (score, bx, by, s)
        return None if best is None else best[1:]

    def _gray(self, i: int) -> int:
        """Return the gray a gradient's bin is drawn in (`ddviz.compute.tasks.images.gradient_grays`), or 0."""
        return 0 if self._grays is None else int(self._grays[i])

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
        With an overlay, a point is drawn as its marker shape: the topmost
        shape covering the cursor answers (`_covering`).

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
        if self._occupancy is None:
            return None
        covering = self._covering(panel, fx, fy, order) if self._shapes else None
        if covering is not None:
            bx, by, series = covering
            found = self._series_at(panel, by, bx)
        else:
            pixel = self._nearest_pixel(panel, fx, fy, sx, sy)
            if pixel is None:
                return None
            bx, by = pixel
            found = self._series_at(panel, by, bx)
            series = next((s for s in order if s in found), max(found))
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
