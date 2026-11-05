"""Which rows a plot draws, and which of them a box drawn on a panel selects.

Both are polars conditions: the aggregation filters the drawn rows with
`ddviz.compute.missing.drawn_conditions`, and the selection layer and the selection table filter
the selected rows with `selection_filter`.
"""

from __future__ import annotations

import math

import polars as pl

from ddviz.compute.axisposition import position
from ddviz.compute.bands import BAND, level_index
from ddviz.compute.cuts import in_level
from ddviz.compute.missing import drawn_conditions, role_index
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.compute.stacked import marker_boxes, stack_frame
from ddviz.compute.stacks import DX, DY, PX, PY, Axis, ranked, stack_groups
from ddviz.shared.layout import GAP, WRAP_GAP, facet_grid, grid_layout
from ddviz.shared.scatter import ScatterSpec

# Whether a row's center is in the box along x and along y (`_stacked`).
_IN_X = "__in_x"
_IN_Y = "__in_y"


def selection_filter(spec: ScatterSpec, index: str) -> list[pl.Expr]:
    """Return the conditions that pick the selected rows of a spec with a selection.

    A row is selected when it is drawn in the panel the box was drawn on:
    its facet levels are the panel's, its x and y are in the box, its
    color, overlay, row and col are drawn (`ddviz.compute.missing.drawn_conditions`), and it passes the local filter.
    On a categorical axis, the point drawn for it is in the box: a row
    alone or of a pile at the center of its band, a row of a stack that
    fits where its stack puts it (`ddviz.compute.stacks`), as the drawn
    result placed it (`_stacked`; this reads the data).
    In a panel of box plots without the points
    (`ddviz.shared.scatter.ScatterSpec.draws_points`), its level's band
    overlaps the box and its y is in the box, inside a box plot or not.
    In a panel of smoothing lines without the points, its x and y are in
    the box, as if the points were drawn.

    Parameters
    ----------
    spec : ScatterSpec
        A spec whose ``selection`` is set, with a view holding the ranges,
        levels, facet levels, cuts and axis levels of the drawn result.
    index : str
        Column of the row index, which orders the points of a stack.

    Returns
    -------
    list of polars.Expr
        Conditions to filter on.
    """
    selection = spec.selection
    axis_levels = spec.view.axis_levels if spec.categorical else {}
    cell = _cell_conditions(spec)
    if spec.points or (selection.x, selection.y) not in spec.box_pairs():
        # Positions on the axes: the log10 of a value on a log axis.
        x = position(_center(selection.x, axis_levels), selection.x in spec.log_x)
        y = position(_center(selection.y, axis_levels), selection.y in spec.log_y)
        if {selection.x, selection.y} & set(spec.categorical):
            return [
                x.is_finite(),
                y.is_finite(),
                _stacked(spec, index, cell, x, y),
                *cell,
            ]
        conditions = [
            x.is_finite(),
            y.is_finite(),
            x.is_between(*selection.x_range),
            y.is_between(*selection.y_range),
        ]
    else:
        lo, hi = selection.x_range
        level = level_index(selection.x, axis_levels[selection.x])
        y = position(pl.col(selection.y).cast(pl.Float64), selection.y in spec.log_y)
        conditions = [
            level.is_between(math.ceil(lo - BAND), math.floor(hi + BAND)),
            y.is_finite(),
            y.is_between(*selection.y_range),
        ]
    return conditions + cell


def _center(column: str, axis_levels: dict[str, list[str]]) -> pl.Expr:
    """Return where a row's center lies along an axis: its level's index, or its number."""
    if column in axis_levels:
        return level_index(column, axis_levels[column], strict=False).cast(pl.Float64)
    return pl.col(column).cast(pl.Float64)


def _cell_conditions(spec: ScatterSpec) -> list[pl.Expr]:
    """Return the conditions of a selected row besides its position: drawn, in the box's facet cell, through the local filter."""
    selection = spec.selection
    conditions = drawn_conditions(spec)
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


def _panel_bins(spec: ScatterSpec) -> tuple[int, int]:
    """Return the pixels of a panel of the drawn result along x and y."""
    facets = spec.view.facets or spec.view.levels
    axes = facet_grid(
        len(facets["row"]),
        len(facets["col"]),
        len(spec.x),
        len(spec.y),
        spec.wrap,
        spec.wrap_cols,
        spec.width,
        spec.height,
    )
    layout = grid_layout(
        spec.width, spec.height, axes.rows, axes.cols, WRAP_GAP if spec.wrap else GAP
    )
    return layout.panel_width, layout.panel_height


