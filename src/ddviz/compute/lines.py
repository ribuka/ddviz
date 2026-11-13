"""Lines joining the points of each series, rasterized into layers of the panels' pixels.

A series is the rows of one pair of axis columns, facet cell and color
level (the color column's level, not the symbol's; one for a gradient or
no color column). Its rows are joined in the order of x, then of the row
index; a row whose y (or, on a log axis, x) has no position breaks the
line there, and the view leaves the order as it is: a segment crossing the
panel is cut at its edges.

The page gets no rows or segments, only a PNG of every panel per color
level, as the points' images: the lines are drawn here at the pixels of
the bins. Within one pixel column, the segments between the rows of a run
there cover the column from their least to their largest y, whatever their
number (the M4 reduction of time-series plots): the work after the sort
grows with the panels' width, not the rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

# Columns of the frame `line_frame` returns.
GROUP = "__line_group"
X = "__line_x"
Y = "__line_y"
LAYER = "__line_layer"
VALUE = "__line_value"
# Rows `line_pixels` turns into pixels at a time: its arrays of every row
# would take about 200 bytes a row.
CHUNK_ROWS = 1_000_000


@dataclass(frozen=True)
class LinePixels:
    """The pixels the lines cover before their width (`line_pixels`).

    Parameters
    ----------
    pixel : numpy.ndarray
        Flat position of each covered pixel in an array of shape
        ``(n_panels, height, width)`` (`ddviz.compute.raster.pixels`).
    layer : numpy.ndarray
        The layer of each: the color level of the row its segment starts
        from.
    rank : numpy.ndarray
        The place of that row in the order the lines join the rows, from 1:
        a pixel of several segments takes the color of the last.
    """

    pixel: np.ndarray
    layer: np.ndarray
    rank: np.ndarray

    @classmethod
    def empty(cls) -> LinePixels:
        """Return the pixels of no line."""
        return cls(np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64))

    @classmethod
    def concat(cls, parts: list[LinePixels]) -> LinePixels:
        """Return the pixels of several parts as one."""
        if not parts:
            return cls.empty()
        return cls(
            np.concatenate([p.pixel for p in parts]),
            np.concatenate([p.layer for p in parts]),
            np.concatenate([p.rank for p in parts]),
        )


def line_frame(
    rows: pl.LazyFrame,
    x_col: str,
    y_col: str,
    panel: pl.Expr,
    series: pl.Expr,
    n_series: int,
    layer: pl.Expr,
    index: str,
    value: pl.Expr | None = None,
) -> pl.LazyFrame:
    """Return the rows of a pair's lines, in the order they are joined.

    Parameters
    ----------
    rows : polars.LazyFrame
        The drawn rows that pass the local filter, with their row index.
    x_col, y_col : str
        The pair's columns.
    panel : polars.Expr
        Each row's panel.
    series : polars.Expr
        Each row's series among those of its panel: its color level, or 0
        for a gradient.
    n_series : int
        Series a panel may have.
    layer : polars.Expr
        Each row's layer: its color level.
    index : str
        Column of the row index, which orders the rows of one x.
    value : polars.Expr, optional
        A value each row keeps (`VALUE`): a gradient's color.

    Returns
    -------
    polars.LazyFrame
        `GROUP` (``panel * n_series + series``), `X` and `Y` (the values,
        as floats) and `LAYER`, and `VALUE` when asked, sorted by group, x
        and row. Rows of an x that cannot be ordered (null, NaN or
        infinite) are left out. The frame takes 22 bytes a row (and 8 more
        for `VALUE`).
    """
    x = pl.col(x_col).cast(pl.Float64)
    columns = [
        (panel.cast(pl.Int32) * n_series + series.cast(pl.Int32)).alias(GROUP),
        x.alias(X),
        pl.col(index),
        pl.col(y_col).cast(pl.Float64).alias(Y),
        layer.cast(pl.Int16).alias(LAYER),
    ]
    if value is not None:
        columns.append(value.alias(VALUE))
    return (
        rows.filter(x.is_finite()).select(columns).sort([GROUP, X, index]).drop(index)
    )


def _clip(
    x0: np.ndarray,
    y0: np.ndarray,
    x1: np.ndarray,
    y1: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, ...]:
    """Cut segments at the edges of a panel (Liang-Barsky); return which cross it and their ends there."""
    dx, dy = x1 - x0, y1 - y0
    t0 = np.zeros(len(x0))
    t1 = np.ones(len(x0))
    keep = np.ones(len(x0), dtype=bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        for p, q in ((-dx, x0), (dx, width - x0), (-dy, y0), (dy, height - y0)):
            r = q / p
            keep &= ~((p == 0) & (q < 0))
            t0 = np.where(p < 0, np.maximum(t0, r), t0)
            t1 = np.where(p > 0, np.minimum(t1, r), t1)
    keep &= t0 <= t1
    return (
        keep,
        x0 + t0 * dx,
        y0 + t0 * dy,
        x0 + t1 * dx,
        y0 + t1 * dy,
    )


def _ranges(lengths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return, for items of the given lengths laid end to end, the item and the step within it of each."""
    item = np.repeat(np.arange(len(lengths)), lengths)
    starts = np.cumsum(lengths) - lengths
    return item, np.arange(int(lengths.sum())) - starts[item]


