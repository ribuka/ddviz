"""Specs of new tasks derived from a drawn result: another view, size, filter or selection.

A drawn result's manifest holds its spec and what its overview found (the
levels, the cuts, the color range); a derived spec reuses them, so that the
worker does not find them again.
"""

from __future__ import annotations

from dataclasses import replace

from ddviz.shared.axisscale import positions
from ddviz.shared.layout import (
    GAP,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    WRAP_GAP,
    bottom_margin,
    facet_grid,
    grid_layout,
    left_margin,
)
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import Filter, ScatterSpec, Selection, View


def facets_of(manifest: PlotManifest) -> dict:
    """Return the row and col levels a result draws as panels.

    Parameters
    ----------
    manifest : PlotManifest
        Manifest of a plot task.

    Returns
    -------
    dict
        ``{"row": levels, "col": levels}``.
    """
    return {role: manifest.levels[role] for role in ("row", "col")}


def _view(
    manifest: PlotManifest,
    x_ranges: list,
    y_ranges: list,
    same_filter: bool,
    colors: list | None = None,
) -> View:
    """Return the view of the given ranges with the result's levels, cuts, color range, boxes and smoothing lines.

    For another filter, the facet levels, the boxes and the smoothing lines
    are left for the worker to find again over the rows it keeps, and so
    are the color levels of a spec that finds them over those rows
    (`ddviz.shared.scatter.ScatterSpec.filters_color`), unless `colors`
    gives them, from a result of that filter. The stacks of the points on
    a categorical axis (`ddviz.compute.stacks`) depend on the ranges and
    the size: the worker places them again.
    """
    levels = manifest.all_levels
    find_color = False
    if manifest.spec.filters_color() and not same_filter:
        if colors is None:
            find_color = True
        else:
            levels = {**levels, "color": colors}
    return View(
        x_ranges=[list(r) for r in x_ranges],
        y_ranges=[list(r) for r in y_ranges],
        levels=levels,
        facets=facets_of(manifest) if same_filter else None,
        cuts=manifest.cuts,
        color_range=manifest.color_range,
        axis_levels=manifest.axis_levels,
        boxes=manifest.boxes if same_filter else [],
        smooths=manifest.smooths if same_filter else [],
        find_color=find_color,
    )


def resized_spec(
    manifest: PlotManifest,
    width: int,
    height: int,
    filters: list[Filter],
    filter_files: dict[str, list[str]],
    x_ranges: list,
    y_ranges: list,
    margin_left: int = MARGIN_LEFT,
    margin_bottom: int = MARGIN_BOTTOM,
    known: PlotManifest | None = None,
) -> ScatterSpec:
    """Return the spec of the overview for other ranges, size or filter, reusing its levels.

    The overview's facet panels are kept for the same filter; another
    filter finds its own (`ddviz.compute.aggregate.aggregate`). So does
    it its color levels, when the spec finds them over the rows of the
    filter (`ddviz.shared.scatter.ScatterSpec.filters_color`), unless
    `known` is a result of that filter: a view aggregated with the new
    filter while zoomed gives them to the next views and to the overview,
    so that the series of one filter stay the same.

    Parameters
    ----------
    manifest : PlotManifest
        Manifest of the overview.
    width, height : int
        Size of the plot area in pixels.
    filters : list of Filter
        Conditions of the local filter.
    filter_files : dict
        Parts of each filter column in the column cache.
    x_ranges, y_ranges : list
        Data range of each x and y column.
    margin_left : int, optional
        Left margin the page asks for, in pixels; kept within the width
        (`ddviz.shared.layout.left_margin`).
    margin_bottom : int, optional
        Bottom margin the page asks for, in pixels; kept within the height
        (`ddviz.shared.layout.bottom_margin`).
    known : PlotManifest, optional
        Another result of the plot, whose color levels are taken when its
        filter is `filters`.

    Returns
    -------
    ScatterSpec
        The spec.

    Raises
    ------
    ValueError
        Unless there is one range per x and per y column.
    """
    spec = manifest.spec
    if len(x_ranges) != len(spec.x) or len(y_ranges) != len(spec.y):
        raise ValueError("one range per x and y column")
    same = spec.filters == filters
    colors = None
    if known is not None and known.spec.filters == filters:
        colors = known.all_levels["color"]
    return replace(
        spec,
        files={**spec.files, **filter_files},
        filters=list(filters),
        width=width,
        height=height,
        margin_left=left_margin(margin_left, width),
        margin_bottom=bottom_margin(margin_bottom, height),
        view=_view(manifest, x_ranges, y_ranges, same, colors),
    )


