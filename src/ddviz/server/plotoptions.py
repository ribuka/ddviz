"""How the page asks to draw a plot (`POST /api/plot`), checked."""

from __future__ import annotations

import math

from ddviz.shared.scatter import Binning, Smoothing
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