def _position(
    values: np.ndarray, log: bool, bounds: tuple[float, float], n: int
) -> np.ndarray:
    """Return the positions of values in pixels over `bounds` split into `n`; NaN for none.

    On a log axis, a value that is not positive has no position, as
    `ddviz.compute.axisposition.position` makes it.
    """
    if log:
        with np.errstate(divide="ignore", invalid="ignore"):
            values = np.where(values > 0, np.log10(values), np.nan)
    lo, hi = bounds
    return (values - lo) * (n / (hi - lo))


def line_pixels(
    frame: pl.DataFrame,
    x_log: bool,
    y_log: bool,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    width: int,
    height: int,
    n_series: int,
) -> LinePixels:
    """Return the pixels the lines of a pair cover, one pixel wide.

    The rows are taken `CHUNK_ROWS` at a time, each chunk starting at the
    last row of the one before: the segment between the chunks is drawn
    once, and a pixel column cut between them is covered by its two parts.

    Parameters
    ----------
    frame : polars.DataFrame
        The rows as `line_frame` returns them.
    x_log, y_log : bool
        Whether the pair's columns lie on log axes: a value not positive
        has no position there, and breaks the line.
    x_range, y_range : tuple of float
        The panel's ranges, as positions (`ddviz.compute.axisposition`).
    width, height : int
        Pixels of a panel.
    n_series : int
        Series a panel may have, as `line_frame` got them.

    Returns
    -------
    LinePixels
        The pixels; the ranks are the rows' places in `frame`, from 1.
    """
    parts = []
    n = frame.height
    for start in range(0, max(n - 1, 0), CHUNK_ROWS):
        rows = frame.slice(start, CHUNK_ROWS + 1)

        found = _pixels(
            rows[GROUP].to_numpy(),
            _position(rows[X].to_numpy(), x_log, x_range, width),
            _position(rows[Y].to_numpy(), y_log, y_range, height),
            rows[LAYER].to_numpy(),
            width,
            height,
            n_series,
        )
        parts.append(LinePixels(found.pixel, found.layer, found.rank + start))
    return LinePixels.concat(parts)


