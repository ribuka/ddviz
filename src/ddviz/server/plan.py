"""Turns the graph the user built (`ddviz.server.encoding.Encoding`) into what a worker draws."""

from __future__ import annotations

import math

from ddviz.server.encoding import Encoding
from ddviz.shared.scatter import (
    MAX_LEVELS,
    ONE_BAND,
    POINT_SIZE,
    SHAPE_SIZE,
    Binning,
    Filter,
    ScatterSpec,
    Smoothing,
)
from ddviz.shared.shapes import SHAPES

# A numeric column on Group X or Group Y is cut into this many intervals of
# about the same number of rows, unless it has at most this many values,
# each then a level of its own.
FACET_BINS = 5
# Numbers of intervals a numeric color column can be cut into.
COLOR_BINS = (2, 3, 5, 10)
# Methods of the smoothing lines (`ddviz.compute.smooth`).
SMOOTH_METHODS = ("gcv", "csaps", "lowess")
# Sizes in pixels the markers can take: the shapes of the overlay levels, or
# the circles without an overlay.
SHAPE_SIZES = (3, 5, 7, 9, 11, 15)


def one_band(encoding: Encoding, numeric: dict[str, bool]) -> bool:
    """Return whether the graph draws every row in one band along x: X is empty and Y holds numeric columns only.

    Parameters
    ----------
    encoding : Encoding
        The graph.
    numeric : dict of str to bool
        Whether each column is numeric; a missing one is numeric.

    Returns
    -------
    bool
        Whether the x axis is the one band (`ddviz.shared.scatter.ONE_BAND`).
    """
    return (
        not encoding.x
        and bool(encoding.y)
        and all(numeric.get(y, True) for y in encoding.y)
    )


