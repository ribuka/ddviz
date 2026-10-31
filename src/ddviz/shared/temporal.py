"""Kinds of temporal columns and the text of their values.

A temporal column is held as numbers (`ddviz.compute.temporal`): a datetime
or date as milliseconds since the epoch, a time as milliseconds since
midnight, a duration as seconds. The first three lie on plotly's date axis
(`DATE_KINDS`); a duration is a plain number of seconds. The page formats
values as `text` does (``static/js/temporal.js``).
"""

from __future__ import annotations

import datetime as dt

KINDS = ("datetime", "date", "time", "duration")
# Kinds drawn on a date axis, whose values are milliseconds.
DATE_KINDS = ("datetime", "date", "time")

# Wall-clock values: the zone is only there to make the arithmetic aware.
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_US_PER_DAY = 86_400_000_000


def text(kind: str, ms: float) -> str | None:
    """Return a value of a date-axis kind as text, or None for another kind or a value out of range.

    Parameters
    ----------
    kind : str
        The column's kind (`KINDS`).
    ms : float
        The value in milliseconds.

    Returns
    -------
    str or None
        ``2026-10-31 12:34:56.789000`` for a datetime (always to the
        microsecond), ``2026-10-31`` for a date, ``12:34:56.789000`` for a
        time.
    """
    if kind not in DATE_KINDS:
        return None
    us = round(ms * 1_000)
    if kind == "time":
        us %= _US_PER_DAY
    try:
        value = _EPOCH + dt.timedelta(microseconds=us)
    except OverflowError:
        return None
    if kind == "date":
        return value.strftime("%Y-%m-%d")
    if kind == "time":
        return value.strftime("%H:%M:%S.%f")
    return f"{value:%Y-%m-%d %H:%M:%S.%f}"
