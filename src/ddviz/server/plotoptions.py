"""How the page asks to draw a plot (`POST /api/plot`), checked."""

from __future__ import annotations

import math
from itertools import pairwise

from ddviz.shared.scatter import LINE_AGGREGATIONS, Binning, ScatterSpec, Smoothing
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


def parse_color_scale(raw: object, spec: ScatterSpec, max_levels: int) -> dict | None:
    """Return the color scale the page keeps under the lock of the axes, checked against the spec it is for.

    Parameters
    ----------
    raw : object
        The ``color`` ``scale`` of the meta of a result
        (`ddviz.server.figure`), or None for the color scale of the filter.
    spec : ScatterSpec
        The spec it is for: a gradient takes ``{"range": [lo, hi]}``, two
        finite numbers with ``lo <= hi``; a color cut into intervals the
        cuts ``{"breaks": [...], "values": bool}``, the breaks finite
        numbers in ascending order, none or from 2 to ``max_levels + 1`` of
        them. Any other spec has no color scale and leaves it out.
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
    if not isinstance(raw, dict) or not (spec.gradient or "color" in spec.binned):
        if isinstance(raw, dict):
            return None
        raise ValueError(f"color_scale is a dict or null: {raw!r}")
    if spec.gradient:
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
    breaks = raw.get("breaks")
    top = max_levels + 1
    if (
        set(raw) != {"breaks", "values"}
        or not isinstance(breaks, list)
        or not all(_finite_number(v) for v in breaks)
        or any(a > b for a, b in pairwise(breaks))
        or len(breaks) == 1
        or len(breaks) > top
        or not isinstance(raw["values"], bool)
    ):
        raise ValueError(
            "color_scale of intervals is breaks, finite numbers in ascending "
            f"order, none or from 2 to {top} of them, and values a bool: {raw!r}"
        )
    return {"breaks": [float(v) for v in breaks], "values": raw["values"]}


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
