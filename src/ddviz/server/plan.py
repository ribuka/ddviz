"""Turns the graph the user built (`ddviz.server.encoding.Encoding`) into what a worker draws."""

from __future__ import annotations

import math

from ddviz.server.encoding import Encoding
from ddviz.shared.axisscale import parse_axis_scales
from ddviz.shared.layout import MARGIN_BOTTOM, MARGIN_LEFT, bottom_margin, left_margin
from ddviz.shared.scatter import (
    LINE_WIDTH,
    MAX_AXIS_LEVELS,
    MAX_LEVELS,
    ONE_BAND,
    POINT_SIZE,
    SHAPE_SIZE,
    Binning,
    Filter,
    RefStat,
    ScatterSpec,
    Smoothing,
)

# A numeric column on Group X or Group Y is cut into this many intervals of
# about the same number of rows, unless it has at most this many values,
# each then a level of its own.
FACET_BINS = 5


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


def has_line_pair(encoding: Encoding, numeric: dict[str, bool]) -> bool:
    """Return whether a pair of the graph's axis columns can join its points with lines: any x column and a numeric y.

    A temporal column is numeric; a categorical x joins its levels' bands
    in their order. Without an x column, there are no lines.

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
    return bool(encoding.x) and any(numeric.get(y, True) for y in encoding.y)


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
        (`has_box_pair`), ``"smooth"`` without a pair of a numeric x
        and a numeric y (`has_smooth_pair`), and ``"line"`` without an x
        column and a numeric y (`has_line_pair`).
    """
    return [
        e
        for e in encoding.elements
        if (e == "box" and not has_box_pair(encoding, numeric))
        or (e == "smooth" and not has_smooth_pair(encoding, numeric))
        or (e == "line" and not has_line_pair(encoding, numeric))
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
        The x and y columns and the color, symbol, row, col and wrap
        columns, once each.
    """
    columns = [
        *encoding.x,
        *encoding.y,
        encoding.color,
        encoding.symbol,
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
        "levels"}`` or ``{"column", "contains"}`` (a text that is not blank) for a
        categorical one; one per column. Each may hold ``"nulls"`` (bool,
        default False): whether the missing rows pass too
        (`ddviz.shared.scatter.Filter`). A numeric column may hold only
        ``"nulls": False`` (its rows that are not missing), a categorical one
        only ``"nulls": True`` or empty ``levels`` with it (its missing rows).
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
        keys = {"column", "range", "levels", "contains", "nulls"}
        if not isinstance(item, dict) or not set(item) <= keys:
            raise ValueError(
                f"a filter has a column and a range, levels, contains or nulls: {item}"
            )
        column = item.get("column")
        if column not in numeric:
            raise ValueError(f"unknown filter column: {column}")
        bounds, levels = item.get("range"), item.get("levels")
        contains, nulls = item.get("contains"), item.get("nulls", False)
        ok = isinstance(nulls, bool)
        if not ok:
            raise ValueError(f"{column}: nulls must be true or false")
        if numeric[column]:
            if levels is not None or contains is not None:
                raise ValueError(f"{column} needs a range [lo, hi]")
            if bounds is None:
                if item.get("nulls") is not False:
                    raise ValueError(f"{column} needs a range [lo, hi]")
                filters.append(Filter(column))
                continue
            ok = (
                isinstance(bounds, list)
                and len(bounds) == 2
                and all(isinstance(b, int | float) and math.isfinite(b) for b in bounds)
                and bounds[0] <= bounds[1]
            )
            if not ok:
                raise ValueError(f"{column} needs a range [lo, hi]")
            filters.append(
                Filter(column, range=[float(b) for b in bounds], nulls=nulls)
            )
        elif contains is not None:
            ok = (
                bounds is None
                and levels is None
                and isinstance(contains, str)
                and contains.strip()
            )
            if not ok:
                raise ValueError(f"{column} needs a text that is not blank to contain")
            filters.append(Filter(column, contains=contains, nulls=nulls))
        elif levels is None and bounds is None:
            if not nulls:
                raise ValueError(f"{column} needs a list of levels")
            filters.append(Filter(column, nulls=True))
        else:
            ok = (
                bounds is None
                and isinstance(levels, list)
                and (len(levels) > 0 or nulls)
                and all(isinstance(v, str) for v in levels)
            )
            if not ok:
                raise ValueError(f"{column} needs a list of levels")
            filters.append(Filter(column, levels=list(levels), nulls=nulls))
    columns = [f.column for f in filters]
    if len(set(columns)) != len(columns):
        raise ValueError("one filter per column")
    return filters


def color_kind(
    color: str | None, numeric: dict[str, bool], color_bins: Binning | None
) -> str | None:
    """Return how a color column draws: ``"gradient"``, ``"bins"`` (intervals), or None for a categorical one or none.

    Parameters
    ----------
    color : str or None
        The color column.
    numeric : dict of str to bool
        Whether each column is numeric (a temporal one is).
    color_bins : Binning or None
        How a numeric color column is cut, or None for a gradient.

    Returns
    -------
    str or None
        The kind, as `scatter_spec` makes it.
    """
    if not numeric.get(color):
        return None
    return "gradient" if color_bins is None else "bins"


def cut_roles(encoding: Encoding, numeric: dict[str, bool]) -> list[str]:
    """Return the roles cut into intervals by `FACET_BINS`: those of a numeric symbol, row and col (wrap's) column.

    Parameters
    ----------
    encoding : Encoding
        The graph.
    numeric : dict of str to bool
        Whether each column is numeric (a temporal one is).

    Returns
    -------
    list of str
        The roles, as `scatter_spec` cuts them.
    """
    col = encoding.wrap if encoding.wrap is not None else encoding.col
    return [
        role
        for role, column in (
            ("symbol", encoding.symbol),
            ("row", encoding.row),
            ("col", col),
        )
        if numeric.get(column)
    ]


def categorical_axes(encoding: Encoding, numeric: dict[str, bool]) -> list[str]:
    """Return the categorical x and y columns of a graph: those drawn in bands, one per level.

    Parameters
    ----------
    encoding : Encoding
        The graph.
    numeric : dict of str to bool
        Whether each column is numeric (a temporal one is).

    Returns
    -------
    list of str
        The columns, once each, as `scatter_spec` makes them
        `ScatterSpec.categorical`, but the one band of a graph without x,
        which is no column.
    """
    return [
        c
        for c in dict.fromkeys([*encoding.x, *encoding.y])
        if not numeric.get(c, True)
    ]


def scatter_spec(
    encoding: Encoding,
    files: dict[str, list[str]],
    width: int,
    height: int,
    colors: list[str],
    *,
    filters: list[Filter] | None = None,
    numeric: dict[str, bool] | None = None,
    color_bins: Binning | None = None,
    max_levels: int = MAX_LEVELS,
    max_axis_levels: int = MAX_AXIS_LEVELS,
    wrap_cols: int | None = None,
    smoothing: Smoothing | None = None,
    shape_size: int | None = None,
    temporal: dict[str, str] | None = None,
    shape_sizes: dict[str, int] | None = None,
    level_shapes: dict[str, str] | None = None,
    show_null_rows: dict[str, bool] | None = None,
    axis_scales: object = None,
    margin_left: int = MARGIN_LEFT,
    margin_bottom: int = MARGIN_BOTTOM,
    line_width: int | None = None,
    line_aggregation: str = "raw",
    keep_unfiltered_color_levels: bool = False,
    keep_unfiltered_symbol_levels: bool = False,
    keep_unfiltered_axis_levels: list[str] | None = None,
    ref_stats: list[RefStat] | None = None,
) -> ScatterSpec:
    """Return the overview scatter plot of a graph.

    Every pair of an x and a y column is drawn in a panel of each facet
    cell, colored by color and faceted by row and col. Symbol draws the
    points in a marker shape per level (`ScatterSpec.symbol`), with or
    without a color column; without one, the points have the one color. The panels of a categorical x and a numeric y have box
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
        symbol column is cut into `FACET_BINS` intervals
        (`ddviz.compute.cuts`); a numeric color column is a gradient, or cut
        by `color_bins`. An x or y column
        missing is numeric; the others, categorical.
    color_bins : Binning, optional
        How to cut a numeric color column; None draws it as a gradient.
    max_levels : int, optional
        Most levels a categorical color, symbol, row, col or wrap column
        may have.
    max_axis_levels : int, optional
        Most levels a categorical x or y column may have.
    wrap_cols : int, optional
        Wrapped panels to a row
        (`ddviz.server.plotoptions.parse_wrap_cols`); None to make them
        closest to square.
    smoothing : Smoothing, optional
        How to fit the smoothing lines
        (`ddviz.server.plotoptions.parse_smoothing`); None for the default.
    shape_size : int, optional
        Size of the markers in pixels
        (`ddviz.server.plotoptions.parse_shape_size`); None for the
        default, `SHAPE_SIZE` for the symbol's shapes and `POINT_SIZE` for
        the circles without a symbol.
    temporal : dict of str to str, optional
        The kind of each temporal column (`ddviz.shared.temporal.KINDS`);
        such a column is numeric in `numeric` too.
    shape_sizes : dict of str to int, optional
        Size of the shapes of single symbol levels, by the level's name
        (`ddviz.server.plotoptions.parse_shape_sizes`), in place of
        `shape_size`; dropped without a symbol.
    level_shapes : dict of str to str, optional
        Shape of single symbol levels, by the level's name
        (`ddviz.server.plotoptions.parse_level_shapes`), in place of the
        shape of the level's place; dropped without shapes, as
        `shape_sizes`.
    show_null_rows : dict of str to bool, optional
        Whether the ``"color"``, ``"symbol"``, ``"row"``, ``"col"`` and
        ``"wrap"`` of the graph draw their rows with a null or NaN value
        (`ScatterSpec.null_roles`); a role left out does. None for all.
        The wrap's column, the spec's col, takes the ``"wrap"`` setting,
        not the ``"col"`` one.
    axis_scales : object, optional
        The scale of each placed x and y column, as the request has it
        (`ddviz.shared.axisscale.parse_axis_scales`); None for all linear.
    margin_left : int, optional
        Left margin the page asks for, in pixels; kept within the width
        (`ddviz.shared.layout.left_margin`).
    margin_bottom : int, optional
        Bottom margin the page asks for, in pixels; kept within the height
        (`ddviz.shared.layout.bottom_margin`).
    line_width : int, optional
        Width of the lines joining the points in pixels
        (`ddviz.server.plotoptions.parse_line_width`); None for the
        default, `LINE_WIDTH`. The lines are drawn with the ``"line"``
        element, in the panels of a numeric y (`ScatterSpec.line_width`).
    line_aggregation : str, optional
        How the lines treat the rows of one x
        (`ddviz.server.plotoptions.parse_line_aggregation`,
        `ScatterSpec.line_aggregation`).
    keep_unfiltered_color_levels : bool, optional
        Whether a categorical color column keeps its levels over every row
        (`ScatterSpec.keep_unfiltered_color_levels`).
    keep_unfiltered_symbol_levels : bool, optional
        Whether a categorical symbol column keeps its levels over every row
        (`ScatterSpec.keep_unfiltered_symbol_levels`).
    keep_unfiltered_axis_levels : list of str, optional
        The categorical x and y columns whose bands are the levels over
        every row (`ddviz.server.plotoptions.parse_keep_axis_levels`,
        `ScatterSpec.keep_unfiltered_axis_levels`); None for none.
    ref_stats : list of RefStat, optional
        The statistics of the reference lines the page asks for, by column
        (`ddviz.server.plotoptions.parse_ref_stats`): those of the
        numeric x and y columns of the graph that are not temporal are
        kept (`ScatterSpec.ref_stats`), the others left out without an
        error, as the page keeps its lines by column for every graph.
        None for none.

    Returns
    -------
    ScatterSpec
        What the worker aggregates.

    Raises
    ------
    ValueError
        When the graph is not `drawable`, or wrap has a column beside row,
        col or the n-th axes, or `axis_scales` is wrong.
    """
    numeric = numeric or {}
    if not drawable(encoding, numeric):
        raise ValueError("x and y need a column, or y numeric columns alone")
    # Without an x column, every row lies in one band.
    x = list(encoding.x) or [ONE_BAND]
    log_x, log_y = parse_axis_scales(
        axis_scales, list(encoding.x), list(encoding.y), numeric, temporal or {}
    )
    wrap = encoding.wrap is not None
    if wrap and (encoding.row is not None or encoding.col is not None):
        raise ValueError("wrap cannot be placed with row or col")
    if wrap and (len(encoding.x) > 1 or len(encoding.y) > 1):
        raise ValueError("wrap cannot be placed with the n-th axes")
    col = encoding.wrap if wrap else encoding.col
    color, symbol = encoding.color, encoding.symbol
    show = dict.fromkeys(("color", "symbol", "row", "col", "wrap"), True)
    show.update(show_null_rows or {})
    null_roles = [
        role
        for role, column, setting in (
            ("color", color, "color"),
            ("symbol", symbol, "symbol"),
            ("row", encoding.row, "row"),
            ("col", col, "wrap" if wrap else "col"),
        )
        if column and show[setting]
    ]
    hover = drawn_columns(encoding)
    filters = list(filters or [])
    binned = {
        role: Binning(FACET_BINS, "rows", values_up_to=FACET_BINS)
        for role in cut_roles(encoding, numeric)
    }
    kind = color_kind(color, numeric, color_bins)
    gradient = kind == "gradient"
    if kind == "bins":
        binned["color"] = color_bins
    read = dict.fromkeys([*hover, *(f.column for f in filters)])
    band = {ONE_BAND: []} if x == [ONE_BAND] else {}
    categorical = [
        c
        for c in dict.fromkeys([*x, *encoding.y])
        if c == ONE_BAND or not numeric.get(c, True)
    ]
    axis_columns = set(x) | set(encoding.y)
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
        max_axis_levels=max_axis_levels,
        wrap=wrap,
        wrap_cols=wrap_cols if wrap else None,
        categorical=categorical,
        points="points" in encoding.elements,
        box="box" in encoding.elements and has_box_pair(encoding, numeric),
        smooth=(smoothing or Smoothing())
        if "smooth" in encoding.elements and has_smooth_pair(encoding, numeric)
        else None,
        line_width=(line_width or LINE_WIDTH)
        if "line" in encoding.elements and has_line_pair(encoding, numeric)
        else None,
        line_aggregation=line_aggregation,
        symbol=symbol,
        shape_size=shape_size or (POINT_SIZE if symbol is None else SHAPE_SIZE),
        shape_sizes=dict(shape_sizes or {}) if symbol is not None else {},
        level_shapes=dict(level_shapes or {}) if symbol is not None else {},
        temporal={c: k for c, k in (temporal or {}).items() if c in read},
        null_roles=null_roles,
        log_x=log_x,
        log_y=log_y,
        margin_left=left_margin(margin_left, width),
        margin_bottom=bottom_margin(margin_bottom, height),
        keep_unfiltered_color_levels=keep_unfiltered_color_levels,
        keep_unfiltered_symbol_levels=keep_unfiltered_symbol_levels,
        keep_unfiltered_axis_levels=list(keep_unfiltered_axis_levels or []),
        ref_stats=[
            r
            for r in ref_stats or []
            if r.column in axis_columns
            and r.column not in categorical
            and r.column not in (temporal or {})
        ],
    )
