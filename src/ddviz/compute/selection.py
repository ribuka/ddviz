"""Which rows a plot draws, and which of them a box drawn on a panel selects.

Both are polars conditions: the aggregation filters the drawn rows with
`drawn_conditions`, and the selection layer and the selection table filter
the selected rows with `selection_filter`.
"""

from __future__ import annotations

import math

import polars as pl

from ddviz.compute.bands import BAND, level_index, pair_positions
from ddviz.compute.cuts import in_level
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.shared.scatter import ScatterSpec


def numeric_roles(spec: ScatterSpec) -> set[str]:
    """Return the roles whose column is read as numbers: the binned ones and a gradient's color."""
    return set(spec.binned) | ({"color"} if spec.gradient else set())


def drawn_conditions(spec: ScatterSpec) -> list[pl.Expr]:
    """Return the conditions a drawn row meets on its color, row and col columns.

    A categorical column must not be null; a numeric one (`numeric_roles`)
    must be finite.
    """
    numeric = {getattr(spec, role) for role in numeric_roles(spec)}
    columns = dict.fromkeys(c for c in (spec.color, spec.row, spec.col) if c)
    return [
        pl.col(c).cast(pl.Float64).is_finite()
        if c in numeric
        else pl.col(c).is_not_null()
        for c in columns
    ]


def selection_filter(spec: ScatterSpec, index: str) -> list[pl.Expr]:
    """Return the conditions that pick the selected rows of a spec with a selection.

    A row is selected when it is drawn in the panel the box was drawn on:
    its facet levels are the panel's, its x and y are in the box, its
    color, row and col are valid (`drawn_conditions`), and it passes the local filter.
    On a categorical axis, its position in the band is in the box
    (`ddviz.compute.bands.pair_positions`): the rows of the points drawn in it.
    In a panel of box plots without the points
    (`ddviz.shared.scatter.ScatterSpec.draws_points`), its level's band
    overlaps the box and its y is in the box, inside a box plot or not.

    Parameters
    ----------
    spec : ScatterSpec
        A spec whose ``selection`` is set, with a view holding the levels,
        cuts, axis levels and spreads of the drawn result.
    index : str
        Column of the row index, which the positions in a band read.

    Returns
    -------
    list of polars.Expr
        Conditions to filter on.
    """
    selection = spec.selection
    axis_levels, spread = {}, None
    if spec.categorical:
        axis_levels = spec.view.axis_levels
        spread = {(k.x, k.y): k for k in spec.view.spreads}.get(
            (selection.x, selection.y)
        )
    if spec.draws_points(selection.x, selection.y):
        x, y = pair_positions(
            selection.x, selection.y, set(spec.categorical), axis_levels, spread, index
        )
        conditions = [
            x.is_finite(),
            y.is_finite(),
            x.is_between(*selection.x_range),
            y.is_between(*selection.y_range),
        ]
    else:
        lo, hi = selection.x_range
        level = level_index(selection.x, axis_levels[selection.x])
        y = pl.col(selection.y).cast(pl.Float64)
        conditions = [
            level.is_between(math.ceil(lo - BAND), math.floor(hi + BAND)),
            y.is_finite(),
            y.is_between(*selection.y_range),
        ]
    conditions += drawn_conditions(spec)
    for role, level in (("row", selection.row), ("col", selection.col)):
        column = getattr(spec, role)
        if column is None or level is None:
            continue
        if role in spec.binned:
            index = spec.view.levels[role].index(level)
            conditions.append(in_level(column, spec.view.cuts[role], index))
        else:
            conditions.append(pl.col(column).cast(pl.String) == level)
    return conditions + filter_conditions(spec.filters)


def selection_columns(spec: ScatterSpec) -> list[str]:
    """Return the columns `selection_filter` reads.

    Parameters
    ----------
    spec : ScatterSpec
        A spec whose ``selection`` is set.

    Returns
    -------
    list of str
        The columns, once each.
    """
    columns = [spec.selection.x, spec.selection.y, spec.color, spec.row, spec.col]
    columns += filter_columns(spec.filters)
    return list(dict.fromkeys(c for c in columns if c is not None))
