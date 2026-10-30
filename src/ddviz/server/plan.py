"""Turns the graph the user built (`ddviz.server.encoding.Encoding`) into what a worker draws."""

from __future__ import annotations

import math

from ddviz.server.encoding import Encoding
from ddviz.shared.scatter import MAX_LEVELS, Binning, Filter, ScatterSpec

# A numeric column on Group X or Group Y is cut into this many intervals of
# about the same number of rows, unless it has at most this many values,
# each then a level of its own.
FACET_BINS = 5
# Numbers of intervals a numeric color column can be cut into.
COLOR_BINS = (2, 3, 5, 10)


# Elements of a graph (`ddviz.server.encoding.ELEMENTS`) that can be drawn.
DRAWN_ELEMENTS = ("points", "box")


def has_box_pair(encoding: Encoding, numeric: dict[str, bool]) -> bool:
    """Return whether a pair of the graph's axis columns can have box plots: a categorical x and a numeric y.

    Parameters
    ----------
    encoding : Encoding
        The graph.
    numeric : dict of str to bool
        Whether each column is numeric; a missing one is numeric.

    Returns
    -------
    bool
        Whether such a pair exists.
    """
    return any(not numeric.get(x, True) for x in encoding.x) and any(
        numeric.get(y, True) for y in encoding.y
    )


def undrawn(encoding: Encoding, numeric: dict[str, bool]) -> list[str]:
    """Return the roles and elements that are placed but cannot be drawn.

    Parameters
    ----------
    encoding : Encoding
        The graph.
    numeric : dict of str to bool
        Whether each column is numeric.

    Returns
    -------
    list of str
        ``"overlay"`` when overlay has a column, each chosen element not
        in `DRAWN_ELEMENTS`, and ``"box"`` without a pair of a categorical
        x and a numeric y (`has_box_pair`).
    """
    roles = ["overlay"] if encoding.overlay is not None else []
    return roles + [
        e
        for e in encoding.elements
        if e not in DRAWN_ELEMENTS
        or (e == "box" and not has_box_pair(encoding, numeric))
    ]


def drawn_columns(encoding: Encoding) -> list[str]:
    """Return the columns a scatter plot of the graph reads.

    Parameters
    ----------
    encoding : Encoding
        The graph.

    Returns
    -------
    list of str
        The x and y columns and the color, row, col and wrap columns, once
        each.
    """
    columns = [
        *encoding.x,
        *encoding.y,
        encoding.color,
        encoding.row,
        encoding.col,
        encoding.wrap,
    ]
    return list(dict.fromkeys(c for c in columns if c is not None))


def parse_filters(raw: list[dict], numeric: dict[str, bool]) -> list[Filter]:
    """Return the conditions of the local filter the page sent, checked.

    Parameters
    ----------
    raw : list of dict
        ``{"column", "range"}`` for a numeric column, ``{"column",
        "levels"}`` for a categorical one; one per column.
    numeric : dict of str to bool
        Whether each column of the data is numeric.

    Returns
    -------
    list of Filter
        The conditions.

    Raises
    ------
    ValueError
        For an unknown column, a column given twice, or a condition that
        does not fit its column.
    """
    filters = []
    for item in raw:
        if not isinstance(item, dict) or not set(item) <= {"column", "range", "levels"}:
            raise ValueError(f"a filter has a column and a range or levels: {item}")
        column = item.get("column")
        if column not in numeric:
            raise ValueError(f"unknown filter column: {column}")
        bounds, levels = item.get("range"), item.get("levels")
        if numeric[column]:
            ok = (
                levels is None
                and isinstance(bounds, list)
                and len(bounds) == 2
                and all(isinstance(b, int | float) and math.isfinite(b) for b in bounds)
                and bounds[0] <= bounds[1]
            )
            if not ok:
                raise ValueError(f"{column} needs a range [lo, hi]")
            filters.append(Filter(column, range=[float(b) for b in bounds]))
        else:
            ok = (
                bounds is None
                and isinstance(levels, list)
                and len(levels) > 0
                and all(isinstance(v, str) for v in levels)
            )
            if not ok:
                raise ValueError(f"{column} needs a list of levels")
            filters.append(Filter(column, levels=list(levels)))
    columns = [f.column for f in filters]
    if len(set(columns)) != len(columns):
        raise ValueError("one filter per column")
    return filters


