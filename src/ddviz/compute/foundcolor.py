"""The color scale, and the cuts of the numeric roles."""

from __future__ import annotations

from collections.abc import Callable

from ddviz.compute.cuts import cut_labels, find_cuts
from ddviz.compute.plotscan import found_ranges, plot_scan
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.shared.missing import MISSING
from ddviz.shared.scatter import Binning, ScatterSpec


def numeric_color(spec: ScatterSpec) -> bool:
    """Return whether the color column is numeric: a gradient, or cut into intervals."""
    return spec.gradient or "color" in spec.binned


def found_color_scale(spec: ScatterSpec, filtered: bool) -> dict | None:
    """Return the color scale of the finite values of a numeric color column, among the rows of the local filter (`filtered`) or every row.

    ``{"range": (lo, hi)}`` for a gradient, the cuts (`find_cuts`) of a
    column cut into intervals; None without a finite value. The rows of
    the filter are read in passes of their own, of the color column and the
    filter's columns alone, as the automatic ranges are (`ddviz.compute.plotscan.range_query`).
    """
    if spec.gradient:
        found = found_ranges(spec, [spec.color], filtered=filtered)[spec.color]
        return None if found is None else {"range": found}
    return found_cuts(spec, spec.color, spec.binned["color"], filtered)


def found_cuts(
    spec: ScatterSpec, column: str, binning: Binning, filtered: bool
) -> dict | None:
    """Return the cuts (`find_cuts`) of the finite values of a numeric column, among the rows of the local filter (`filtered`) or every row; None without a finite value.

    The rows of the filter are read in a pass of their own, of the column
    and the filter's columns alone.
    """
    if filtered and spec.filters:
        scan = plot_scan(spec, [column, *filter_columns(spec.filters)]).filter(
            *filter_conditions(spec.filters)
        )
    else:
        scan = plot_scan(spec, [column])
    cuts = find_cuts(scan, column, binning)
    return cuts if cuts["breaks"] else None


def color_scale(spec: ScatterSpec, progress: Callable[[str], None]) -> dict | None:
    """Return the color scale a numeric color column draws with, or None to keep the one known.

    The scale kept by the page (`ScatterSpec.color_scale`) comes first.
    Else the overview of a filter, and a view that finds it again
    (`ddviz.shared.scatter.View.find_color_scale`), take that of the rows of
    the filter; one that the filter leaves without a finite value takes
    that of every row: the overview's own, or found again by a view. The
    overview without a filter keeps that of every row, with no pass more.
    """
    if not numeric_color(spec):
        return None
    if spec.color_scale is not None:
        return spec.color_scale
    view = spec.view
    if (view is None and not spec.filters) or (
        view is not None and not view.find_color_scale
    ):
        return None
    progress("scale")
    found = found_color_scale(spec, filtered=True)
    if found is None and spec.filters:
        if view is None:
            return None
        found = found_color_scale(spec, filtered=False)
    if found is None:
        # As the overview has it for a column without a finite value.
        return (
            {"range": (0.0, 1.0)} if spec.gradient else {"breaks": [], "values": False}
        )
    return found


def role_cuts(
    spec: ScatterSpec, roles: dict[str, str | None], progress: Callable[[str], None]
) -> dict[str, dict]:
    """Return the cuts the roles of ``binned`` but the color (symbol, row, col) draw with; a role left out keeps those known.

    As the color scale (`color_scale`): the cuts kept by the page
    (`ScatterSpec.kept_cuts`) come first. Else the overview of a filter,
    and a view that finds them again (`ddviz.shared.scatter.View.find_cuts`),
    take those of the rows of the filter; a role that the filter leaves
    without a finite value takes those of every row: the overview's own,
    or found again by a view. The overview without a filter keeps those of
    every row, with no pass more. A column on two roles is read once.
    """
    view = spec.view
    found: dict[str, dict] = {}
    by_column: dict[tuple[str, Binning], dict | None] = {}
    for role, binning in spec.binned.items():
        if role == "color":
            continue
        if role in spec.kept_cuts:
            found[role] = spec.kept_cuts[role]
            continue
        if (view is None and not spec.filters) or (
            view is not None and role not in view.find_cuts
        ):
            continue
        key = (roles[role], binning)
        if key not in by_column:
            progress("cuts")
            cuts = found_cuts(spec, roles[role], binning, filtered=True)
            if cuts is None and spec.filters and view is not None:
                cuts = found_cuts(spec, roles[role], binning, filtered=False)
            by_column[key] = cuts
        cuts = by_column[key]
        if cuts is not None:
            found[role] = cuts
        elif view is not None:
            # As the overview has it for a column without a finite value.
            found[role] = {"breaks": [], "values": False}
    return found


def scaled(
    spec: ScatterSpec,
    roles: dict[str, str | None],
    scale: dict | None,
    levels: dict[str, list],
    cuts: dict,
    color_range: tuple[float, float] | None,
) -> tuple[dict[str, list], dict, tuple[float, float] | None]:
    """Return the levels, the cuts and the color range with the color scale `scale` (`color_scale`, None to keep the one known) and the cuts of the other roles (`cuts`).

    The levels of each role cut into intervals are the names of its cuts,
    the missing level kept last: a view is given the levels of another
    result, and the cuts of the rows of its filter.
    """
    if scale is not None and spec.gradient:
        lo, hi = scale["range"]
        color_range = (float(lo), float(hi))
    elif scale is not None:
        cuts = {**cuts, "color": scale}
    cuts = {
        role: {"breaks": [float(b) for b in c["breaks"]], "values": bool(c["values"])}
        for role, c in cuts.items()
    }
    named = dict(levels)
    for role in spec.binned:
        names = cut_labels(cuts[role], spec.temporal.get(roles[role]))
        if levels[role][-1:] == [MISSING]:
            names = [*names, MISSING]
        named[role] = names
    return named, cuts, color_range