def drawable(encoding: Encoding, numeric: dict[str, bool]) -> bool:
    """Return whether the graph has a scatter plot: x and y columns, or numeric y columns alone (`one_band`).

    Parameters
    ----------
    encoding : Encoding
        The graph.
    numeric : dict of str to bool
        Whether each column is numeric; a missing one is numeric.

    Returns
    -------
    bool
        Whether it is drawn.
    """
    return bool(encoding.x and encoding.y) or one_band(encoding, numeric)


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
        Whether such a pair exists; the one band (`one_band`) is a
        categorical x.
    """
    return one_band(encoding, numeric) or (
        any(not numeric.get(x, True) for x in encoding.x)
        and any(numeric.get(y, True) for y in encoding.y)
    )


def has_smooth_pair(encoding: Encoding, numeric: dict[str, bool]) -> bool:
    """Return whether a pair of the graph's axis columns can have smoothing lines: a numeric x and a numeric y.

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
    return any(numeric.get(x, True) for x in encoding.x) and any(
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
        ``"box"`` without a pair of a categorical x and a numeric y
        (`has_box_pair`), and ``"smooth"`` without a pair of a numeric x
        and a numeric y (`has_smooth_pair`).
    """
    return [
        e
        for e in encoding.elements
        if (e == "box" and not has_box_pair(encoding, numeric))
        or (e == "smooth" and not has_smooth_pair(encoding, numeric))
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
        The x and y columns and the color, overlay, row, col and wrap
        columns, once each.
    """
    columns = [
        *encoding.x,
        *encoding.y,
        encoding.color,
        encoding.overlay,
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
        "levels"}`` or ``{"column", "contains"}`` (a non-empty text) for a
        categorical one; one per column.
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
        keys = {"column", "range", "levels", "contains"}
        if not isinstance(item, dict) or not set(item) <= keys:
            raise ValueError(
                f"a filter has a column and a range, levels or contains: {item}"
            )
        column = item.get("column")
        if column not in numeric:
            raise ValueError(f"unknown filter column: {column}")
        bounds, levels = item.get("range"), item.get("levels")
        contains = item.get("contains")
        if numeric[column]:
            ok = (
                levels is None
                and contains is None
                and isinstance(bounds, list)
                and len(bounds) == 2
                and all(isinstance(b, int | float) and math.isfinite(b) for b in bounds)
                and bounds[0] <= bounds[1]
            )
            if not ok:
                raise ValueError(f"{column} needs a range [lo, hi]")
            filters.append(Filter(column, range=[float(b) for b in bounds]))
        elif contains is not None:
            ok = (
                bounds is None
                and levels is None
                and isinstance(contains, str)
                and contains
            )
            if not ok:
                raise ValueError(f"{column} needs a non-empty text to contain")
            filters.append(Filter(column, contains=contains))
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
    smoothing: Smoothing | None = None,
    shape_size: int | None = None,
    temporal: dict[str, str] | None = None,
    shape_sizes: dict[str, int] | None = None,
    level_shapes: dict[str, str] | None = None,
) -> ScatterSpec:
    """Return the overview scatter plot of a graph.

    Every pair of an x and a y column is drawn in a panel of each facet
    cell, colored by color and faceted by row and col. Overlay draws the
    points in a marker shape per level (`ScatterSpec.overlay`) beside a
    color column; alone, it colors the series as color would, without
    shapes (as JMP does). The panels of a categorical x and a numeric y have box
    plots when the elements have them (`ScatterSpec.box`), and those of a
    numeric x and a numeric y smoothing lines (`ScatterSpec.smooth`); the
    other panels draw the points even without the points element. A categorical x or y column is drawn in bands, one per
    level (`ScatterSpec.categorical`); without an x column, every row lies
    in one band (`one_band`), a categorical x of its own. A wrap column takes the col role of the spec, its levels
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
        Whether each column is numeric. A numeric row, col, wrap or
        overlay (beside color) column is cut into `FACET_BINS` intervals
        (`ddviz.compute.cuts`); a numeric color column is a gradient, or cut
        by `color_bins`. An x or y column
        missing is numeric; the others, categorical.
    color_bins : Binning, optional
        How to cut a numeric color column; None draws it as a gradient.
    max_levels : int, optional
        Most levels a categorical x, y, color, overlay, row, col or wrap
        column may have.
    wrap_cols : int, optional
        Wrapped panels to a row (`parse_wrap_cols`); None to make them
        closest to square.
    smoothing : Smoothing, optional
        How to fit the smoothing lines (`parse_smoothing`); None for the
        default.
    shape_size : int, optional
        Size of the markers in pixels (`parse_shape_size`); None for the
        default, `SHAPE_SIZE` for the overlay's shapes and `POINT_SIZE` for
        the circles without an overlay.
    temporal : dict of str to str, optional
        The kind of each temporal column (`ddviz.shared.temporal.KINDS`);
        such a column is numeric in `numeric` too.
    shape_sizes : dict of str to int, optional
        Size of the shapes of single overlay levels, by the level's name
        (`parse_shape_sizes`), in place of `shape_size`; dropped without
        shapes (overlay alone colors the series).
    level_shapes : dict of str to str, optional
        Shape of single overlay levels, by the level's name
        (`parse_level_shapes`), in place of the shape of the level's place;
        dropped without shapes, as `shape_sizes`.

    Returns
    -------
    ScatterSpec
        What the worker aggregates.

    Raises
    ------
    ValueError
        When the graph is not `drawable`, or wrap has a column beside row,
        col or the n-th axes.
    """
    numeric = numeric or {}
    if not drawable(encoding, numeric):
        raise ValueError("x and y need a column, or y numeric columns alone")
    # Without an x column, every row lies in one band.
    x = list(encoding.x) or [ONE_BAND]
    wrap = encoding.wrap is not None
    if wrap and (encoding.row is not None or encoding.col is not None):
        raise ValueError("wrap cannot be placed with row or col")
    if wrap and (len(encoding.x) > 1 or len(encoding.y) > 1):
        raise ValueError("wrap cannot be placed with the n-th axes")
    col = encoding.wrap if wrap else encoding.col
    color, overlay = encoding.color, encoding.overlay
    if color is None:
        # Overlay alone colors the series, without shapes.
        color, overlay = overlay, None
    hover = drawn_columns(encoding)
    filters = list(filters or [])
    binned = {
        role: Binning(FACET_BINS, "rows", values_up_to=FACET_BINS)
        for role, column in (("overlay", overlay), ("row", encoding.row), ("col", col))
        if numeric.get(column)
    }
    gradient = bool(numeric.get(color))
    if gradient and color_bins is not None:
        binned["color"] = color_bins
        gradient = False
    read = dict.fromkeys([*hover, *(f.column for f in filters)])
    band = {ONE_BAND: []} if x == [ONE_BAND] else {}
    return ScatterSpec(
        files={**{c: files[c] for c in read}, **band},
        x=x,
        y=list(encoding.y),
        color=color,
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
            for c in dict.fromkeys([*x, *encoding.y])
            if c == ONE_BAND or not numeric.get(c, True)
        ],
        points="points" in encoding.elements,
        box="box" in encoding.elements and has_box_pair(encoding, numeric),
        smooth=(smoothing or Smoothing())
        if "smooth" in encoding.elements and has_smooth_pair(encoding, numeric)
        else None,
        overlay=overlay,
        shape_size=shape_size or (POINT_SIZE if overlay is None else SHAPE_SIZE),
        shape_sizes=dict(shape_sizes or {}) if overlay is not None else {},
        level_shapes=dict(level_shapes or {}) if overlay is not None else {},
        temporal={c: k for c, k in (temporal or {}).items() if c in read},
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


