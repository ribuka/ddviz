"""Looks up the row under the cursor in the hover files a plot task wrote, and the piles it drew."""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np

from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import ONE_BAND
from ddviz.shared.shapes import marker

# Hover distance in screen pixels, as plotly's default `hoverdistance`.
HOVER_DISTANCE = 20
# Cap on the search window in bins, for views zoomed out so far that a bin
# is much smaller than a pixel.
_MAX_WINDOW = 256
# Most keys matched at once when the hover passes over the hidden series:
# about 8MB of keys, so that 10,000 series by the bins near the cursor do
# not take hundreds of MB.
_MAX_KEYS_AT_ONCE = 2**20


class HoverIndex:
    """Memory-mapped hover files of one plot task.

    A result without hover files (`PlotManifest.hover_files`) finds no row.
    The files of its piles (`PlotManifest.piles`) are open whatever the
    hover files.

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
        self._piles: dict[str, np.ndarray] = {}
        self._pile_columns = []
        if self.manifest.piles:
            names = ["pixel", "n", "start", "series", "series_n"]
            if self.manifest.spec.gradient:
                names += ["min", "max"]
            self._piles = {
                name: np.load(out / f"pile_{name}.npy", mmap_mode="r") for name in names
            }
            self._pile_columns = [
                (c.name, np.load(out / c.file, mmap_mode="r"), c.labels)
                for c in self.manifest.pile_columns
            ]
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
        # The marker of each overlay level, in its size, or the circle
        # without an overlay, rows from the bottom as the bins: a series'
        # points cover the bins of their marker (`ddviz.compute.shapes`).
        spec = self.manifest.spec
        levels = self.manifest.levels["overlay"]
        self._shapes = [
            marker(shape, size)[::-1]
            for shape, size in zip(
                spec.marker_shapes(levels), spec.marker_sizes(levels), strict=True
            )
        ]

    def close(self) -> None:
        """Drop the memory maps, so that the files can be deleted."""
        self._keys = self._count = self._index = self._occupancy = None
        self._columns = []
        self._piles = {}
        self._pile_columns = []

    def piles(self) -> dict:
        """Return the piles the page draws: where each lies, its rows and its series.

        Returns
        -------
        dict
            Lists of the same length, one item per pile: its ``panel``, its
            bins ``bx`` and ``by``, its rows ``n``, and the ``series`` of
            its rows (the pile is drawn faded when all are inactive).
        """
        if not self._piles:
            return {"panel": [], "bx": [], "by": [], "n": [], "series": []}
        rest, bx = np.divmod(np.asarray(self._piles["pixel"]), self.grid.width)
        panel, by = np.divmod(rest, self.grid.height)
        start = np.asarray(self._piles["start"])
        series = np.asarray(self._piles["series"])
        return {
            "panel": panel.tolist(),
            "bx": bx.tolist(),
            "by": by.tolist(),
            "n": np.asarray(self._piles["n"]).tolist(),
            "series": [
                series[a:b].tolist() for a, b in itertools.pairwise(start.tolist())
            ],
        }

    def pile(self, i: int) -> dict | None:
        """Return what the hover shows of a pile: its values, its rows, and its rows by series.

        Parameters
        ----------
        i : int
            The pile, in the order of `piles`.

        Returns
        -------
        dict or None
            The values of the panel's x and y columns (``values``), the
            rows (``n``), the rows by series (``series``: ``[series, rows]``
            each) and, for a gradient, the least and largest color
            (``color_range``); None for no such pile.
        """
        if not self._piles or not 0 <= i < len(self._piles["n"]):
            return None
        panel = int(self._piles["pixel"][i]) // (self.grid.width * self.grid.height)
        xi, yj = self.manifest.axes.axes(panel)
        spec = self.manifest.spec
        own = {spec.x[xi], spec.y[yj]} - {ONE_BAND}
        a, b = int(self._piles["start"][i]), int(self._piles["start"][i + 1])
        series = self._piles["series"][a:b].tolist()
        rows = self._piles["series_n"][a:b].tolist()
        color_range = None
        if "min" in self._piles:
            color_range = [
                self._value(self._piles["min"], None, i),
                self._value(self._piles["max"], None, i),
            ]
        return {
            "values": {
                name: self._value(array, labels, i)
                for name, array, labels in self._pile_columns
                if name in own
            },
            "n": int(self._piles["n"][i]),
            "series": [[s, n] for s, n in zip(series, rows, strict=True)],
            "color_range": color_range,
        }

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
        self, panel: int, fx: float, fy: float, order: list[int], hidden: frozenset[int]
    ) -> tuple[int, int, int] | None:
        """Return the bin and series of the topmost marker that covers the cursor's bin, or None.

        Of the series whose markers cover it, not in `hidden`, the first in
        `order` (else the last series) wins, and of its bins, the one drawn
        on top (`ddviz.compute.shapes.spread_top`): the one whose row has the
        largest index.
        """
        grid = self.grid
        cx, cy = math.floor(fx), math.floor(fy)
        if not (0 <= cx < grid.width and 0 <= cy < grid.height):
            return None
        half = max(shape.shape[0] for shape in self._shapes) // 2
        x0, y0 = max(cx - half, 0), max(cy - half, 0)
        x1, y1 = min(cx + half + 1, grid.width), min(cy + half + 1, grid.height)
        rank = {s: i for i, s in enumerate(order)}
        best = None
        for py, px in np.argwhere(self._occupancy[panel, y0:y1, x0:x1]):
            by, bx = int(py) + y0, int(px) + x0
            for s, i in self._series_at(panel, by, bx).items():
                if s in hidden:
                    continue
                shape = self._shapes[s % len(self._shapes)]
                h = shape.shape[0] // 2
                dy, dx = cy - by + h, cx - bx + h
                if not (0 <= dy < len(shape) and 0 <= dx < len(shape)):
                    continue
                if not shape[dy, dx]:
                    continue
                score = (
                    -rank.get(s, len(order) + grid.n_series - s),
                    int(self._index[i]),
                )
                if best is None or score > best[0]:
                    best = (score, bx, by, s)
        return None if best is None else best[1:]

    def _nearest_pixel(
        self,
        panel: int,
        fx: float,
        fy: float,
        sx: float,
        sy: float,
        hidden: frozenset[int],
    ) -> tuple[int, int] | None:
        """Return the bin nearest the cursor within the hover distance with rows of a series not in `hidden`."""
        grid = self.grid
        cx, cy = math.floor(fx), math.floor(fy)
        if (
            0 <= cx < grid.width
            and 0 <= cy < grid.height
            and self._occupancy[panel, cy, cx]
            and self._series_at(panel, cy, cx).keys() - hidden
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
        near = d2 <= HOVER_DISTANCE**2
        xs, ys, d2 = xs[near] + x0, ys[near] + y0, d2[near]
        if hidden:
            return self._nearest_shown(panel, xs, ys, d2, hidden)
        if len(d2) == 0:
            return None
        best = int(np.argmin(d2))
        return int(xs[best]), int(ys[best])

    def _nearest_shown(
        self,
        panel: int,
        xs: np.ndarray,
        ys: np.ndarray,
        d2: np.ndarray,
        hidden: frozenset[int],
    ) -> tuple[int, int] | None:
        """Return the nearest of the bins `xs`, `ys` (squared distances `d2`) with rows of a series not in `hidden`.

        The bins are matched nearest first, a chunk at a time, so that the
        keys of the shown series by the bins never take more than
        `_MAX_KEYS_AT_ONCE` at once (up to 10,000 series by some hundred bins).
        """
        grid = self.grid
        shown = np.setdiff1d(np.arange(grid.n_series), list(hidden))
        if len(shown) == 0:
            return None
        order = np.argsort(d2, kind="stable")
        step = max(1, _MAX_KEYS_AT_ONCE // len(shown))
        last = len(self._keys) - 1
        for start in range(0, len(order), step):
            chunk = order[start : start + step]
            keys = grid.pack(panel, shown[:, None], ys[chunk], xs[chunk])
            found = np.searchsorted(self._keys, keys).clip(max=last)
            keep = np.flatnonzero((self._keys[found] == keys).any(axis=0))
            if len(keep):
                best = chunk[keep[0]]
                return int(xs[best]), int(ys[best])
        return None

    def _value(self, array: np.ndarray, labels: list | None, i: int) -> object:
        """Return a hover value as JSON-ready Python."""
        value = array[i].item()
        if labels is not None:
            return labels[value] if value >= 0 else None
        if isinstance(value, float) and math.isnan(value):
            return None
        return value

    def lookup(
        self,
        panel: int,
        fx: float,
        fy: float,
        sx: float,
        sy: float,
        order: list[int],
        hidden: frozenset[int] = frozenset(),
    ) -> dict | None:
        """Return the row plotly would show under the cursor.

        That is the topmost drawn point under the cursor, or else at the
        nearest occupied pixel within `HOVER_DISTANCE`: of the series there,
        the first in `order`, and of its rows, the one with the largest index.
        A point is drawn as its marker (`ddviz.shared.shapes.marker`): the
        topmost marker covering the cursor answers (`_covering`).

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
        hidden : frozenset of int, optional
            Series drawn invisible (inactive at opacity 0): their points
            never answer, as if they had no rows.

        Returns
        -------
        dict or None
            The series, the bin, the row index, the rows in the bin and in
            the whole pixel, and the hover values; None when no point is near.
        """
        if self._occupancy is None:
            return None
        covering = self._covering(panel, fx, fy, order, hidden)
        if covering is not None:
            bx, by, series = covering
            found = self._series_at(panel, by, bx)
        else:
            pixel = self._nearest_pixel(panel, fx, fy, sx, sy, hidden)
            if pixel is None:
                return None
            bx, by = pixel
            found = self._series_at(panel, by, bx)
            shown = found.keys() - hidden
            series = next((s for s in order if s in shown), max(shown))
        i = found[series]
        return {
            "series": series,
            "bx": bx,
            "by": by,
            "row": int(self._index[i]),
            "count": int(self._count[i]),
            "pixel_count": sum(
                int(self._count[j]) for s, j in found.items() if s not in hidden
            ),
            "values": {
                name: self._value(array, labels, i)
                for name, array, labels in self._columns
            },
        }
