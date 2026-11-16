"""Conditions of the local filter as polars expressions."""

from __future__ import annotations

import polars as pl

from ddviz.compute.missing import is_missing
from ddviz.shared.keywords import keywords
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
        One condition per filter: the condition on the values (if any) or,
        with `Filter.nulls`, a missing value; without it, the condition on
        the values and a value that is not missing.
    """
    conditions = []
    for f in filters:
        column = pl.col(f.column)
        missing = is_missing(f.column, f.numeric)
        if f.range is not None:
            values = column.cast(pl.Float64).is_between(*f.range)
        elif f.contains is not None:
            text = column.cast(pl.String).str.to_lowercase()
            values = pl.all_horizontal(
                text.str.contains(w, literal=True) for w in keywords(f.contains)
            )
        elif f.levels is not None:
            values = column.cast(pl.String).is_in(f.levels)
        else:
            conditions.append(missing if f.nulls else ~missing)
            continue
        conditions.append(values | missing if f.nulls else values & ~missing)
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