def _overlay_index(spec: ScatterSpec) -> pl.Expr:
    """Return each row's overlay level, whose marker its point is drawn in; 0 without an overlay."""
    return role_index(
        spec, "overlay", spec.view.levels["overlay"], cuts=spec.view.cuts.get("overlay")
    )


def _stacked(
    spec: ScatterSpec, index: str, cell: list[pl.Expr], x: pl.Expr, y: pl.Expr
) -> pl.Expr:
    """Return the condition of the rows whose points a box selects in a panel with a categorical axis.

    A row is selected when its center (`x`, `y`) is in the box, unless its
    stack fits and puts its point out of the box, or when its stack puts
    its point in the box from a center out of it. Only the stacks whose
    band crosses an edge of the box can do either: their rows are placed
    again as the drawn result placed them (the stacks of every drawn row of
    the panel, whatever the box, in the result's ranges and panel size),
    and those whose point is across the edge from their center are listed
    by their row index. Those are at most the rows of the levels along the
    box's edges.
    """
    selection = spec.selection
    view = spec.view
    xi, yj = spec.x.index(selection.x), spec.y.index(selection.y)
    width, height = _panel_bins(spec)
    categorical = set(spec.categorical)
    axis_x = Axis(
        selection.x in categorical, *view.x_ranges[xi], width, selection.x in spec.log_x
    )
    axis_y = Axis(
        selection.y in categorical,
        *view.y_ranges[yj],
        height,
        selection.y in spec.log_y,
    )
    x0, x1 = selection.x_range
    y0, y1 = selection.y_range
    in_box = x.is_between(x0, x1) & y.is_between(y0, y1)
    near, around = pl.lit(False), []
    for axis, center, (lo, hi) in ((axis_x, x, (x0, x1)), (axis_y, y, (y0, y1))):
        if axis.banded:
            near = near | ((center - lo).abs() < BAND) | ((center - hi).abs() < BAND)
            around.append(center.is_between(lo - BAND, hi + BAND))
        else:
            around.append(center.is_between(lo, hi))
    levels = view.levels["overlay"] if spec.overlay is not None else []
    columns = [
        selection.x,
        selection.y,
        *(c for c in (spec.color, spec.overlay, spec.row, spec.col) if c),
        *filter_columns(spec.filters),
    ]
    frame, coordinates = stack_frame(
        {c: spec.files[c] for c in dict.fromkeys(columns)},
        index,
        selection.x,
        selection.y,
        axis_x,
        axis_y,
        view.axis_levels,
        [*cell, *around, near],
        pl.lit(0, pl.Int64),
        [0],
        pl.lit(0, pl.Int64),
        _overlay_index(spec),
        marker_boxes(spec.marker_shapes(levels), spec.marker_sizes(levels)),
        [],
    )
    frame = frame.with_columns(
        x.is_between(x0, x1).alias(_IN_X), y.is_between(y0, y1).alias(_IN_Y)
    )
    added, dropped = [], []
    for rows, stacks, part in stack_groups(frame, axis_x, axis_y, coordinates):
        for placed in ranked(rows, stacks, part, index, axis_x, axis_y, [_IN_X, _IN_Y]):
            at = []
            for axis, pixel, offset, inside, (lo, hi) in (
                (axis_x, PX, DX, _IN_X, (x0, x1)),
                (axis_y, PY, DY, _IN_Y, (y0, y1)),
            ):
                if axis.banded:
                    where = axis.position(pl.col(pixel) + pl.col(offset))
                    at.append(where.is_between(lo, hi))
                else:
                    at.append(pl.col(inside))
            moved = placed.select(
                index,
                (at[0] & at[1]).alias("__at"),
                (pl.col(_IN_X) & pl.col(_IN_Y)).alias("__center"),
            )
            added.append(moved.filter(pl.col("__at") & ~pl.col("__center"))[index])
            dropped.append(moved.filter(~pl.col("__at") & pl.col("__center"))[index])
    if not added:
        return in_box
    plus, minus = pl.concat(added), pl.concat(dropped)
    return (in_box & ~pl.col(index).is_in(minus.implode())) | pl.col(index).is_in(
        plus.implode()
    )


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
    columns = [
        spec.selection.x,
        spec.selection.y,
        spec.color,
        spec.overlay,
        spec.row,
        spec.col,
    ]
    columns += filter_columns(spec.filters)
    return list(dict.fromkeys(c for c in columns if c is not None))
