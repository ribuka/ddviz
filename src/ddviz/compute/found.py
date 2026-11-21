"""What the overview finds and a view carries: the ranges, levels, cuts, and boxes and lines known."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ddviz.compute import foundcolor, foundlevels, foundranges
from ddviz.compute.missing import numeric_roles
from ddviz.shared.scatter import ONE_BAND, Boxes, RefStats, ScatterSpec, Smooths


@dataclass(frozen=True)
class Found:
    """What the overview found, or a view carries: the ranges, levels, cuts and boxes and lines known.

    Attributes
    ----------
    x_ranges, y_ranges : list of tuple of float
        The range each x and each y column is drawn over.
    x_auto, y_auto : list of tuple of float
        The automatic range of each x and each y column.
    all_levels : dict
        The levels of each role and column, before the facets of the filter.
    levels : dict
        The drawn levels.
    cuts : dict
        The cuts of each role cut into intervals.
    color_range : tuple of float or None
        The range of a gradient color column.
    axis_levels : dict
        The levels of each categorical axis column.
    known_boxes : list of Boxes
        The box plots a view already knows.
    known_smooths : list of Smooths
        The smooth lines a view already knows.
    known_ref_stats : list of RefStats
        The statistics of the reference lines a view already knows.
    """

    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]
    # The automatic ranges of the filter (`Aggregation.x_auto`).
    x_auto: list[tuple[float, float]]
    y_auto: list[tuple[float, float]]
    all_levels: dict[str, list]
    # The drawn levels: `all_levels` with the facets of the filter.
    levels: dict[str, list]
    cuts: dict
    color_range: tuple[float, float] | None
    axis_levels: dict[str, list[str]]
    known_boxes: list[Boxes]
    known_smooths: list[Smooths]
    known_ref_stats: list[RefStats]


def find(  # noqa: PLR0915
    spec: ScatterSpec,
    roles: dict[str, str | None],
    logs: foundranges.LogAxes,
    progress: Callable[[str], None],
) -> Found:
    """Return the ranges and levels of the overview, or of a view, then the drawn facet levels.

    The overview finds the levels over every row (`ddviz.compute.foundlevels.overview`) but for
    those of the rows of the local filter (`ddviz.compute.foundlevels.found_levels`): the
    categorical roles of `ScatterSpec.levels_of_filter` and the categorical
    axis columns but those of `ScatterSpec.keep_unfiltered_axis_levels`
    (whose levels are of every row, a view's too), when the spec has a filter (a categorical color column
    always, so that its limit is checked without holding the levels of an
    ID column). It spans the automatic ranges (`ddviz.compute.foundranges.auto_ranges`); a view its
    own, but for a column without one, and finds the automatic ranges
    unless it knows them, and the levels the spec asks for again
    (`View.find_levels`, `View.find_axis_levels`). A categorical axis spans
    the bands of its levels. Raises `NoPositiveValuesError` when a log axis
    has no positive value among every row.

    Parameters
    ----------
    spec : ScatterSpec
        The plot, with its view, if any.
    roles : dict
        The column of each role, None for a role without one.
    logs : ddviz.compute.foundranges.LogAxes
        The positive ranges of the log axes among the rows of the filter.
    progress : callable
        Called with the name of each stage as it starts.

    Returns
    -------
    Found
        The ranges, levels, cuts, and boxes and lines known.
    """
    view = spec.view
    numeric = numeric_roles(spec)
    if view is not None:
        all_levels = view.levels
        cuts = view.cuts
        color_range = view.color_range
        if color_range is not None:
            color_range = (color_range[0], color_range[1])
        axis_levels = view.axis_levels
        known_boxes = view.boxes
        known_smooths = view.smooths
        known_ref_stats = view.ref_stats
        # An axis column that keeps its levels has those of every row, which
        # the view takes from the overview (`View.axis_levels`).
        find_axes = [
            c
            for c in view.find_axis_levels
            if c not in spec.keep_unfiltered_axis_levels
        ]
        if view.find_levels or find_axes:
            progress("filtered_levels")
            found_levels, found_axes = foundlevels.found_levels(
                spec, roles, all_levels, view.find_levels, find_axes
            )
            all_levels = {**all_levels, **found_levels}
            axis_levels = {**axis_levels, **found_axes}
        if view.x_auto is not None and view.y_auto is not None:
            x_auto = foundranges.with_bands(spec.x, view.x_auto, axis_levels)
            y_auto = foundranges.with_bands(spec.y, view.y_auto, axis_levels)
        else:
            progress("ranges")
            x_auto, y_auto = foundranges.auto_ranges(spec, foundranges.log_auto(spec, logs), axis_levels)
        x_ranges = foundranges.view_ranges(spec.x, view.x_ranges, x_auto, view, axis_levels)
        y_ranges = foundranges.view_ranges(spec.y, view.y_ranges, y_auto, view, axis_levels)
    else:
        # Before the levels: a log axis without a positive value is refused.
        log = foundranges.log_auto(spec, logs)
        progress("levels")
        if spec.filters:
            find = [r for r in spec.levels_of_filter() if r not in numeric]
            # An axis column that keeps its levels has those of every row.
            axes = [
                c
                for c in spec.categorical
                if c != ONE_BAND and c not in spec.keep_unfiltered_axis_levels
            ]
        else:
            find = ["color"] if spec.filters_color() else []
            axes = []
        # The levels of the rows of the filter are found on their own,
        # after the limits of the levels over every row.
        overview = foundlevels.overview(
            spec,
            {**roles, **dict.fromkeys(find)},
            [c for c in spec.categorical if c not in axes],
        )
        all_levels, cuts = overview.levels, overview.cuts
        color_range = overview.color_range
        axis_levels = overview.axis_levels
        if find or axes:
            progress("filtered_levels")
            found_levels, found_axes = foundlevels.found_levels(
                spec, roles, all_levels, find, axes
            )
            all_levels = {**all_levels, **found_levels}
            axis_levels = {**axis_levels, **found_axes}
        known_boxes = []
        known_smooths = []
        known_ref_stats = []
        if spec.filters:
            progress("ranges")
        x_auto, y_auto = foundranges.auto_ranges(spec, log, axis_levels, overview.ranges)
        x_ranges, y_ranges = x_auto, y_auto
    scale = foundcolor.color_scale(spec, progress)
    cuts = {**cuts, **foundcolor.role_cuts(spec, roles, progress)}
    all_levels, cuts, color_range = foundcolor.scaled(
        spec, roles, scale, all_levels, cuts, color_range
    )
    if view is not None and view.facets is not None:
        levels = {**all_levels, **view.facets}
    else:
        progress("facets")
        levels = foundlevels.facet_levels(spec, all_levels, cuts)
    return Found(
        x_ranges=x_ranges,
        y_ranges=y_ranges,
        x_auto=x_auto,
        y_auto=y_auto,
        all_levels=all_levels,
        levels=levels,
        cuts=cuts,
        color_range=color_range,
        axis_levels=axis_levels,
        known_boxes=known_boxes,
        known_smooths=known_smooths,
        known_ref_stats=known_ref_stats,
    )
