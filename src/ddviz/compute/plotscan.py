"""Scans of the plot's columns, and the finite minimum and maximum of a numeric column."""

from __future__ import annotations

import polars as pl

from ddviz.compute.axisposition import on_axis
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.compute.scan import scan_columns
from ddviz.shared.scatter import ScatterSpec


def plot_scan(
    spec: ScatterSpec, columns: list[str], row_index: str | None = None
) -> pl.LazyFrame:
    """Return a scan of only `columns` of the plot.

    Each query gets its own scan: queries in one `collect_all` sharing a scan
    followed by a ``select`` made the streaming engine peak at about 6.7GB on
    100M rows, against about 1.2GB with separate scans.
    """
    return scan_columns({c: spec.files[c] for c in dict.fromkeys(columns)}, row_index)


def range_query(
    spec: ScatterSpec, column: str, filtered: bool = False, log: bool = False
) -> pl.LazyFrame:
    """Return the query of the finite minimum and maximum of a numeric column.

    `filtered` takes only the rows of the local filter, reading the column
    and the filter's columns alone; `log` only the positive values, those
    a log axis draws.
    """
    value = pl.col(column).cast(pl.Float64)
    # Not ``value.filter(...)``: a filter inside an expression holds the rows
    # it keeps until the minimum is taken, and the ranges of x and y on 1.11
    # billion rows went past 6GB; nulls in their place peaked at 0.69GB.
    finite = pl.when(on_axis(value, log)).then(value)
    if filtered and spec.filters:
        scan = plot_scan(spec, [column, *filter_columns(spec.filters)]).filter(
            *filter_conditions(spec.filters)
        )
    else:
        scan = plot_scan(spec, [column])
    return scan.select(finite.min().alias("min"), finite.max().alias("max"))


def found_ranges(
    spec: ScatterSpec, columns: list[str], filtered: bool, log: bool = False
) -> dict[str, tuple[float, float] | None]:
    """Return the finite (`log`: positive) minimum and maximum of each column, None for one without such a value (`range_query`)."""
    if not columns:
        return {}
    found = pl.collect_all(
        [range_query(spec, c, filtered, log) for c in columns], engine="streaming"
    )
    out = {}
    for c, f in zip(columns, found, strict=True):
        lo, hi = f.row(0)
        out[c] = None if lo is None else (lo, hi)
    return out
