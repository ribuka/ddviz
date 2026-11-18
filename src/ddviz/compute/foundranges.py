"""Ranges of the axes: the positive values of the log axes, the automatic ranges and the ranges shown."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from ddviz.compute.axisposition import on_axis
from ddviz.compute.bands import band_range
from ddviz.compute.plotscan import found_ranges, plot_scan
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.shared.axisscale import (
    RANGE_PADDING,
    NoPositiveValuesError,
    no_positive_message,
    padded_log_range,
)
from ddviz.shared.scatter import ScatterSpec, View


def padded(lo: float | None, hi: float | None) -> tuple[float, float]:
    """Return a data range with a margin, or a unit range around a constant."""
    if lo is None or hi is None:
        return (0.0, 1.0)
    if lo == hi:
        return (lo - 0.5, hi + 0.5)
    pad = (hi - lo) * RANGE_PADDING
    return (lo - pad, hi + pad)


@dataclass(frozen=True)
class LogAxes:
    """What the rows of the local filter hold for the log axes (`log_axes`)."""

    ranges: dict[str, tuple[float, float] | None]
    nonpositive: list[tuple[str, str]]


def log_axes(spec: ScatterSpec) -> LogAxes:
    """Return the positive finite range of each column on a log axis, and those with a value not positive.

    Over the rows of the local filter, in one pass per column.
    """
    columns = list(dict.fromkeys([*spec.log_x, *spec.log_y]))
    if not columns:
        return LogAxes({}, [])
    queries = []
    for c in columns:
        value = pl.col(c).cast(pl.Float64)
        # Nulls in place of the others, as `ddviz.compute.plotscan.range_query` does.
        positive = pl.when(on_axis(value, True)).then(value)
        queries.append(
            plot_scan(spec, [c, *filter_columns(spec.filters)])
            .filter(*filter_conditions(spec.filters))
            .select(
                positive.min().alias("min"),
                positive.max().alias("max"),
                (value.is_finite() & (value <= 0)).any().alias("nonpositive"),
            )
        )
    found = pl.collect_all(queries, engine="streaming")
    ranges, flagged = {}, set()
    for c, f in zip(columns, found, strict=True):
        lo, hi, nonpositive = f.row(0)
        ranges[c] = None if lo is None else (lo, hi)
        if nonpositive:
            flagged.add(c)
    nonpositive = [
        (role, c)
        for role, logs in (("x", spec.log_x), ("y", spec.log_y))
        for c in logs
        if c in flagged
    ]
    return LogAxes(ranges, nonpositive)


def log_auto(spec: ScatterSpec, logs: LogAxes) -> dict[str, tuple[float, float]]:
    """Return the automatic range of each column on a log axis, as positions.

    The padded exponents of its positive values among the rows of the
    filter (`log_axes`), or among every row when the filter leaves it
    none.

    Raises
    ------
    NoPositiveValuesError
        When a column has no positive value among every row either.
    """
    columns = list(dict.fromkeys([*spec.log_x, *spec.log_y]))
    found = {c: logs.ranges[c] for c in columns}
    left = [c for c in columns if found[c] is None]
    if left and spec.filters:
        found.update(found_ranges(spec, left, filtered=False, log=True))
    empty = [
        (role, c)
        for role, logged in (("x", spec.log_x), ("y", spec.log_y))
        for c in logged
        if found[c] is None
    ]
    if empty:
        raise NoPositiveValuesError(no_positive_message(empty))
    return {c: padded_log_range(*found[c]) for c in columns}


def linear_auto(
    spec: ScatterSpec, every_row: dict[str, tuple[float, float] | None] | None
) -> dict[str, tuple[float, float]]:
    """Return the automatic range of each numeric column on a linear axis.

    The padded range of its finite values among the rows of the filter,
    each column alone, in a pass of its own that reads it and the filter's
    columns; a column the filter leaves without a value takes that of every
    row (`every_row`, from the overview, or found again), and a column
    without any value the unit range (`padded`).
    """
    columns = [
        c
        for c in dict.fromkeys(
            [
                *(c for c in spec.x if c not in spec.log_x),
                *(c for c in spec.y if c not in spec.log_y),
            ]
        )
        if c not in spec.categorical
    ]
    if not spec.filters and every_row is not None:
        found = {c: every_row[c] for c in columns}
    else:
        found = found_ranges(spec, columns, filtered=True)
    left = [c for c in columns if found[c] is None]
    if left and spec.filters:
        if every_row is None:
            found.update(found_ranges(spec, left, filtered=False))
        else:
            found.update({c: every_row[c] for c in left})
    return {c: padded(*(found[c] or (None, None))) for c in columns}


def auto_ranges(
    spec: ScatterSpec,
    log: dict[str, tuple[float, float]],
    axis_levels: dict[str, list[str]],
    every_row: dict[str, tuple[float, float] | None] | None = None,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Return the automatic range of each x and each y column (`Aggregation.x_auto`), given those of the log axes (`log_auto`)."""
    linear = linear_auto(spec, every_row)
    bands = {c: band_range(v) for c, v in axis_levels.items()}

    def auto(columns: list[str], logged: list[str]) -> list[tuple[float, float]]:
        return [
            bands[c] if c in bands else log[c] if c in logged else linear[c]
            for c in columns
        ]

    return auto(spec.x, spec.log_x), auto(spec.y, spec.log_y)


def with_bands(
    columns: list[str], auto: list[list[float]], axis_levels: dict[str, list[str]]
) -> list[tuple[float, float]]:
    """Return the automatic ranges `auto` of `columns`, a categorical one spanning the bands of its levels (`axis_levels`)."""
    return [
        band_range(axis_levels[c]) if c in axis_levels else (r[0], r[1])
        for c, r in zip(columns, auto, strict=True)
    ]


def view_ranges(
    columns: list[str],
    given: list[list[float] | None],
    auto: list[tuple[float, float]],
    view: View,
    axis_levels: dict[str, list[str]],
) -> list[tuple[float, float]]:
    """Return the ranges a view draws its `columns` over: those `given`, or else the automatic ones `auto`.

    A categorical column whose range is given as a position among levels
    (`View.range_levels`) other than those it draws (`axis_levels`) takes
    its automatic range, the bands of the levels drawn: the range would
    show other levels.
    """

    def stale(c: str) -> bool:
        return c in view.range_levels and view.range_levels[c] != axis_levels.get(c)

    return [
        a if r is None or stale(c) else (r[0], r[1])
        for c, r, a in zip(columns, given, auto, strict=True)
    ]
