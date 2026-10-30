"""Conditions of the local filter as polars expressions."""

from __future__ import annotations

import polars as pl

from ddviz.shared.scatter import Filter


def filter_conditions(filters: list[Filter]) -> list[pl.Expr]:
    """Return the conditions a row must meet to pass the local filter.

    Parameters
    ----------
    filters : list of Filter
        Conditions of the filter, one per column.

    Returns
    -------
    list of polars.Expr
        One condition per filter; a null value fails each of them.
    """
    conditions = []
    for f in filters:
        column = pl.col(f.column)
        if f.range is not None:
            conditions.append(column.cast(pl.Float64).is_between(*f.range))
        elif f.contains is not None:
            conditions.append(
                column.cast(pl.String).str.contains(f.contains, literal=True)
            )
        else:
            conditions.append(column.cast(pl.String).is_in(f.levels))
    return conditions


def filter_columns(filters: list[Filter]) -> list[str]:
    """Return the columns the conditions of `filters` read.

    Parameters
    ----------
    filters : list of Filter
        Conditions of the filter.

    Returns
    -------
    list of str
        The columns, once each.
    """
    return list(dict.fromkeys(f.column for f in filters))
