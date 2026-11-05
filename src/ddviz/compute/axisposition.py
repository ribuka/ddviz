"""Positions of the rows on linear and log10 axes (`ddviz.shared.axisscale`), as polars expressions."""

from __future__ import annotations

import polars as pl


def position(value: pl.Expr, log: bool) -> pl.Expr:
    """Return the position of values on an axis: their log10 on a log axis.

    A value that is not positive has no finite position on a log axis
    (NaN below 0, -inf at 0), so that the conditions of finite positions
    leave its row out.

    Parameters
    ----------
    value : polars.Expr
        The values, as floats.
    log : bool
        Whether the axis is a log axis.

    Returns
    -------
    polars.Expr
        The positions.
    """
    return value.log10() if log else value


def on_axis(value: pl.Expr, log: bool) -> pl.Expr:
    """Return whether values have a position on an axis: finite, and positive on a log axis.

    Parameters
    ----------
    value : polars.Expr
        The values, as floats.
    log : bool
        Whether the axis is a log axis.

    Returns
    -------
    polars.Expr
        The condition.
    """
    finite = value.is_finite()
    return finite & (value > 0) if log else finite
