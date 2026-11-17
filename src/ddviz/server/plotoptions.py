"""How the page asks to draw a plot (`POST /api/plot`), checked."""

from __future__ import annotations

import math
from collections.abc import Iterable
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


def parse_axis_levels(
    raw: object, columns: Iterable[str], max_axis_levels: int
) -> dict[str, list[str]]:
    """Return the levels of the categorical axis columns the page keeps under the lock of the axes, checked against the spec they are for.

    Parameters
    ----------
    raw : object
        The ``axis_levels`` of the meta of a result (`ddviz.server.figure`):
        a dict of a categorical x or y column to its levels, a list of
        distinct texts; or None for the levels of the filter.
    columns : iterable of str
        The categorical x and y columns of the spec
        (`ddviz.server.plan.axis_level_columns`). A column left out of
        `raw` takes the levels of the filter.
    max_axis_levels : int
        Most levels of a categorical axis column (``plot.max_axis_levels``).

    Returns
    -------
    dict of str to list of str
        The levels by column (`ddviz.shared.scatter.ScatterSpec.kept_axis_levels`).

    Raises
    ------
    ValueError
        When `raw` is neither a dict nor None, has a column not in
        `columns`, or levels that are not a list of at most
        `max_axis_levels` distinct texts.
    """
    if raw is None:
        return {}
    columns = set(columns)
    unknown = sorted(c for c in raw if c not in columns) if isinstance(raw, dict) else []
    if not isinstance(raw, dict) or unknown:
        raise ValueError(
            "axis_levels is a dict of the categorical axis columns "
            f"({sorted(columns)}) or null: {raw!r}"
        )
    out = {}
    for column, levels in raw.items():
        if (
            not isinstance(levels, list)
            or len(levels) > max_axis_levels
            or not all(isinstance(v, str) for v in levels)
            or len(set(levels)) != len(levels)
        ):
            raise ValueError(
                f"axis_levels of {column} is a list of at most {max_axis_levels:,} "
                "distinct texts"
            )
        # No level kept is the levels of the filter.
        if levels:
            out[column] = list(levels)
    return out


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