def _pixels(
    group: np.ndarray,
    px: np.ndarray,
    py: np.ndarray,
    layer: np.ndarray,
    width: int,
    height: int,
    n_series: int,
) -> LinePixels:
    """Return the pixels the lines of consecutive rows of `line_frame` cover, at their positions in pixels (`line_pixels`); the ranks are their places, from 1."""
    n = len(group)
    if n < 2:
        return LinePixels.empty()
    panel = group.astype(np.int64) // n_series
    valid = np.isfinite(px) & np.isfinite(py)
    # A run starts at a new series and after a row without a position.
    start = np.ones(n, dtype=bool)
    start[1:] = (group[1:] != group[:-1]) | ~valid[:-1]
    kept = np.flatnonzero(valid)
    if len(kept) < 2:
        return LinePixels.empty()
    run = np.cumsum(start)[kept]
    x, y = px[kept], py[kept]
    # The pixel column; the rows left and right of the panel make one
    # column each, whose segments cross nothing but at their ends.
    column = np.where(
        x < 0,
        -1,
        np.where(x > width, width, np.clip(np.floor(x), 0, width - 1)),
    ).astype(np.int64)
    # A cell: the rows of one run in one pixel column, one after another.
    new = np.ones(len(kept), dtype=bool)
    new[1:] = (run[1:] != run[:-1]) | (column[1:] != column[:-1])
    first = np.flatnonzero(new)
    last = np.append(first[1:], len(kept)) - 1
    pixels, layers, ranks = [], [], []

    def add(
        at_panel: np.ndarray, row: np.ndarray, col: np.ndarray, src: np.ndarray
    ) -> None:
        rows_at = np.clip(np.floor(row), 0, height - 1).astype(np.int64)
        cols_at = np.clip(np.floor(col), 0, width - 1).astype(np.int64)
        pixels.append((at_panel * height + rows_at) * width + cols_at)
        layers.append(layer[src])
        ranks.append(src + 1)

    # The segments within a cell cover its column from its least to its
    # largest y; each takes the color of the last of them (its row before
    # the last).
    lo = np.minimum.reduceat(y, first)
    hi = np.maximum.reduceat(y, first)
    span = (
        (last > first)
        & (column[first] >= 0)
        & (column[first] < width)
        & (hi >= 0)
        & (lo <= height)
    )
    if span.any():
        r0 = np.clip(np.floor(lo[span]), 0, height - 1).astype(np.int64)
        r1 = np.clip(np.floor(hi[span]), 0, height - 1).astype(np.int64)
        item, step = _ranges(r1 - r0 + 1)
        src = kept[last[span] - 1][item]
        add(
            panel[src],
            (r0[item] + step).astype(np.float64),
            column[first[span]][item].astype(np.float64),
            src,
        )
    # The segment from the last row of a cell to the first of the next one
    # of its run, cut at the panel's edges.
    joined = run[last[:-1]] == run[first[1:]]
    a, b = last[:-1][joined], first[1:][joined]
    keep, x0, y0, x1, y1 = _clip(x[a], y[a], x[b], y[b], width, height)
    a, x0, y0, x1, y1 = a[keep], x0[keep], y0[keep], x1[keep], y1[keep]
    if len(a):
        # Steps of at most half a pixel along the longer side.
        length = np.maximum(np.abs(x1 - x0), np.abs(y1 - y0))
        steps = np.ceil(length * 2).astype(np.int64) + 1
        item, step = _ranges(steps)
        t = step / np.maximum(steps[item] - 1, 1)
        src = kept[a][item]
        add(
            panel[src],
            y0[item] + t * (y1 - y0)[item],
            x0[item] + t * (x1 - x0)[item],
            src,
        )
    if not pixels:
        return LinePixels.empty()
    return LinePixels(
        np.concatenate(pixels), np.concatenate(layers), np.concatenate(ranks)
    )


def stroke(line_width: int) -> np.ndarray:
    """Return the pen the one-pixel lines are widened with: a disk of `line_width` pixels across.

    Parameters
    ----------
    line_width : int
        Width of the lines in pixels, at least 1.

    Returns
    -------
    numpy.ndarray
        Boolean array of shape ``(line_width, line_width)``, as the markers
        of `ddviz.shared.shapes.marker`.
    """
    center = (line_width - 1) / 2
    d = np.arange(line_width) - center
    return d[:, None] ** 2 + d[None, :] ** 2 <= (line_width / 2) ** 2 + 1e-9