def parse_smoothing(raw: dict | None) -> Smoothing | None:
    """Return how the page asks to fit the smoothing lines, checked.

    Parameters
    ----------
    raw : dict or None
        ``{"method": "gcv"}``, ``{"method": "csaps", "p": float | None}``
        or ``{"method": "lowess", "frac": float}``; None for the default.

    Returns
    -------
    Smoothing or None
        The smoothing.

    Raises
    ------
    ValueError
        When `raw` has another form, ``p`` is not from 0 to 1 or ``frac``
        not above 0 and at most 1.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("method") not in SMOOTH_METHODS:
        raise ValueError(f"smooth needs a method in {SMOOTH_METHODS}: {raw}")
    method = raw["method"]
    allowed = {"gcv": set(), "csaps": {"p"}, "lowess": {"frac"}}[method]
    if not set(raw) - {"method"} <= allowed:
        raise ValueError(f"{method} takes only {sorted(allowed)}: {raw}")
    p, frac = raw.get("p"), raw.get("frac", Smoothing.frac)

    def number(v: object) -> bool:
        return (
            isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
        )

    if p is not None and not (number(p) and 0 <= p <= 1):
        raise ValueError(f"p is from 0 to 1 or null: {p}")
    if not (number(frac) and 0 < frac <= 1):
        raise ValueError(f"frac is above 0 and at most 1: {frac}")
    return Smoothing(method, None if p is None else float(p), float(frac))


def parse_shape_size(raw: object) -> int | None:
    """Return the size of the markers the page asks for, checked.

    Parameters
    ----------
    raw : object
        One of `SHAPE_SIZES`, or None for the default.

    Returns
    -------
    int or None
        The size in pixels, or None for the default (`scatter_spec`).

    Raises
    ------
    ValueError
        For anything else.
    """
    if raw is None:
        return None
    if isinstance(raw, bool) or raw not in SHAPE_SIZES:
        raise ValueError(f"shape_size is one of {SHAPE_SIZES} or null: {raw}")
    return int(raw)


def parse_shape_sizes(raw: dict[str, object] | None) -> dict[str, int]:
    """Return the sizes the page asks for the shapes of single overlay levels, checked.

    Parameters
    ----------
    raw : dict of str to object, or None
        A level's name to one of `SHAPE_SIZES`, or None for none.

    Returns
    -------
    dict of str to int
        The size in pixels of each level named.

    Raises
    ------
    ValueError
        For anything else.
    """
    if raw is None:
        return {}
    sizes = {}
    for level, size in raw.items():
        sizes[level] = parse_shape_size(size)
        if sizes[level] is None:
            raise ValueError(f"shape_sizes has no size for {level!r}")
    return sizes


def parse_level_shapes(raw: dict[str, object] | None) -> dict[str, str]:
    """Return the shapes the page asks for single overlay levels, checked.

    Parameters
    ----------
    raw : dict of str to object, or None
        A level's name to one of `ddviz.shared.shapes.SHAPES`, or None for
        none.

    Returns
    -------
    dict of str to str
        The shape of each level named.

    Raises
    ------
    ValueError
        For anything else.
    """
    if raw is None:
        return {}
    for level, shape in raw.items():
        if not isinstance(shape, str) or shape not in SHAPES:
            raise ValueError(
                f"level_shapes has no shape of {SHAPES} for {level!r}: {shape}"
            )
    return dict(raw)


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