def unchanged(manifest: PlotManifest | None, spec: ScatterSpec) -> bool:
    """Whether a result already has the panels, ranges and filter of `spec`.

    A new size often keeps the layout: a grid that scrolls in both
    directions keeps its panels at their smallest size. A wrapped grid may
    put another number of panels to a row.

    Parameters
    ----------
    manifest : PlotManifest or None
        Manifest of the result, if any.
    spec : ScatterSpec
        The spec of a new task.

    Returns
    -------
    bool
        True when the result can stand for the task.
    """
    if manifest is None:
        return False
    levels = manifest.levels
    axes = facet_grid(
        len(levels["row"]),
        len(levels["col"]),
        len(spec.x),
        len(spec.y),
        spec.wrap,
        spec.wrap_cols,
        spec.width,
        spec.height,
        spec.margin_left,
        spec.margin_bottom,
    )
    row_gap = WRAP_GAP if spec.wrap else GAP
    layout = grid_layout(
        spec.width,
        spec.height,
        axes.rows,
        axes.cols,
        row_gap,
        spec.margin_left,
        spec.margin_bottom,
    )
    return (
        layout == manifest.layout
        and manifest.x_ranges == spec.view.x_ranges
        and manifest.y_ranges == spec.view.y_ranges
        and manifest.spec.filters == spec.filters
    )


def box_selection(
    manifest: PlotManifest,
    panel: int,
    x_range: tuple[float, float] | None,
    y_range: tuple[float, float] | None,
) -> Selection:
    """Return the rows a box drawn on a panel of a result selects.

    Parameters
    ----------
    manifest : PlotManifest
        Manifest of the result.
    panel : int
        Index of the panel.
    x_range, y_range : tuple of float or None
        Data ranges of the box, in either order: of the values themselves,
        also on a log axis (`ddviz.shared.axisscale`).

    Returns
    -------
    Selection
        The selection.

    Raises
    ------
    ValueError
        For a panel the result does not have, a box without both ranges,
        or a box of a log axis over values that are not positive.
    """
    spec, levels, axes = manifest.spec, manifest.levels, manifest.axes
    if not 0 <= panel < axes.panels:
        raise ValueError("no such panel")
    if x_range is None or y_range is None:
        raise ValueError("a box needs x_range and y_range")
    xi, yj = axes.axes(panel)
    row, col = axes.facet(panel)
    return Selection(
        x=spec.x[xi],
        y=spec.y[yj],
        # The box is of the values; a log axis holds their positions.
        x_range=list(positions(tuple(sorted(x_range)), spec.x[xi] in spec.log_x)),
        y_range=list(positions(tuple(sorted(y_range)), spec.y[yj] in spec.log_y)),
        row=levels["row"][row] if spec.row else None,
        col=levels["col"][col] if spec.col else None,
    )


def selection_spec(manifest: PlotManifest, selection: Selection) -> ScatterSpec:
    """Return the spec of the task aggregating a selection over a result.

    Parameters
    ----------
    manifest : PlotManifest
        Manifest of the result.
    selection : Selection
        The selected rows.

    Returns
    -------
    ScatterSpec
        The result's spec with its view and the selection.
    """
    return replace(
        manifest.spec,
        view=_view(manifest, manifest.x_ranges, manifest.y_ranges, True),
        selection=selection,
    )