def scatter_spec(
    encoding: Encoding,
    files: dict[str, list[str]],
    width: int,
    height: int,
    colors: list[str],
    filters: list[Filter] | None = None,
    numeric: dict[str, bool] | None = None,
    color_bins: Binning | None = None,
    max_levels: int = MAX_LEVELS,
    wrap_cols: int | None = None,
) -> ScatterSpec:
    """Return the overview scatter plot of a graph.

    Every pair of an x and a y column is drawn in a panel of each facet
    cell, colored by color and faceted by row and col; overlay is left out
    (`undrawn`). The panels of a categorical x and a numeric y have box
    plots when the elements have them (`ScatterSpec.box`); the other panels
    draw the points even without the points element. A categorical x or y column is drawn in bands, one per
    level (`ScatterSpec.categorical`). A wrap column takes the col role of the spec, its levels
    wrapping into rows (`ScatterSpec.wrap`). The hover shows the drawn
    columns. The local filter's columns are read too.

    Parameters
    ----------
    encoding : Encoding
        The graph.
    files : dict of str to list of str
        Parquet files holding each drawn column and filter column: its parts
        in the column cache.
    width, height : int
        Figure size in pixels.
    colors : list of str
        Series colors as ``#rrggbb``.
    filters : list of Filter, optional
        Conditions of the local filter.
    numeric : dict of str to bool, optional
        Whether each column is numeric. A numeric row, col or wrap column is
        cut into `FACET_BINS` intervals (`ddviz.compute.cuts`); a numeric color
        column is a gradient, or cut by `color_bins`. An x or y column
        missing is numeric; the others, categorical.
    color_bins : Binning, optional
        How to cut a numeric color column; None draws it as a gradient.
    max_levels : int, optional
        Most levels a categorical x, y, color, row, col or wrap column may
        have.
    wrap_cols : int, optional
        Wrapped panels to a row (`parse_wrap_cols`); None to make them
        closest to square.

    Returns
    -------
    ScatterSpec
        What the worker aggregates.

    Raises
    ------
    ValueError
        When x or y has no column, wrap has one beside row, col or the
        n-th axes, or the elements have none that can be drawn.
    """
    if not encoding.x or not encoding.y:
        raise ValueError("x and y need a column")
    if not set(encoding.elements) & set(DRAWN_ELEMENTS):
        raise ValueError(f"elements need one of {DRAWN_ELEMENTS}")
    wrap = encoding.wrap is not None
    if wrap and (encoding.row is not None or encoding.col is not None):
        raise ValueError("wrap cannot be placed with row or col")
    if wrap and (len(encoding.x) > 1 or len(encoding.y) > 1):
        raise ValueError("wrap cannot be placed with the n-th axes")
    col = encoding.wrap if wrap else encoding.col
    hover = drawn_columns(encoding)
    filters = list(filters or [])
    numeric = numeric or {}
    binned = {
        role: Binning(FACET_BINS, "rows", values_up_to=FACET_BINS)
        for role, column in (("row", encoding.row), ("col", col))
        if numeric.get(column)
    }
    gradient = bool(numeric.get(encoding.color))
    if gradient and color_bins is not None:
        binned["color"] = color_bins
        gradient = False
    read = dict.fromkeys([*hover, *(f.column for f in filters)])
    return ScatterSpec(
        files={c: files[c] for c in read},
        x=list(encoding.x),
        y=list(encoding.y),
        color=encoding.color,
        row=encoding.row,
        col=col,
        width=width,
        height=height,
        hover=hover,
        colors=colors,
        binned=binned,
        gradient=gradient,
        filters=filters,
        max_levels=max_levels,
        wrap=wrap,
        wrap_cols=wrap_cols if wrap else None,
        categorical=[
            c
            for c in dict.fromkeys([*encoding.x, *encoding.y])
            if not numeric.get(c, True)
        ],
        points="points" in encoding.elements,
        box="box" in encoding.elements and has_box_pair(encoding, numeric),
    )


def parse_color_bins(raw: dict | None) -> Binning | None:
    """Return how the page asks to cut a numeric color column, checked.

    Parameters
    ----------
    raw : dict or None
        ``{"n": int, "by": "rows" | "values"}``, or None for a gradient.

    Returns
    -------
    Binning or None
        The binning.

    Raises
    ------
    ValueError
        When `raw` has another form, or `n` is not one of `COLOR_BINS`.
    """
    if raw is None:
        return None
    if (
        not isinstance(raw, dict)
        or set(raw) != {"n", "by"}
        or raw["n"] not in COLOR_BINS
        or raw["by"] not in ("rows", "values")
    ):
        raise ValueError(
            f"color bins are n in {COLOR_BINS} and by rows or values: {raw}"
        )
    return Binning(raw["n"], raw["by"])


def parse_wrap_cols(raw: object) -> int | None:
    """Return how many wrapped panels the page asks to put in a row, checked.

    Parameters
    ----------
    raw : object
        A positive int, or None to make the panels closest to square.

    Returns
    -------
    int or None
        The number.

    Raises
    ------
    ValueError
        For anything else.
    """
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError(f"wrap_cols is a positive int or null: {raw}")
    return raw
