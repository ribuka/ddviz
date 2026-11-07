"""Which rows the color, symbol, row and col roles draw, and the level each row is in.

A role's column draws a row whose value is a level: not null for a
categorical column, finite for a numeric one. With ``Show null rows`` on the
color or symbol role (`ddviz.shared.scatter.ScatterSpec.null_roles`), the
rows whose value is null or NaN are drawn too, in the role's missing level
(`ddviz.shared.missing.MISSING`), the last of its levels; an infinite value
stays out.
"""

from __future__ import annotations

import polars as pl

from ddviz.compute.bands import level_index
from ddviz.compute.cuts import cut_index
from ddviz.shared.missing import has_missing
from ddviz.shared.scatter import ScatterSpec

ROLES = ("color", "symbol", "row", "col")


def numeric_roles(spec: ScatterSpec) -> set[str]:
    """Return the roles whose column is read as numbers: the binned ones and a gradient's color."""
    return set(spec.binned) | ({"color"} if spec.gradient else set())


def numeric_columns(spec: ScatterSpec) -> set[str]:
    """Return the columns of the roles read as numbers (`numeric_roles`)."""
    return {getattr(spec, role) for role in numeric_roles(spec)}


def is_missing(column: str, numeric: bool) -> pl.Expr:
    """Return whether a row's value of a column is missing: null, or NaN for a numeric column."""
    if numeric:
        value = pl.col(column).cast(pl.Float64)
        return value.is_null() | value.is_nan()
    return pl.col(column).is_null()


def drawn_conditions(spec: ScatterSpec) -> list[pl.Expr]:
    """Return the conditions a drawn row meets on its color, symbol, row and col columns.

    Each role sets its own condition, so that a column on two roles meets
    both: a categorical column must not be null, a numeric one
    (`numeric_roles`) must be finite, unless the role draws its missing
    rows (`ddviz.shared.scatter.ScatterSpec.null_roles`), which then may
    be null or NaN too.
    """
    numeric = numeric_columns(spec)
    conditions = {}
    for role in ROLES:
        column = getattr(spec, role)
        if not column:
            continue
        is_numeric = column in numeric
        valid = (
            pl.col(column).cast(pl.Float64).is_finite()
            if is_numeric
            else pl.col(column).is_not_null()
        )
        draws_missing = role in spec.null_roles
        if draws_missing:
            valid = valid | is_missing(column, is_numeric)
        conditions[(column, is_numeric, draws_missing)] = valid
    return list(conditions.values())


def role_index(
    spec: ScatterSpec,
    role: str,
    levels: list,
    all_levels: list | None = None,
    cuts: dict | None = None,
) -> pl.Expr:
    """Return the index of each drawn row's level of a role among the drawn levels.

    Parameters
    ----------
    spec : ScatterSpec
        The spec.
    role : str
        ``"color"``, ``"symbol"``, ``"row"`` or ``"col"``.
    levels : list
        The role's drawn levels as text, the missing level last if drawn.
    all_levels : list, optional
        The role's levels over every row, of which `levels` are some, for a
        binned role; `levels` when omitted.
    cuts : dict, optional
        The cuts of a binned role (`ddviz.compute.cuts`).

    Returns
    -------
    polars.Expr
        The index as Int64; 0 without a column or for a gradient's values.
    """
    column = getattr(spec, role)
    if column is None:
        return pl.lit(0, pl.Int64)
    missing = has_missing(levels)
    normal = levels[:-1] if missing else levels
    numeric = role in numeric_roles(spec)
    if role in spec.binned:
        every = all_levels if all_levels is not None else levels
        index = cut_index(column, cuts, [every.index(v) for v in normal])
    elif role == "color" and spec.gradient:
        index = pl.lit(0, pl.Int64)
    else:
        index = level_index(column, [str(v) for v in normal])
    if not missing:
        return index
    return (
        pl.when(is_missing(column, numeric))
        .then(pl.lit(len(levels) - 1, pl.Int64))
        .otherwise(index)
    )
