"""Statistics of the reference lines of a numeric axis column: each panel's mean, standard deviation and quantiles.

The page draws the lines of the mean plus or minus n standard deviations
and of a quantile at the values of each panel (`static/js/axisdialog.js`).
A panel's values are those of the rows it draws as points, whether the
points are drawn or not (`ddviz.compute.aggregate`). The mean and the sample
standard deviation (ddof 1, polars' own) are one pass; the quantiles are
exact, as the box plots' (`ddviz.compute.boxes.group_quantiles`), linear
between ranks as numpy's default.
"""

from __future__ import annotations

import polars as pl

from ddviz.compute.boxes import GROUP, VALUE, group_quantiles
from ddviz.shared.scatter import RefStat


def group_stats(frame: pl.LazyFrame, asked: RefStat) -> dict[int, list]:
    """Return the statistics of the values of each group of rows.

    Parameters
    ----------
    frame : polars.LazyFrame
        The rows a group draws, with their group (`GROUP`, Int64 from 0)
        and a finite value (`VALUE`, Float64).
    asked : RefStat
        The statistics asked for.

    Returns
    -------
    dict of int to list
        For each group with rows, ``[n, mean, std, quantiles]``: its rows,
        the mean and the sample standard deviation when `asked` has the
        moments (None otherwise, and the deviation of a single row), and
        ``[p, value]`` of each percentile asked for.
    """
    groups = (
        frame.group_by(GROUP)
        .agg(
            pl.len().alias("n"),
            pl.col(VALUE).min().alias("lo"),
            pl.col(VALUE).max().alias("hi"),
            pl.col(VALUE).mean().alias("mean"),
            pl.col(VALUE).std().alias("std"),
        )
        .collect(engine="streaming")
    )
    stats: dict[int, list] = {}
    for g, n, mean, std in groups.select(GROUP, "n", "mean", "std").iter_rows():
        if asked.moments:
            stats[g] = [n, mean, std if n > 1 else None, []]
        else:
            stats[g] = [n, None, None, []]
    if asked.quantiles and stats:
        sizes = dict(zip(groups[GROUP].to_list(), groups["n"].to_list(), strict=True))
        bounds = {
            g: (lo, hi) for g, lo, hi in groups.select(GROUP, "lo", "hi").iter_rows()
        }
        found = group_quantiles(frame, sizes, bounds, [p / 100 for p in asked.quantiles])
        for g, values in found.items():
            stats[g][3] = [[p, v] for p, v in zip(asked.quantiles, values, strict=True)]
    return stats
