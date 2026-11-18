"""Specs of new tasks derived from a drawn result: another view, size, filter or selection.

A drawn result's manifest holds its spec and what its overview found (the
levels, the cuts, the color range); a derived spec reuses them, so that the
worker does not find them again. The color scale of a numeric color column
(the gradient's range, or the color's cuts) is that of the rows of the
filter, unless the page keeps one under the lock of the axes
(`ddviz.shared.scatter.ScatterSpec.color_scale`); so are the cuts of a
numeric symbol, row or col column (`ddviz.shared.scatter.ScatterSpec.kept_cuts`).
The levels of the categorical roles (`ddviz.shared.scatter.ScatterSpec.levels_of_filter`)
and axes are those of the rows of the filter: a result of another filter
leaves them for the worker to find again.
"""

from __future__ import annotations

from dataclasses import replace

from ddviz.shared.axisscale import positions
from ddviz.shared.layout import (
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    bottom_margin,
    left_margin,
)
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import ONE_BAND, Filter, ScatterSpec, Selection, View


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


def drawn_scale(manifest: PlotManifest) -> dict | None:
    """Return the color scale a result draws its numeric color column with.

    Parameters
    ----------
    manifest : PlotManifest
        Manifest of a plot task.

    Returns
    -------
    dict or None
        ``{"range": [lo, hi]}`` for a gradient, the cuts of the color
        (``{"breaks", "values"}``) for one cut into intervals, None for
        another color (`ddviz.shared.scatter.ScatterSpec.color_scale`).
    """
    spec = manifest.spec
    if spec.gradient:
        return {"range": list(manifest.color_range)}
    if "color" in spec.binned:
        cuts = manifest.cuts["color"]
        return {"breaks": list(cuts["breaks"]), "values": cuts["values"]}
    return None


def drawn_cuts(manifest: PlotManifest) -> dict[str, dict]:
    """Return the cuts a result draws its numeric symbol, row and col columns with.

    Parameters
    ----------
    manifest : PlotManifest
        Manifest of a plot task.

    Returns
    -------
    dict of str to dict
        The cuts (``{"breaks", "values"}``) of each role of the spec's
        ``binned`` but the color (`ddviz.shared.scatter.ScatterSpec.kept_cuts`).
    """
    return {
        role: {
            "breaks": list(manifest.cuts[role]["breaks"]),
            "values": manifest.cuts[role]["values"],
        }
        for role in manifest.spec.binned
        if role != "color"
    }


def _own_cuts(manifest: PlotManifest | None, filters: list[Filter]) -> dict[str, dict]:
    """Return the cuts a result draws of the roles whose cuts are those of the rows of `filters`; none for a result of another filter, or the cuts kept by the page."""
    if manifest is None or manifest.spec.filters != filters:
        return {}
    kept = manifest.spec.kept_cuts
    return {r: c for r, c in drawn_cuts(manifest).items() if r not in kept}


def _drawn_axis_levels(
    manifest: PlotManifest | None, filters: list[Filter]
) -> dict[str, list[str]]:
    """Return the levels a result of `filters` draws of each categorical axis column; none for a result of another filter."""
    if manifest is None or manifest.spec.filters != filters:
        return {}
    return dict(manifest.axis_levels)


def _own_scale(manifest: PlotManifest | None, filters: list[Filter]) -> dict | None:
    """Return the color scale a result draws when it is that of the rows of `filters`; None for one of another filter, or kept by the page."""
    if (
        manifest is None
        or manifest.spec.filters != filters
        or manifest.spec.color_scale is not None
    ):
        return None
    return drawn_scale(manifest)


