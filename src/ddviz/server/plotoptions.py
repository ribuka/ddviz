"""How the page asks to draw a plot (`POST /api/plot`), checked."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import pairwise

from ddviz.server.models import PlotRequest, ShowNullRows
from ddviz.shared.scatter import (
    LINE_AGGREGATIONS,
    Binning,
    RefStat,
    ScatterSpec,
    Smoothing,
)
from ddviz.shared.shapes import SHAPES

# The fewest intervals a numeric color column can be cut into.
COLOR_BINS_MIN = 2
# The largest integer JavaScript holds exactly (``Number.MAX_SAFE_INTEGER``),
# so that the page and the server take the same numbers of intervals.
MAX_SAFE_INTEGER = 2**53 - 1
# Methods of the smoothing lines (`ddviz.compute.smooth`).
SMOOTH_METHODS = ("gcv", "csaps", "lowess")
# Sizes in pixels the markers can take: the shapes of the symbol levels, or
# the circles without a symbol.
SHAPE_SIZES = (3, 5, 7, 9, 11, 15)
# Widths in pixels the lines joining the points can take.
LINE_WIDTHS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class PlotOptions:
    """How the page asks to draw a plot (`POST /api/plot`), checked: the settings `ddviz.server.plan.scatter_spec` takes beside the graph.

    The axes' scales, the margins, the most levels and the temporal columns
    are not settings of the drawing and stay apart, as the page's
    ``PlotOptions`` (``static/js/plotoptions.js``) leaves the axes out.

    Attributes
    ----------
    color_bins : Binning or None
        How to cut a numeric color column (`parse_color_bins`); None draws
        it as a gradient.
    wrap_cols : int or None
        Wrapped panels to a row (`parse_wrap_cols`); None to make them
        closest to square.
    smoothing : Smoothing or None
        How to fit the smoothing lines (`parse_smoothing`); None for the
        default.
    shape_size : int or None
        Size of the markers in pixels (`parse_shape_size`); None for the
        default, `ddviz.shared.scatter.SHAPE_SIZE` for the symbol's shapes
        and `ddviz.shared.scatter.POINT_SIZE` for the circles without a
        symbol.
    line_width : int or None
        Width of the lines joining the points in pixels
        (`parse_line_width`); None for the default,
        `ddviz.shared.scatter.LINE_WIDTH`. The lines are drawn with the
        ``"line"`` element, in the panels of a numeric y
        (`ddviz.shared.scatter.ScatterSpec.line_width`).
    line_aggregation : str
        How the lines treat the rows of one x (`parse_line_aggregation`,
        `ddviz.shared.scatter.ScatterSpec.line_aggregation`).
    shape_sizes : dict of str to int
        Size of the shapes of single symbol levels, by the level's name
        (`parse_shape_sizes`), in place of `shape_size`; dropped without a
        symbol.
    level_shapes : dict of str to str
        Shape of single symbol levels, by the level's name
        (`parse_level_shapes`), in place of the shape of the level's place;
        dropped without shapes, as `shape_sizes`.
    ref_stats : list of RefStat
        The statistics of the reference lines the page asks for, by column
        (`parse_ref_stats`): those of the numeric x and y columns of the
        graph that are not temporal are kept
        (`ddviz.shared.scatter.ScatterSpec.ref_stats`), the others left out
        without an error, as the page keeps its lines by column for every
        graph.
    show_null_rows : dict of str to bool
        Whether the ``"color"``, ``"symbol"``, ``"row"``, ``"col"`` and
        ``"wrap"`` of the graph draw their rows with a null or NaN value
        (`ddviz.shared.scatter.ScatterSpec.null_roles`); a role left out
        does, and each does by default
        (`ddviz.server.models.ShowNullRows`). The wrap's column, the spec's
        col, takes the ``"wrap"`` setting, not the ``"col"`` one.
    keep_unfiltered_color_levels : bool
        Whether a categorical color column keeps its levels over every row
        (`ddviz.shared.scatter.ScatterSpec.keep_unfiltered_color_levels`).
    keep_unfiltered_symbol_levels : bool
        Whether a categorical symbol column keeps its levels over every row
        (`ddviz.shared.scatter.ScatterSpec.keep_unfiltered_symbol_levels`).
    keep_unfiltered_axis_levels : list of str
        The categorical x and y columns whose bands are the levels over
        every row (`parse_keep_axis_levels`,
        `ddviz.shared.scatter.ScatterSpec.keep_unfiltered_axis_levels`).
    color_scale : dict or None
        The color scale of a numeric color column the page keeps under the
        lock of the axes (`parse_color_scale`,
        `ddviz.shared.scatter.ScatterSpec.color_scale`); None for that of
        the filter.
    cuts : dict of str to dict
        The cuts of the numeric symbol, row and col columns the page keeps
        under the lock of the axes, by role (`parse_cuts`,
        `ddviz.shared.scatter.ScatterSpec.kept_cuts`); a role left out
        takes the cuts of the filter.
    """

    color_bins: Binning | None = None
    wrap_cols: int | None = None
    smoothing: Smoothing | None = None
    shape_size: int | None = None
    line_width: int | None = None
    line_aggregation: str = "raw"
    shape_sizes: dict[str, int] = field(default_factory=dict)
    level_shapes: dict[str, str] = field(default_factory=dict)
    ref_stats: list[RefStat] = field(default_factory=list)
    show_null_rows: dict[str, bool] = field(
        default_factory=lambda: ShowNullRows().model_dump()
    )
    keep_unfiltered_color_levels: bool = False
    keep_unfiltered_symbol_levels: bool = False
    keep_unfiltered_axis_levels: list[str] = field(default_factory=list)
    color_scale: dict | None = None
    cuts: dict[str, dict] = field(default_factory=dict)


def parse_plot_options(request: PlotRequest, max_levels: int) -> PlotOptions:
    """Return the settings of the drawing a plot request asks for, checked.

    The settings checked against the graph's columns
    (``keep_unfiltered_axis_levels``, ``color_scale`` and ``cuts``) are left
    at their defaults: ``POST /api/plot`` checks them after the unknown
    columns, with `parse_keep_axis_levels`, `parse_color_scale` and
    `parse_cuts`.

    Parameters
    ----------
    request : PlotRequest
        The body of ``POST /api/plot``.
    max_levels : int
        Most intervals of a numeric color column (``plot.max_levels``).

    Returns
    -------
    PlotOptions
        The settings.

    Raises
    ------
    ValueError
        From the first setting of another form, as its ``parse_*`` raises it.
    """
    return PlotOptions(
        color_bins=parse_color_bins(request.color_bins, max_levels),
        wrap_cols=parse_wrap_cols(request.wrap_cols),
        smoothing=parse_smoothing(request.smooth),
        shape_size=parse_shape_size(request.shape_size),
        line_width=parse_line_width(request.line_width),
        line_aggregation=parse_line_aggregation(request.line_aggregation),
        shape_sizes=parse_shape_sizes(request.shape_sizes),
        level_shapes=parse_level_shapes(request.level_shapes),
        ref_stats=parse_ref_stats(request.ref_stats),
        show_null_rows=request.show_null_rows.model_dump(),
        keep_unfiltered_color_levels=request.keep_unfiltered_color_levels,
        keep_unfiltered_symbol_levels=request.keep_unfiltered_symbol_levels,
    )


def is_int(value: object) -> bool:
    """Return whether a value is a JSON integer: an int, not a bool.

    Parameters
    ----------
    value : object
        A value of the request.

    Returns
    -------
    bool
        Whether it is an int and not a bool; ``7.0`` and ``"7"`` are not.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def parse_color_bins(raw: dict | None, max_levels: int) -> Binning | None:
    """Return how the page asks to cut a numeric color column, checked.

    Parameters
    ----------
    raw : dict or None
        ``{"n": int, "by": "rows" | "values"}``, or None for a gradient.
    max_levels : int
        Most intervals taken (``plot.max_levels``); the number is also at most
        `MAX_SAFE_INTEGER`.

    Returns
    -------
    Binning or None
        The binning.

    Raises
    ------
    ValueError
        When `raw` has another form, or `n` is not an integer from
        `COLOR_BINS_MIN` to the limit.
    """
    if raw is None:
        return None
    top = min(max_levels, MAX_SAFE_INTEGER)
    if (
        not isinstance(raw, dict)
        or set(raw) != {"n", "by"}
        or not is_int(raw["n"])
        or not COLOR_BINS_MIN <= raw["n"] <= top
        or raw["by"] not in ("rows", "values")
    ):
        raise ValueError(
            f"color_bins are n, an integer from {COLOR_BINS_MIN} to {top}, "
            f"and by rows or values: {raw}"
        )
    return Binning(raw["n"], raw["by"])


