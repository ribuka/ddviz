"""The index of a categorical column's levels, for the filter card that searches them.

A column with more levels than the filter pane lists
(`ddviz.compute.summary.MAX_FILTER_LEVELS`) but at most `MAX_SEARCH_LEVELS`
gets an index on its first search: every level (as text, nulls left out)
with its rows, in natural order (`ddviz.shared.natural`), written as a
Parquet file of ``value``, ``count`` and ``rank`` (the place in natural
order). A search reads only that file: it keeps the levels holding every
keyword of the query (`ddviz.shared.keywords`), orders them by name or by
count, and returns the first `LISTED`.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ddviz.shared.keywords import keywords
from ddviz.shared.natural import natural_key

# Most levels a column may have to be searched; one with more is filtered by
# the text its values contain. The largest count measured on 100M rows
# (10k to 2M levels) whose searches all answered within 0.5s (docs/spec.md,
# "フィルタの候補の検索の計測").
MAX_SEARCH_LEVELS = 2_000_000
# Most levels a search returns.
LISTED = 100
ORDERS = ("name", "count")


def build_index(parts: list[str], column: str, path: Path) -> dict:
    """Count the rows of each level of a column and write its index.

    A column whose estimated levels pass twice `MAX_SEARCH_LEVELS` is not
    grouped: an ID with about one level per row would take memory in
    proportion to the rows. The index is written under a temporary name
    (`partial`) and renamed once written; a failure removes it.

    Parameters
    ----------
    parts : list of str
        Parquet files holding the column, read one after another: its parts
        in the column cache.
    column : str
        The column.
    path : pathlib.Path
        Where the index goes.

    Returns
    -------
    dict
        ``index``, the path written, or None when the column has more than
        `MAX_SEARCH_LEVELS` levels; ``n_levels``, the exact count of levels,
        or the estimate when the column was not grouped.
    """
    value = pl.col(column).cast(pl.String).alias("value")
    scan = pl.scan_parquet(parts).select(value)
    estimate = (
        scan.select(pl.col("value").approx_n_unique())
        .collect(engine="streaming")
        .item()
    )
    if estimate > 2 * MAX_SEARCH_LEVELS:
        return {"index": None, "n_levels": estimate}
    counts = (
        scan.drop_nulls("value")
        .group_by("value")
        .len("count")
        .collect(engine="streaming")
    )
    if counts.height > MAX_SEARCH_LEVELS:
        return {"index": None, "n_levels": counts.height}
    values = counts["value"].to_list()
    order = sorted(range(len(values)), key=lambda i: natural_key(values[i]))
    index = counts[order].with_columns(
        pl.int_range(pl.len(), dtype=pl.UInt32).alias("rank")
    )
    temporary = partial(path)
    try:
        index.write_parquet(temporary)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {"index": str(path), "n_levels": counts.height}


def partial(path: Path) -> Path:
    """Return the temporary name an index is written under before it is renamed to `path`."""
    return path.with_name(path.name + ".partial")


def search_index(path: Path, query: str, order: str) -> dict:
    """Return the first `LISTED` levels of an index that hold every keyword of a query.

    Parameters
    ----------
    path : pathlib.Path
        The index (`build_index`).
    query : str
        The search input; blank keeps every level.
    order : {"name", "count"}
        ``"name"``: natural order. ``"count"``: the most rows first, equal
        counts in natural order.

    Returns
    -------
    dict
        ``levels``, ``[value, count]`` pairs in the order; ``truncated``,
        whether more levels matched; ``n_levels``, the levels of the index.

    Raises
    ------
    ValueError
        For an unknown order.
    """
    if order not in ORDERS:
        raise ValueError(f"unknown order: {order}")
    scan = pl.scan_parquet(path)
    n_levels = scan.select(pl.len()).collect().item()
    lowered = pl.col("value").str.to_lowercase()
    for word in keywords(query):
        scan = scan.filter(lowered.str.contains(word, literal=True))
    if order == "name":
        scan = scan.sort("rank")
    else:
        scan = scan.sort(["count", "rank"], descending=[True, False])
    found = scan.head(LISTED + 1).select("value", "count").collect()
    return {
        "levels": [list(row) for row in found.head(LISTED).iter_rows()],
        "truncated": found.height > LISTED,
        "n_levels": n_levels,
    }
