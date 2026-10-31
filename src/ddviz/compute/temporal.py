"""Columns of dates, times and durations as numbers, so that they are binned, cut and filtered as numeric columns are.

A ``Datetime`` or ``Date`` column becomes the milliseconds since the epoch,
a ``Time`` column the milliseconds since midnight, and a ``Duration`` column
its seconds, all as Float64. A ``Datetime`` with a time zone is taken at its
wall-clock time in that zone: plotly's date axis has no time zone. The kinds
are named as `ddviz.shared.temporal.KINDS`.
"""

from __future__ import annotations

import polars as pl

# Units of a time unit per millisecond.
_PER_MS = {"ns": 1_000_000, "us": 1_000, "ms": 1}
_MS_PER_DAY = 86_400_000


def temporal_kind(dtype: pl.DataType) -> str | None:
    """Return the kind of a temporal type, or None for another type.

    Parameters
    ----------
    dtype : polars.DataType
        The type.

    Returns
    -------
    str or None
        ``"datetime"``, ``"date"``, ``"time"`` or ``"duration"``.
    """
    if isinstance(dtype, pl.Datetime):
        return "datetime"
    if isinstance(dtype, pl.Duration):
        return "duration"
    if dtype == pl.Date:
        return "date"
    if dtype == pl.Time:
        return "time"
    return None


def as_number(column: str, dtype: pl.DataType) -> pl.Expr:
    """Return a temporal column as Float64 numbers.

    Parameters
    ----------
    column : str
        The column.
    dtype : polars.DataType
        Its type, temporal (`temporal_kind`).

    Returns
    -------
    polars.Expr
        Milliseconds for a datetime, date or time; seconds for a duration.
        The value is computed in the column's own unit, so that no date
        overflows a finer one.
    """
    value = pl.col(column)
    kind = temporal_kind(dtype)
    if kind == "datetime":
        if dtype.time_zone is not None:
            value = value.dt.replace_time_zone(None)
        unit = dtype.time_unit
        return value.dt.epoch(unit).cast(pl.Float64) / _PER_MS[unit]
    if kind == "date":
        return value.cast(pl.Int64).cast(pl.Float64) * _MS_PER_DAY
    if kind == "time":
        # A time is held as nanoseconds since midnight.
        return value.cast(pl.Int64).cast(pl.Float64) / _PER_MS["ns"]
    if kind == "duration":
        unit = dtype.time_unit
        return value.cast(pl.Int64).cast(pl.Float64) / (_PER_MS[unit] * 1_000)
    raise ValueError(f"not a temporal type: {dtype}")


def with_numbers(frame: pl.LazyFrame) -> pl.LazyFrame:
    """Return a frame with its temporal columns as numbers (`as_number`), named as before.

    Parameters
    ----------
    frame : polars.LazyFrame
        The frame.

    Returns
    -------
    polars.LazyFrame
        The frame itself when it has no temporal column.
    """
    numbers = [
        as_number(name, dtype).alias(name)
        for name, dtype in frame.collect_schema().items()
        if temporal_kind(dtype) is not None
    ]
    return frame.with_columns(numbers) if numbers else frame