def _finite_number(value: object) -> bool:
    """Return whether a value is a finite JSON number: an int or a float, not a bool."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def spec_color_kind(spec: ScatterSpec) -> str | None:
    """Return how a spec colors by a numeric column: ``"gradient"``, ``"bins"`` (intervals), or None for another color.

    Parameters
    ----------
    spec : ScatterSpec
        The spec.

    Returns
    -------
    str or None
        The kind, as `parse_color_scale` takes it.
    """
    if spec.gradient:
        return "gradient"
    return "bins" if "color" in spec.binned else None


def parse_color_scale(raw: object, kind: str | None, max_levels: int) -> dict | None:
    """Return the color scale the page keeps under the lock of the axes, checked against the spec it is for.

    Parameters
    ----------
    raw : object
        The ``color`` ``scale`` of the meta of a result
        (`ddviz.server.figure`), or None for the color scale of the filter.
    kind : str or None
        The color it is for (`spec_color_kind`, `ddviz.server.plan.color_kind`): a gradient takes
        ``{"range": [lo, hi]}``, two finite numbers with ``lo <= hi``;
        intervals (``"bins"``) the cuts ``{"breaks": [...], "values": bool}``,
        the breaks finite numbers in ascending order, none or from 2 to
        ``max_levels + 1`` of them. Another color (None) has no color scale
        and leaves it out.
    max_levels : int
        Most intervals of a numeric color column (``plot.max_levels``).

    Returns
    -------
    dict or None
        The color scale with float numbers
        (`ddviz.shared.scatter.ScatterSpec.color_scale`), or None.

    Raises
    ------
    ValueError
        When `raw` is neither a dict nor None, or not of the form above.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict) or kind is None:
        if isinstance(raw, dict):
            return None
        raise ValueError(f"color_scale is a dict or null: {raw!r}")
    if kind == "gradient":
        lo_hi = raw.get("range")
        if (
            set(raw) != {"range"}
            or not isinstance(lo_hi, list)
            or len(lo_hi) != 2
            or not all(_finite_number(v) for v in lo_hi)
            or lo_hi[0] > lo_hi[1]
        ):
            raise ValueError(
                "color_scale of a gradient is a range of two finite numbers "
                f"lo <= hi: {raw!r}"
            )
        return {"range": [float(v) for v in lo_hi]}
    return _parse_breaks(raw, max_levels, "color_scale of intervals")


