"""Bands of categorical axes: a band per level, and the jitter of a box plot's outliers.

Level ``i`` of a categorical axis column is the band centered on position
``i`` (the axis spans ``-0.5`` to ``n - 0.5``); the points of a row lie at
its center, or apart in it where rows share their coordinates
(`ddviz.compute.stacks`). The outliers of a box plot spread in the slot of
their series by a jitter from their row index (`jitter`), so that a row
keeps its place over zooms, sizes and processes.
"""

from __future__ import annotations

import polars as pl

# Half the width of a band, as a part of the step between levels.
BAND = 0.4
# Step of the jitter by row index: the golden ratio's, so that consecutive
# rows spread evenly.
JITTER_X = 0.6180339887498949


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


def level_index(column: str, levels: list[str], strict: bool = True) -> pl.Expr:
    """Return the index of each row's level of a categorical column, null for a null value.

    Parameters
    ----------
    column : str
        The column.
    levels : list of str
        Its levels as text; every value of the column must be one.
    strict : bool
        Whether a value that is no level fails the query; False makes it
        null. A filter on the index pushed down into the Parquet reader
        sees the slots of null values as empty texts (polars 2.1, a
        categorical column on both axes): the stacks
        (`ddviz.compute.stacked`) filter on it without failing.

    Returns
    -------
    polars.Expr
        The index as Int64.
    """
    # An Enum cast streams; replace_strict on 100M rows took over 9GB.
    return (
        pl.col(column)
        .cast(pl.String)
        .cast(pl.Enum(levels), strict=strict)
        .to_physical()
        .cast(pl.Int64)
    )


def jitter(index: str, step: float) -> pl.Expr:
    """Return a spread of the rows from -1 to 1 by their row index."""
    return ((pl.col(index).cast(pl.Float64) * step) % 1.0) * 2 - 1