def _view(
    manifest: PlotManifest,
    x_ranges: list,
    y_ranges: list,
    same_filter: bool,
    filter_levels: dict[str, list] | None = None,
    auto: PlotManifest | None = None,
    scale: dict | None = None,
    role_cuts: dict[str, dict] | None = None,
    axis_levels: dict[str, list[str]] | None = None,
    range_levels: dict[str, list[str]] | None = None,
) -> View:
    """Return the view of the given ranges with the result's levels, cuts, color range, boxes and smoothing lines.

    A range None is the column's automatic range: that of `auto`, a result
    of the view's filter, or else one the worker finds. The view carries
    the automatic ranges of `auto`, so that the worker does not find them
    again.

    For another filter, the facet levels, the boxes and the smoothing lines
    are left for the worker to find again over the rows it keeps, and so
    are the levels of the roles that it finds over those rows
    (`ddviz.shared.scatter.ScatterSpec.levels_of_filter`), unless
    `filter_levels` gives them, from a result of that filter. The levels of
    each categorical axis column are those of `axis_levels` (by default the
    result's); the worker finds those left out
    (`ddviz.shared.scatter.View.find_axis_levels`), and spans the bands of
    the levels drawn when a categorical axis takes its automatic range.
    `range_levels` are the levels the given ranges of the categorical axes
    are positions among (`ddviz.shared.scatter.View.range_levels`). The
    stacks of the points on
    a categorical axis (`ddviz.compute.stacks`) depend on the ranges and
    the size: the worker places them again.

    A numeric color column draws with the color scale `scale`
    (`drawn_scale`); without one, the worker finds that of the rows of the
    view's filter (`ddviz.shared.scatter.View.find_color_scale`). So do
    the numeric symbol, row and col columns with the cuts of `role_cuts`
    (`drawn_cuts`), the worker finding those of the roles left out
    (`ddviz.shared.scatter.View.find_cuts`). The facet levels, the boxes
    and the smoothing lines of the same filter are those of other panels
    when the cuts or the axis levels differ from the result's: the worker
    finds them again.
    """
    levels = manifest.all_levels
    cuts, color_range = manifest.cuts, manifest.color_range
    numeric = drawn_scale(manifest) is not None
    if scale is not None and manifest.spec.gradient:
        color_range = list(scale["range"])
    elif scale is not None and numeric:
        cuts = {**cuts, "color": scale}
    role_cuts = role_cuts or {}
    find_cuts = [r for r in drawn_cuts(manifest) if r not in role_cuts]
    cuts = {**cuts, **role_cuts}
    axis_levels = manifest.axis_levels if axis_levels is None else axis_levels
    find_axis_levels = [c for c in manifest.axis_levels if c not in axis_levels]
    same_panels = (
        same_filter
        and not find_cuts
        and all(cuts[r] == manifest.cuts[r] for r in role_cuts)
        and axis_levels == manifest.axis_levels
    )
    find_levels = []
    if not same_filter:
        if filter_levels is None:
            find_levels = manifest.spec.levels_of_filter()
        else:
            levels = {**levels, **filter_levels}
    categorical = set(manifest.axis_levels)

    def ranges(given: list, columns: list[str], known: list | None) -> list:
        # A categorical axis spans the bands of the levels the worker draws.
        return [
            list(r)
            if r is not None
            else None
            if known is None or c in categorical
            else list(known[i])
            for i, (r, c) in enumerate(zip(given, columns, strict=True))
        ]

    x_auto = None if auto is None else [list(r) for r in auto.x_auto]
    y_auto = None if auto is None else [list(r) for r in auto.y_auto]
    return View(
        x_ranges=ranges(x_ranges, manifest.spec.x, x_auto),
        y_ranges=ranges(y_ranges, manifest.spec.y, y_auto),
        x_auto=x_auto,
        y_auto=y_auto,
        levels=levels,
        facets=facets_of(manifest) if same_panels else None,
        cuts=cuts,
        color_range=color_range,
        axis_levels={
            c: axis_levels[c] for c in manifest.axis_levels if c in axis_levels
        },
        boxes=manifest.boxes if same_panels else [],
        smooths=manifest.smooths if same_panels else [],
        find_levels=find_levels,
        find_axis_levels=find_axis_levels,
        find_color_scale=numeric and scale is None,
        find_cuts=find_cuts,
        range_levels=dict(range_levels or {}),
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
    color_scale: dict | None = None,
    cuts: dict[str, dict] | None = None,
    range_levels: dict[str, list[str]] | None = None,
) -> ScatterSpec:
    """Return the spec of the overview for other ranges, size or filter, reusing its levels.

    The overview's facet panels are kept for the same filter; another
    filter finds its own (`ddviz.compute.aggregate.aggregate`). So does
    it the levels of the roles it finds over the rows of the filter
    (`ddviz.shared.scatter.ScatterSpec.levels_of_filter`) and those of the
    categorical axis columns, unless `known` is a result of that filter: a
    view aggregated with the new filter while zoomed gives them to the
    next views and to the overview, so that the series and the bands of
    one filter stay the same. A categorical axis column whose levels are
    those of every row
    (`ddviz.shared.scatter.ScatterSpec.keep_unfiltered_axis_levels`) keeps
    the overview's for any filter. The automatic ranges
    (`ddviz.compute.aggregate.Aggregation.x_auto`) come from the overview
    or `known`, whichever is of the filter; else the worker finds them,
    once per filter. So does the color scale of a numeric color column
    (`drawn_scale`): that of the rows of the filter which the overview or
    `known` draws, else found by the worker; or `color_scale`, kept by the
    page, which the spec holds (`ddviz.shared.scatter.ScatterSpec.color_scale`)
    unless it is that of the filter. The cuts of the numeric symbol, row
    and col columns (`drawn_cuts`) are found so too, role by role, or kept
    by the page (`cuts`, `ddviz.shared.scatter.ScatterSpec.kept_cuts`).

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
        Data range of each x and y column, or None for its automatic range.
    margin_left : int, optional
        Left margin the page asks for, in pixels; kept within the width
        (`ddviz.shared.layout.left_margin`).
    margin_bottom : int, optional
        Bottom margin the page asks for, in pixels; kept within the height
        (`ddviz.shared.layout.bottom_margin`).
    known : PlotManifest, optional
        Another result of the plot, whose levels of the roles and the
        categorical axes, automatic ranges and color scale are taken when
        its filter is `filters`.
    color_scale : dict, optional
        The color scale the page keeps (`ddviz.server.plotoptions.parse_color_scale`),
        for a numeric color column; None for that of the filter.
    cuts : dict of str to dict, optional
        The cuts the page keeps (`ddviz.server.plotoptions.parse_cuts`), by
        role; a role left out takes those of the filter.
    range_levels : dict of str to list of str, optional
        Levels of the result the page shows, of each categorical axis column
        whose range it gives (`ddviz.server.plotoptions.parse_range_levels`):
        a range of other levels than those drawn becomes the automatic one
        (`ddviz.shared.scatter.View.range_levels`).

    Returns
    -------
    ScatterSpec
        The spec, with the overview's limits of levels
        (`ddviz.shared.scatter.ScatterSpec.max_levels`); the caller puts
        those of the settings in effect (`ddviz.server.api_plot`).

    Raises
    ------
    ValueError
        Unless there is one range per x and per y column.
    """
    spec = manifest.spec
    if len(x_ranges) != len(spec.x) or len(y_ranges) != len(spec.y):
        raise ValueError("one range per x and y column")
    same = spec.filters == filters
    filter_levels = None
    auto = manifest if same else None
    if known is not None and known.spec.filters == filters:
        filter_levels = {r: known.all_levels[r] for r in spec.levels_of_filter()}
        auto = known
    # The one band is no column: it is the same for every filter. So are the
    # levels of every row of an axis column that keeps them: the view does
    # not find them again among the rows of its filter.
    kept = [ONE_BAND, *spec.keep_unfiltered_axis_levels]
    known_axes = {
        **{c: v for c, v in manifest.axis_levels.items() if c in kept},
        **_drawn_axis_levels(known, filters),
        **_drawn_axis_levels(manifest, filters),
    }
    own = _own_scale(manifest, filters) or _own_scale(known, filters)
    scale = own if color_scale is None else color_scale
    numeric = drawn_scale(manifest) is not None
    own_cuts = {**_own_cuts(known, filters), **_own_cuts(manifest, filters)}
    cuts = cuts or {}
    return replace(
        spec,
        files={**spec.files, **filter_files},
        filters=list(filters),
        # A scale kept that is the filter's own is none kept.
        color_scale=color_scale if numeric and color_scale != own else None,
        kept_cuts={r: c for r, c in cuts.items() if c != own_cuts.get(r)},
        width=width,
        height=height,
        margin_left=left_margin(margin_left, width),
        margin_bottom=bottom_margin(margin_bottom, height),
        view=_view(
            manifest,
            x_ranges,
            y_ranges,
            same,
            filter_levels,
            auto,
            scale,
            own_cuts | cuts,
            known_axes,
            range_levels,
        ),
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
    _, layout = spec.facet_layout(manifest.levels)
    return (
        layout == manifest.layout
        and manifest.x_ranges == spec.view.x_ranges
        and manifest.y_ranges == spec.view.y_ranges
        and manifest.spec.filters == spec.filters
        and (
            manifest.spec.color_scale is None
            if spec.color_scale is None
            else drawn_scale(manifest) == spec.color_scale
        )
        and all(
            drawn_cuts(manifest)[r] == spec.kept_cuts[r]
            if r in spec.kept_cuts
            else r not in manifest.spec.kept_cuts
            for r in drawn_cuts(manifest)
        )
        and not spec.view.find_axis_levels
        and spec.view.axis_levels == manifest.axis_levels
        # A range of other levels than those drawn becomes the automatic one.
        and all(
            spec.view.axis_levels.get(c) == v for c, v in spec.view.range_levels.items()
        )
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
        view=_view(
            manifest,
            manifest.x_ranges,
            manifest.y_ranges,
            True,
            auto=manifest,
            scale=drawn_scale(manifest),
            role_cuts=drawn_cuts(manifest),
        ),
        selection=selection,
    )