def _parse_breaks(raw: object, max_levels: int, name: str) -> dict:
    """Return the cuts ``{"breaks": [...], "values": bool}`` of `raw` with float breaks: finite numbers in ascending order, none or from 2 to ``max_levels + 1`` of them; a ValueError naming `name` otherwise."""
    breaks = raw.get("breaks") if isinstance(raw, dict) else None
    top = max_levels + 1
    if (
        not isinstance(raw, dict)
        or set(raw) != {"breaks", "values"}
        or not isinstance(breaks, list)
        or not all(_finite_number(v) for v in breaks)
        or any(a > b for a, b in pairwise(breaks))
        or len(breaks) == 1
        or len(breaks) > top
        or not isinstance(raw["values"], bool)
    ):
        raise ValueError(
            f"{name} is breaks, finite numbers in ascending order, none or "
            f"from 2 to {top} of them, and values a bool: {raw!r}"
        )
    return {"breaks": [float(v) for v in breaks], "values": raw["values"]}


def parse_cuts(raw: object, roles: Iterable[str], max_levels: int) -> dict[str, dict]:
    """Return the cuts of the numeric symbol, row and col columns the page keeps under the lock of the axes, checked against the spec they are for.

    Parameters
    ----------
    raw : object
        The ``cuts`` of the meta of a result (`ddviz.server.figure`): a
        dict of a role to its cuts, as `parse_color_scale` takes those of
        intervals; or None for the cuts of the filter.
    roles : iterable of str
        The roles of the spec's ``binned`` but the color (``"symbol"``,
        ``"row"``, ``"col"``). A role left out of `raw` takes the cuts of
        the filter.
    max_levels : int
        Most intervals of these roles (``ddviz.server.plan.FACET_BINS``).

    Returns
    -------
    dict of str to dict
        The cuts with float breaks, by role
        (`ddviz.shared.scatter.ScatterSpec.kept_cuts`).

    Raises
    ------
    ValueError
        When `raw` is neither a dict nor None, has a role not in `roles`,
        or cuts not of the form of `parse_color_scale`.
    """
    if raw is None:
        return {}
    roles = set(roles)
    unknown = sorted(r for r in raw if r not in roles) if isinstance(raw, dict) else []
    if not isinstance(raw, dict) or unknown:
        raise ValueError(
            f"cuts is a dict of the roles cut into intervals ({sorted(roles)}) "
            f"or null: {raw!r}"
        )
    return {
        role: _parse_breaks(cuts, max_levels, f"cuts of {role}")
        for role, cuts in raw.items()
    }


