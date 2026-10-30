"""Positions of rows on categorical axes: a band per level, the points spread by density.

Level ``i`` of a categorical axis column is the band centered on position
``i`` (the axis spans ``-0.5`` to ``n - 0.5``). A row lies at
``i + BAND * width * jitter``: the jitter comes from its row index, so that a
row keeps its place over zooms, sizes and processes; the width, from 0 to 1,
grows with the rows of its level near its value on the other axis
(`Spread`), like the outline of a violin. The aggregation then bins the
positions as it bins a numeric column.
"""

from __future__ import annotations

import polars as pl

from ddviz.shared.scatter import Spread

# Half the width of a band, as a part of the step between levels.
BAND = 0.4
# Cells of the numeric axis that the widths are counted in.
SPREAD_CELLS = 128
# Steps of the jitter by row index: the golden ratio's along a categorical
# axis, and another irrational's along y when both axes are categorical,
# so that the two do not line up.
JITTER_X = 0.6180339887498949
JITTER_Y = 0.41421356237309515


def band_range(levels: list) -> tuple[float, float]:
    """Return the data range of a categorical axis: its bands and nothing more.

    Parameters
    ----------
    levels : list
        The axis column's levels.

    Returns
    -------
    tuple of float
        ``(-0.5, n - 0.5)``; ``(-0.5, 0.5)`` without levels.
    """
    return (-0.5, max(len(levels), 1) - 0.5)


def level_index(column: str, levels: list[str]) -> pl.Expr:
    """Return the index of each row's level of a categorical column, null for a null value.

    Parameters
    ----------
    column : str
        The column.
    levels : list of str
        Its levels as text; every value of the column must be one.

    Returns
    -------
    polars.Expr
        The index as Int64.
    """
    # An Enum cast streams; replace_strict on 100M rows took over 9GB.
    return (
        pl.col(column)
        .cast(pl.String)
        .cast(pl.Enum(levels))
        .to_physical()
        .cast(pl.Int64)
    )


def _cell(column: str, bounds: list[float]) -> pl.Expr:
    """Return the cell of a numeric column among `SPREAD_CELLS` over `bounds`; 0 when it is not finite."""
    lo, hi = bounds
    value = pl.col(column).cast(pl.Float64)
    cell = ((value - lo) * (SPREAD_CELLS / (hi - lo))).floor().clip(0, SPREAD_CELLS - 1)
    # A row whose value is not finite is not drawn; its cell only has to exist.
    return pl.when(value.is_finite()).then(cell).otherwise(0).cast(pl.Int64)


def _cells(
    x: str, y: str, categorical: set[str], axis_levels: dict, bounds: list[float] | None
) -> pl.Expr:
    """Return the flat cell of each row in the widths of a pair (`Spread.widths`)."""
    if x in categorical and y in categorical:
        return level_index(x, axis_levels[x]) * len(axis_levels[y]) + level_index(
            y, axis_levels[y]
        )
    level, other = (x, y) if x in categorical else (y, x)
    return level_index(level, axis_levels[level]) * SPREAD_CELLS + _cell(other, bounds)


def count_spread(
    frame: pl.LazyFrame,
    x: str,
    y: str,
    categorical: set[str],
    axis_levels: dict[str, list[str]],
    bounds: list[float] | None,
) -> Spread:
    """Return the spread of a pair, counting the rows of `frame` in each cell.

    With one categorical axis, a cell's width is the square root of its
    rows over those of the fullest cell of its level, so that a level of
    few rows still spreads; with two, over those of the fullest cell.

    Parameters
    ----------
    frame : polars.LazyFrame
        The drawn rows, with the pair's columns.
    x, y : str
        The pair's columns.
    categorical : set of str
        The axis columns that are categorical; `x` or `y` at least.
    axis_levels : dict
        Levels of each categorical axis column.
    bounds : list of float or None
        The range of the numeric axis to cut into cells; None with two
        categorical axes.

    Returns
    -------
    Spread
        The widths.
    """
    both = x in categorical and y in categorical
    level = x if x in categorical else y
    inner = len(axis_levels[y]) if both else SPREAD_CELLS
    n = len(axis_levels[level]) * inner
    counts = (
        frame.select(_cells(x, y, categorical, axis_levels, bounds).alias("cell"))
        .group_by("cell")
        .len()
        .collect(engine="streaming")
    )
    table = [0] * n
    for cell, rows in counts.iter_rows():
        if cell is not None:
            table[cell] = rows
    if both:
        top = max(table, default=0)
        widths = [(r / top) ** 0.5 if top else 0.0 for r in table]
    else:
        widths = []
        for i in range(0, n, inner):
            row = table[i : i + inner]
            top = max(row)
            widths += [(r / top) ** 0.5 if top else 0.0 for r in row]
    return Spread(x=x, y=y, bounds=None if both else list(bounds), widths=widths)


def jitter(index: str, step: float) -> pl.Expr:
    """Return a spread of the rows from -1 to 1 by their row index."""
    return ((pl.col(index).cast(pl.Float64) * step) % 1.0) * 2 - 1


def pair_positions(
    x: str,
    y: str,
    categorical: set[str],
    axis_levels: dict[str, list[str]],
    spread: Spread | None,
    index: str,
) -> tuple[pl.Expr, pl.Expr]:
    """Return where each row lies along the x and y axes of a pair's panels.

    A numeric column lies at its value; a categorical one in its level's
    band, spread by `spread`. A row with a null or non-finite position is
    not drawn.

    Parameters
    ----------
    x, y : str
        The pair's columns.
    categorical : set of str
        The axis columns that are categorical.
    axis_levels : dict
        Levels of each categorical axis column.
    spread : Spread or None
        Widths of the pair, with its widths; None unless an axis is
        categorical.
    index : str
        Column of the row index.

    Returns
    -------
    tuple of polars.Expr
        The x and y positions as Float64.
    """
    if x not in categorical and y not in categorical:
        return pl.col(x).cast(pl.Float64), pl.col(y).cast(pl.Float64)
    widths = pl.lit(pl.Series(spread.widths, dtype=pl.Float64)).gather(
        _cells(x, y, categorical, axis_levels, spread.bounds)
    )
    both = x in categorical and y in categorical

    def position(column: str, step: float) -> pl.Expr:
        if column not in categorical:
            return pl.col(column).cast(pl.Float64)
        center = level_index(column, axis_levels[column]).cast(pl.Float64)
        return center + BAND * widths * jitter(index, step)

    return position(x, JITTER_X), position(y, JITTER_Y if both else JITTER_X)
