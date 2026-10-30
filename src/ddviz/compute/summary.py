"""What the filter pane shows of a column: its range or its levels with their counts."""

from __future__ import annotations

import polars as pl

# Most levels the filter pane lists for a categorical column. A column with
# about one level per row (an ID) cannot be filtered by ticking levels.
MAX_FILTER_LEVELS = 1000


def summarize_column(files: list[str], column: str) -> dict:
    """Return the summary of one column over every row.

    Parameters
    ----------
    files : list of str
        Parquet files holding the column, read one after another: its parts
        in the column cache.
    column : str
        The column.

    Returns
    -------
    dict
        ``rows`` and ``nulls`` (the count of null values) and, for a numeric
        column, ``numeric: True``, ``integer`` and the finite ``min`` and
        ``max`` (None without finite values); for a categorical column,
        ``numeric: False`` and ``levels``, ``[text, count]`` pairs sorted by
        text, or None when it has more than `MAX_FILTER_LEVELS` levels, with
        ``n_levels`` (an estimate then).
    """
    scan = pl.scan_parquet(files).select(column)
    dtype = scan.collect_schema()[column]
    value = pl.col(column)
    if dtype.is_numeric():
        number = value.cast(pl.Float64)
        finite = number.filter(number.is_finite())
        found = scan.select(
            pl.len().alias("rows"),
            value.null_count().alias("nulls"),
            finite.min().alias("min"),
            finite.max().alias("max"),
        ).collect(engine="streaming")
        return {
            **found.row(0, named=True),
            "numeric": True,
            "integer": dtype.is_integer(),
        }
    text = value.cast(pl.String)
    counts = scan.select(
        pl.len().alias("rows"),
        value.null_count().alias("nulls"),
        text.approx_n_unique().alias("n_levels"),
    ).collect(engine="streaming")
    summary = {**counts.row(0, named=True), "numeric": False, "levels": None}
    if summary["n_levels"] > MAX_FILTER_LEVELS + 1:
        return summary
    levels = (
        scan.group_by(text.alias("level"))
        .len()
        .drop_nulls("level")
        .sort("level")
        .collect(engine="streaming")
    )
    summary["n_levels"] = levels.height
    if levels.height <= MAX_FILTER_LEVELS:
        summary["levels"] = [list(r) for r in levels.iter_rows()]
    return summary