def parse_range_levels(
    raw: object, columns: Iterable[str], max_axis_levels: int
) -> dict[str, list[str]]:
    """Return the levels of the categorical axes that the page's ranges are positions of, checked against the spec they are for.

    Parameters
    ----------
    raw : object
        The ``range_levels`` of ``POST /api/view``: a dict of a categorical
        axis column to the levels of the result the page shows
        (``meta.axis_levels``), or None for none.
    columns : iterable of str
        The categorical axis columns of the spec
        (`ddviz.shared.scatter.ScatterSpec.categorical` but the one band).
    max_axis_levels : int
        Most levels of a categorical axis column (``plot.max_axis_levels``).

    Returns
    -------
    dict of str to list of str
        The levels by column (`ddviz.shared.scatter.View.range_levels`).

    Raises
    ------
    ValueError
        When `raw` is neither a dict nor None, has a column not in
        `columns`, or levels that are not a list of at most
        `max_axis_levels` strings.
    """
    if raw is None:
        return {}
    columns = set(columns)
    unknown = sorted(c for c in raw if c not in columns) if isinstance(raw, dict) else []
    if not isinstance(raw, dict) or unknown:
        raise ValueError(
            "range_levels is a dict of the categorical axis columns "
            f"({sorted(columns)}) or null: {raw!r}"
        )
    for column, levels in raw.items():
        if (
            not isinstance(levels, list)
            or len(levels) > max_axis_levels
            or not all(isinstance(v, str) for v in levels)
        ):
            raise ValueError(
                f"range_levels of {column} is a list of at most "
                f"{max_axis_levels} strings: {levels!r}"
            )
    return {c: list(v) for c, v in raw.items()}


def parse_keep_axis_levels(raw: object, columns: Iterable[str]) -> list[str]:
    """Return the categorical axis columns whose bands the page asks to be the levels of every row, checked against the graph.

    Parameters
    ----------
    raw : object
        The ``keep_unfiltered_axis_levels`` of ``POST /api/plot``: a list of
        column names.
    columns : iterable of str
        The categorical x and y columns of the graph
        (`ddviz.server.plan.categorical_axes`).

    Returns
    -------
    list of str
        The columns, once each
        (`ddviz.shared.scatter.ScatterSpec.keep_unfiltered_axis_levels`).

    Raises
    ------
    ValueError
        When `raw` is not a list of strings, or names a column not in
        `columns`.
    """
    columns = list(columns)
    if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw):
        raise ValueError(
            f"keep_unfiltered_axis_levels is a list of column names: {raw!r}"
        )
    other = [c for c in raw if c not in columns]
    if other:
        raise ValueError(
            "keep_unfiltered_axis_levels names the categorical x and y columns "
            f"({columns}), not {other}"
        )
    return list(dict.fromkeys(raw))


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
    if p is not None and not (_finite_number(p) and 0 <= p <= 1):
        raise ValueError(f"p is from 0 to 1 or null: {p}")
    if not (_finite_number(frac) and 0 < frac <= 1):
        raise ValueError(f"frac is above 0 and at most 1: {frac}")
    return Smoothing(method, None if p is None else float(p), float(frac))


