"""Box plots of a numeric column by the levels of a categorical axis: exact quartiles, Tukey's whiskers and the outliers.

A box is the rows of one group (a facet cell, an x level and a series).
Its quartiles are exact, found without sorting every row: a pass counts the
rows of each group in `CELLS` cells of its value range, which tells the cell
holding each wanted rank and the rank within it; a second pass reads only the
values of those cells and sorts them. A cell of more than `CELL_ROWS` rows (a
column whose values gather in one cell, such as one stretched by far
outliers) is cut into cells again over its own range, up to `DEPTH` times,
and a cell whose rows all have one value needs no reading.

In a band of the x axis (`ddviz.compute.bands`), the boxes of the series lie
side by side: the band's width split evenly into a slot per series, each box
`BOX` of its slot.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from ddviz.compute.bands import BAND, level_index

# Columns of the frame `box_stats` reads: the group of a row and its value.
GROUP = "__group"
VALUE = "__value"
_REGION = "__region"
_CELL = "__cell"
_KEY = "__cellkey"

# Cells of a group's value range counted at a time.
CELLS = 65536
# Most rows of a cell whose values are read and sorted; a fuller one is cut
# into cells again over its own range.
CELL_ROWS = 1_000_000
# Most times a cell is cut again; the last cut's cells are read however full.
DEPTH = 3
# Whiskers reach the furthest value within this many interquartile ranges
# of the box (Tukey); the rows beyond are the outliers.
WHISKER = 1.5
# Width of a box as a part of its series' slot of the band.
BOX = 0.8
# How far the outliers spread from the middle of their box, as a part of
# their slot: a quarter of the slot from one side to the other.
OUTLIER_SPREAD = 0.125
# Quartiles of a box.
QUARTILES = (0.25, 0.5, 0.75)


def slot_center(series: pl.Expr | int, n_series: int) -> pl.Expr | float:
    """Return where the slot of a series lies from the middle of its band.

    Parameters
    ----------
    series : polars.Expr or int
        The series' index.
    n_series : int
        Number of series.

    Returns
    -------
    polars.Expr or float
        The offset along the axis.
    """
    # Without series, no row is drawn; the slot only has to exist.
    slot = 2 * BAND / max(n_series, 1)
    return -BAND + slot * (series + 0.5)


def outlier_position(
    x: str, levels: list[str], series: pl.Expr, n_series: int, jitter: pl.Expr
) -> pl.Expr:
    """Return where an outlier lies along a categorical x axis: in the slot of its series, spread by its jitter.

    Parameters
    ----------
    x : str
        The x column.
    levels : list of str
        Its levels.
    series : polars.Expr
        Each row's series index.
    n_series : int
        Number of series.
    jitter : polars.Expr
        Each row's jitter from -1 to 1 (`ddviz.compute.bands`).

    Returns
    -------
    polars.Expr
        The position as Float64.
    """
    slot = 2 * BAND / max(n_series, 1)
    center = level_index(x, levels).cast(pl.Float64)
    return center + slot_center(series, n_series) + slot * OUTLIER_SPREAD * jitter


def _ranks(n: int) -> list[tuple[int, int, float]]:
    """Return, for each quartile of `n` values, the ranks around it and the weight of the upper one (linear, as numpy)."""
    ranks = []
    for q in QUARTILES:
        position = q * (n - 1)
        low = math.floor(position)
        ranks.append((low, min(low + 1, n - 1), position - low))
    return ranks


def _cell(lo: pl.Expr, hi: pl.Expr) -> pl.Expr:
    """Return the cell of each row's value among `CELLS` over its region's range."""
    scaled = (pl.col(VALUE) - lo) * (CELLS / (hi - lo))
    return scaled.floor().clip(0, CELLS - 1).cast(pl.Int64)


class _Regions:
    """Rows of the value ranges being searched: a group at first, then a cell of one cut again.

    `frame` gives each row of a region its id (`_REGION`); `bounds` holds
    the smallest and largest value of each region.
    """

    def __init__(
        self, frame: pl.LazyFrame, bounds: dict[int, tuple[float, float]]
    ) -> None:
        self.frame = frame
        self.bounds = bounds

    def cells(self) -> pl.LazyFrame:
        """Return the rows of the regions with their cell (`_CELL`)."""
        ids = sorted(self.bounds)
        size = ids[-1] + 1
        lo = [0.0] * size
        hi = [1.0] * size
        for r, (a, b) in self.bounds.items():
            lo[r], hi[r] = a, b
        region = pl.col(_REGION)
        cell = _cell(
            pl.lit(pl.Series(lo, dtype=pl.Float64)).gather(region),
            pl.lit(pl.Series(hi, dtype=pl.Float64)).gather(region),
        )
        return self.frame.filter(region.is_in(ids)).with_columns(cell.alias(_CELL))

    def cut(self, cells: dict[tuple[int, int], tuple[float, float]]) -> _Regions:
        """Return the regions of the given cells of these regions, numbered from 0, over their own ranges."""
        keys = [r * CELLS + c for r, c in cells]
        frame = (
            self.cells()
            .with_columns((pl.col(_REGION) * CELLS + pl.col(_CELL)).alias(_KEY))
            .filter(pl.col(_KEY).is_in(keys))
            .with_columns(
                pl.col(_KEY)
                .replace_strict(keys, list(range(len(keys))), return_dtype=pl.Int64)
                .alias(_REGION)
            )
            .drop(_KEY, _CELL)
        )
        return _Regions(frame, dict(enumerate(cells.values())))


def _ranked_values(
    frame: pl.LazyFrame,
    wanted: dict[int, set[int]],
    bounds: dict[int, tuple[float, float]],
) -> dict[tuple[int, int], float]:
    """Return the value at each wanted rank of each group's sorted values.

    Parameters
    ----------
    frame : polars.LazyFrame
        Rows with `GROUP` and `VALUE`.
    wanted : dict of int to set of int
        Ranks (from 0) of each group.
    bounds : dict of int to tuple of float
        Smallest and largest value of each group.

    Returns
    -------
    dict
        The value of each ``(group, rank)``.
    """
    found: dict[tuple[int, int], float] = {}
    # Each target: (group, rank) it answers, its region, its rank there.
    targets = []
    for g, ranks in wanted.items():
        for k in ranks:
            if bounds[g][0] == bounds[g][1]:
                found[(g, k)] = bounds[g][0]
            else:
                targets.append(((g, k), g, k))
    regions = _Regions(
        frame.with_columns(pl.col(GROUP).alias(_REGION)),
        {g: bounds[g] for _, g, _ in targets},
    )
    for depth in range(DEPTH + 1):
        if not targets:
            break
        counts = (
            regions.cells()
            .group_by(_REGION, _CELL)
            .agg(
                pl.len().alias("n"),
                pl.col(VALUE).min().alias("lo"),
                pl.col(VALUE).max().alias("hi"),
            )
            .sort(_REGION, _CELL)
            .collect(engine="streaming")
        )
        region_of = counts[_REGION].to_numpy()
        cell_of = counts[_CELL].to_numpy()
        rows = counts["n"].to_numpy().astype(np.int64)
        lows, highs = counts["lo"].to_numpy(), counts["hi"].to_numpy()
        read: dict[tuple[int, int], list] = {}
        again: dict[tuple[int, int], list] = {}
        for answer, r, k in targets:
            first = int(np.searchsorted(region_of, r, side="left"))
            last = int(np.searchsorted(region_of, r, side="right"))
            ends = np.cumsum(rows[first:last])
            j = int(np.searchsorted(ends, k, side="right"))
            i = first + j
            rank = k - int(ends[j] - rows[i])
            key = (r, int(cell_of[i]))
            if lows[i] == highs[i]:
                found[answer] = float(lows[i])
            elif rows[i] <= CELL_ROWS or depth == DEPTH:
                read.setdefault(key, []).append((answer, rank))
            else:
                again.setdefault(key, []).append((answer, rank, lows[i], highs[i]))
        if read:
            keys = [r * CELLS + c for r, c in read]
            values = (
                regions.cells()
                .select((pl.col(_REGION) * CELLS + pl.col(_CELL)).alias(_KEY), VALUE)
                .filter(pl.col(_KEY).is_in(keys))
                .sort(_KEY, VALUE)
                .collect(engine="streaming")
            )
            key_of = values[_KEY].to_numpy()
            value_of = values[VALUE].to_numpy()
            for (r, c), asked in read.items():
                start = np.searchsorted(key_of, r * CELLS + c, side="left")
                for answer, rank in asked:
                    found[answer] = float(value_of[start + rank])
        if not again:
            break
        cells = {key: (float(a[0][2]), float(a[0][3])) for key, a in again.items()}
        targets = [
            (answer, new, rank)
            for new, asked in enumerate(again.values())
            for answer, rank, _, _ in asked
        ]
        regions = regions.cut(cells)
    return found


def fences(stats: dict[int, list[float]], n_groups: int) -> tuple[pl.Series, pl.Series]:
    """Return the bounds beyond which a row of each group is an outlier.

    Parameters
    ----------
    stats : dict of int to list of float
        Each group's ``[n, low, q1, median, q3, high]`` (`box_stats`).
    n_groups : int
        Number of groups.

    Returns
    -------
    tuple of polars.Series
        The lower and upper fence of each group, NaN for a group without
        rows (no row of it is an outlier).
    """
    lo = [math.nan] * n_groups
    hi = [math.nan] * n_groups
    for g, (_, _, q1, _, q3, _) in stats.items():
        lo[g] = q1 - WHISKER * (q3 - q1)
        hi[g] = q3 + WHISKER * (q3 - q1)
    return pl.Series(lo, dtype=pl.Float64), pl.Series(hi, dtype=pl.Float64)


def is_outlier(
    value: pl.Expr, group: pl.Expr, bounds: tuple[pl.Series, pl.Series]
) -> pl.Expr:
    """Return whether each row's value lies beyond its group's fences (`fences`).

    Parameters
    ----------
    value : polars.Expr
        The value, Float64.
    group : polars.Expr
        The group.
    bounds : tuple of polars.Series
        The fences.

    Returns
    -------
    polars.Expr
        The condition.
    """
    lo, hi = bounds
    return (value < pl.lit(lo).gather(group)) | (value > pl.lit(hi).gather(group))


def box_stats(frame: pl.LazyFrame) -> dict[int, list[float]]:
    """Return the box of each group of rows.

    Parameters
    ----------
    frame : polars.LazyFrame
        The rows drawn, with their group (`GROUP`, Int64 from 0) and a
        finite value (`VALUE`, Float64).

    Returns
    -------
    dict of int to list of float
        For each group with rows, ``[n, low, q1, median, q3, high]``: the
        rows, the quartiles (linear between ranks, as numpy's), and the
        ends of the whiskers, the furthest values within `WHISKER`
        interquartile ranges of the box.
    """
    groups = (
        frame.group_by(GROUP)
        .agg(
            pl.len().alias("n"),
            pl.col(VALUE).min().alias("lo"),
            pl.col(VALUE).max().alias("hi"),
        )
        .collect(engine="streaming")
    )
    if groups.height == 0:
        return {}
    sizes = dict(zip(groups[GROUP].to_list(), groups["n"].to_list(), strict=True))
    bounds = {g: (lo, hi) for g, lo, hi in groups.select(GROUP, "lo", "hi").iter_rows()}
    ranks = {g: _ranks(n) for g, n in sizes.items()}
    wanted = {
        g: {k for low, high, _ in rs for k in (low, high)} for g, rs in ranks.items()
    }
    values = _ranked_values(frame, wanted, bounds)
    stats = {}
    for g, rs in ranks.items():
        q = [
            values[(g, low)] + w * (values[(g, high)] - values[(g, low)])
            for low, high, w in rs
        ]
        stats[g] = [sizes[g], math.nan, *q, math.nan]
    n_groups = max(stats) + 1
    lo, hi = fences(stats, n_groups)
    group, value = pl.col(GROUP), pl.col(VALUE)
    whiskers = (
        frame.with_columns(
            pl.when(value >= pl.lit(lo).gather(group)).then(value).alias("low"),
            pl.when(value <= pl.lit(hi).gather(group)).then(value).alias("high"),
        )
        .group_by(GROUP)
        .agg(pl.col("low").min(), pl.col("high").max())
        .collect(engine="streaming")
    )
    for g, low, high in whiskers.iter_rows():
        stats[g][1], stats[g][5] = low, high
    return stats
