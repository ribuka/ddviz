"""Specs of new tasks derived from a drawn result: another view, size, filter or selection.

A drawn result's manifest holds its spec and what its overview found (the
levels, the cuts, the color range); a derived spec reuses them, so that the
worker does not find them again.
"""

from __future__ import annotations

from dataclasses import asdict

from ddviz.shared.layout import AxisGrid, grid_layout
from ddviz.shared.scatter import Filter, ScatterSpec, Selection


def facets_of(manifest: dict) -> dict:
    """Return the row and col levels a result draws as panels.

    Parameters
    ----------
    manifest : dict
        Manifest of a plot task.

    Returns
    -------
    dict
        ``{"row": levels, "col": levels}``.
    """
    return {role: manifest["levels"][role] for role in ("row", "col")}


def _view(manifest: dict, x_ranges: list, y_ranges: list, facets: dict | None) -> dict:
    """Return the ``view`` of a spec: the given ranges and the result's levels, cuts and color range."""
    return {
        "x_ranges": [list(r) for r in x_ranges],
        "y_ranges": [list(r) for r in y_ranges],
        "levels": manifest["all_levels"],
        "facets": facets,
        "cuts": manifest["cuts"],
        "color_range": manifest["color_range"],
    }


def resized_spec(
    manifest: dict,
    width: int,
    height: int,
    filters: list[Filter],
    filter_files: dict[str, str],
    x_ranges: list,
    y_ranges: list,
) -> ScatterSpec:
    """Return the spec of the overview for other ranges, size or filter, reusing its levels.

    The overview's facet panels are kept for the same filter; another
    filter finds its own (`ddviz.compute.aggregate.aggregate`).

    Parameters
    ----------
    manifest : dict
        Manifest of the overview.
    width, height : int
        Size of the plot area in pixels.
    filters : list of Filter
        Conditions of the local filter.
    filter_files : dict
        File of each filter column in the column cache.
    x_ranges, y_ranges : list
        Data range of each x and y column.

    Returns
    -------
    ScatterSpec
        The spec.

    Raises
    ------
    ValueError
        Unless there is one range per x and per y column.
    """
    spec = manifest["spec"]
    if len(x_ranges) != len(spec["x"]) or len(y_ranges) != len(spec["y"]):
        raise ValueError("one range per x and y column")
    same = spec["filters"] == [asdict(f) for f in filters]
    return ScatterSpec.from_dict(
        {
            **spec,
            "files": {**spec["files"], **filter_files},
            "filters": [asdict(f) for f in filters],
            "width": width,
            "height": height,
            "view": _view(
                manifest, x_ranges, y_ranges, facets_of(manifest) if same else None
            ),
        }
    )


def unchanged(manifest: dict | None, spec: ScatterSpec) -> bool:
    """Whether a result already has the panels, ranges and filter of `spec`.

    A new size often keeps the layout: a grid that scrolls in both
    directions keeps its panels at their smallest size.

    Parameters
    ----------
    manifest : dict or None
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
    axes = AxisGrid(**manifest["axes"])
    layout = grid_layout(spec.width, spec.height, axes.rows, axes.cols)
    return (
        asdict(layout) == manifest["layout"]
        and [list(r) for r in manifest["x_ranges"]] == spec.view.x_ranges
        and [list(r) for r in manifest["y_ranges"]] == spec.view.y_ranges
        and manifest["spec"]["filters"] == [asdict(f) for f in spec.filters]
    )


def box_selection(
    manifest: dict,
    panel: int,
    x_range: tuple[float, float] | None,
    y_range: tuple[float, float] | None,
) -> Selection:
    """Return the rows a box drawn on a panel of a result selects.

    Parameters
    ----------
    manifest : dict
        Manifest of the result.
    panel : int
        Index of the panel.
    x_range, y_range : tuple of float or None
        Data ranges of the box, in either order.

    Returns
    -------
    Selection
        The selection.

    Raises
    ------
    ValueError
        For a panel the result does not have, or a box without both ranges.
    """
    spec, levels = manifest["spec"], manifest["levels"]
    axes = AxisGrid(**manifest["axes"])
    if not 0 <= panel < axes.rows * axes.cols:
        raise ValueError("no such panel")
    if x_range is None or y_range is None:
        raise ValueError("a box needs x_range and y_range")
    xi, yj = axes.axes(panel)
    prow, pcol = divmod(panel, axes.cols)
    return Selection(
        x=spec["x"][xi],
        y=spec["y"][yj],
        x_range=sorted(x_range),
        y_range=sorted(y_range),
        row=levels["row"][prow // axes.ny] if spec["row"] else None,
        col=levels["col"][pcol // axes.nx] if spec["col"] else None,
    )


def selection_spec(manifest: dict, selection: Selection) -> ScatterSpec:
    """Return the spec of the task aggregating a selection over a result.

    Parameters
    ----------
    manifest : dict
        Manifest of the result.
    selection : Selection
        The selected rows.

    Returns
    -------
    ScatterSpec
        The result's spec with its view and the selection.
    """
    return ScatterSpec.from_dict(
        {
            **manifest["spec"],
            "view": _view(
                manifest,
                manifest["x_ranges"],
                manifest["y_ranges"],
                facets_of(manifest),
            ),
            "selection": asdict(selection),
        }
    )