def parse_ref_stats(raw: object) -> list[RefStat]:
    """Return the statistics of the reference lines the page asks for, checked.

    Parameters
    ----------
    raw : object
        ``{column: {"moments": bool, "quantiles": [p, ...]}}``: whether the
        mean and the standard deviation of the column are found, and the
        percentiles (finite numbers from 0 to 100); either key may be left
        out (no moments, no quantiles).

    Returns
    -------
    list of RefStat
        One per column asking for any, its percentiles ascending without
        repeats.

    Raises
    ------
    ValueError
        When `raw` is not an object of objects of these keys, ``moments``
        is not a bool, or ``quantiles`` not a list of such numbers.
    """
    if not isinstance(raw, dict) or not all(isinstance(c, str) for c in raw):
        raise ValueError(f"ref_stats is an object of columns: {raw!r}")
    asked = []
    for column, stats in raw.items():
        if not isinstance(stats, dict) or not set(stats) <= {"moments", "quantiles"}:
            raise ValueError(
                f"ref_stats of {column!r} is an object of moments and quantiles: {stats!r}"
            )
        moments = stats.get("moments", False)
        quantiles = stats.get("quantiles", [])
        if type(moments) is not bool:
            raise ValueError(f"moments of {column!r} is true or false: {moments!r}")
        if not isinstance(quantiles, list) or not all(
            _finite_number(p) and 0 <= p <= 100 for p in quantiles
        ):
            raise ValueError(
                f"quantiles of {column!r} are numbers from 0 to 100: {quantiles!r}"
            )
        if moments or quantiles:
            asked.append(RefStat(column, moments, sorted({float(p) for p in quantiles})))
    return asked


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
    if not is_int(raw) or raw not in SHAPE_SIZES:
        raise ValueError(f"shape_size is one of {SHAPE_SIZES} or null: {raw}")
    return raw


def parse_line_width(raw: object) -> int | None:
    """Return the width of the lines the page asks for, checked.

    Parameters
    ----------
    raw : object
        One of `LINE_WIDTHS`, or None for the default.

    Returns
    -------
    int or None
        The width in pixels, or None for the default (`scatter_spec`).

    Raises
    ------
    ValueError
        For anything else.
    """
    if raw is None:
        return None
    if not is_int(raw) or raw not in LINE_WIDTHS:
        raise ValueError(f"line_width is one of {LINE_WIDTHS} or null: {raw}")
    return raw


def parse_line_aggregation(raw: object) -> str:
    """Return how the lines the page asks for treat the rows of one x, checked.

    Parameters
    ----------
    raw : object
        One of `ddviz.shared.scatter.LINE_AGGREGATIONS`, or None for
        ``"raw"``.

    Returns
    -------
    str
        The aggregation (`ddviz.shared.scatter.ScatterSpec.line_aggregation`).

    Raises
    ------
    ValueError
        For anything else.
    """
    if raw is None:
        return "raw"
    if not isinstance(raw, str) or raw not in LINE_AGGREGATIONS:
        raise ValueError(
            f"line_aggregation is one of {LINE_AGGREGATIONS} or null: {raw!r}"
        )
    return raw


def parse_shape_sizes(raw: dict[str, object] | None) -> dict[str, int]:
    """Return the sizes the page asks for the shapes of single symbol levels, checked.

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
    """Return the shapes the page asks for single symbol levels, checked.

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
    if not is_int(raw) or raw < 1:
        raise ValueError(f"wrap_cols is a positive int or null: {raw}")
    return raw
