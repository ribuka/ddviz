"""Linear and log10 scales of the axis columns: parsing, and positions on an axis.

A column on a log axis lies at ``log10(value)`` on it: its rows with a value
that is not positive and finite are not drawn there. Ranges and bins of
such an axis hold these positions (`ddviz.shared.scatter.ScatterSpec.log_x`);
the requests of the page and the saved bins hold the values themselves,
in ascending order.
"""

from __future__ import annotations

import math

from ddviz.shared.temporal import DATE_KINDS

LINEAR = "linear"
LOG = "log"
SCALES = (LINEAR, LOG)

# Exponents whose powers of 10 are positive finite doubles (the smallest
# subnormal is about 4.9e-324, the largest double about 1.8e308).
MIN_EXPONENT = -323.0
MAX_EXPONENT = 308.0

# Margin of a log axis around its data, as a share of its span of exponents.
RANGE_PADDING = 0.02
# Half the span of exponents around a single positive value.
SINGLE_VALUE_PAD = 0.5


class NoPositiveValuesError(ValueError):
    """A log axis column has no positive finite value under the local filter."""


def no_positive_message(columns: list[tuple[str, str]]) -> str:
    """Return the error of log axes without a positive value.

    Parameters
    ----------
    columns : list of tuple of str
        The role (``"x"`` or ``"y"``) and the name of each such column.

    Returns
    -------
    str
        The message shown in the footer.
    """
    names = "、".join(f"{role.upper()} の {name}" for role, name in columns)
    return f"{names} に正の値がないため、対数表示に切り替えられません"


def loggable(column: str, numeric: dict[str, bool], temporal: dict[str, str]) -> bool:
    """Return whether an axis column may lie on a log axis: a number or a duration.

    Parameters
    ----------
    column : str
        The column.
    numeric : dict of str to bool
        Whether each column is numeric (temporal columns are).
    temporal : dict of str to str
        The kind of each temporal column.

    Returns
    -------
    bool
        False for a categorical, datetime, date or time column.
    """
    return bool(numeric.get(column)) and temporal.get(column) not in DATE_KINDS


def parse_axis_scales(
    raw: object,
    x: list[str],
    y: list[str],
    numeric: dict[str, bool],
    temporal: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Return the x and y columns on log axes from ``axis_scales`` of a request.

    Parameters
    ----------
    raw : object
        ``{"x": {column: scale}, "y": {column: scale}}``, each scale one of
        `SCALES`; a column left out is linear. None for all linear.
    x, y : list of str
        The columns placed on x and on y.
    numeric : dict of str to bool
        Whether each column is numeric.
    temporal : dict of str to str
        The kind of each temporal column.

    Returns
    -------
    tuple of list of str
        The x and the y columns on log axes, in the order placed.

    Raises
    ------
    ValueError
        When the shape or a scale is wrong, a column is not placed on its
        role, or a log column is not `loggable`.
    """
    if raw is None:
        return [], []
    if not isinstance(raw, dict) or not set(raw) <= {"x", "y"}:
        raise ValueError('axis_scales takes {"x": {...}, "y": {...}}')
    logs = {}
    for role, placed in (("x", x), ("y", y)):
        scales = raw.get(role, {})
        if not isinstance(scales, dict):
            raise ValueError(f"axis_scales.{role} takes {{column: scale}}")  # noqa: TRY004 - a 400 of the request
        for column, scale in scales.items():
            if scale not in SCALES:
                raise ValueError(f"axis_scales.{role}.{column} is linear or log")
            if column not in placed:
                raise ValueError(f"axis_scales.{role}: {column} is not on {role}")
            if scale == LOG and not loggable(column, numeric, temporal):
                raise ValueError(
                    f"axis_scales.{role}: {column} is neither a number nor a duration"
                )
        logs[role] = [c for c in placed if scales.get(c) == LOG]
    return logs["x"], logs["y"]


def to_position(value: float, log: bool) -> float:
    """Return a value's position on an axis: its log10 on a log axis (NaN unless positive).

    Parameters
    ----------
    value : float
        The value.
    log : bool
        Whether the axis is a log axis.

    Returns
    -------
    float
        The position.
    """
    if not log:
        return value
    return math.log10(value) if value > 0 and math.isfinite(value) else math.nan


def from_position(position: float, log: bool) -> float:
    """Return the value at a position on an axis: the inverse of `to_position`.

    Parameters
    ----------
    position : float
        The position, within `MIN_EXPONENT` and `MAX_EXPONENT` on a log axis.
    log : bool
        Whether the axis is a log axis.

    Returns
    -------
    float
        The value.
    """
    return 10.0**position if log else position


def positions(bounds: tuple[float, float], log: bool) -> tuple[float, float]:
    """Return the positions of ascending values on an axis (`to_position`).

    Parameters
    ----------
    bounds : tuple of float
        The values ``(lo, hi)``.
    log : bool
        Whether the axis is a log axis.

    Returns
    -------
    tuple of float
        The positions, ascending.

    Raises
    ------
    ValueError
        When a bound of a log axis is not positive and finite.
    """
    lo, hi = (to_position(v, log) for v in bounds)
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError("the range of a log axis needs positive finite values")
    return lo, hi


def values(bounds: tuple[float, float], log: bool) -> tuple[float, float]:
    """Return the values at ascending positions on an axis (`from_position`).

    Parameters
    ----------
    bounds : tuple of float
        The positions ``(lo, hi)``.
    log : bool
        Whether the axis is a log axis.

    Returns
    -------
    tuple of float
        The values, ascending.
    """
    lo, hi = bounds
    return from_position(lo, log), from_position(hi, log)


def padded_log_range(lo: float, hi: float) -> tuple[float, float]:
    """Return the padded exponents of a log axis over positive values ``lo <= hi``.

    The margin stays within `MIN_EXPONENT` and `MAX_EXPONENT`, so that its
    powers of 10 stay positive and finite; a single value gets a span of
    its own.

    Parameters
    ----------
    lo, hi : float
        The smallest and largest positive finite values.

    Returns
    -------
    tuple of float
        The exponents ``(lo, hi)``, ``lo < hi``.
    """
    a, b = math.log10(lo), math.log10(hi)
    pad = (b - a) * RANGE_PADDING if b > a else SINGLE_VALUE_PAD
    return max(a - pad, min(a, MIN_EXPONENT)), min(b + pad, max(b, MAX_EXPONENT))


def axis_positions(
    ranges: list, columns: list[str], logs: list[str]
) -> list[tuple[float, float]]:
    """Return the positions of the ranges of a request, one per axis column (`positions`).

    Parameters
    ----------
    ranges : list
        The ascending values ``(lo, hi)`` of each column's range.
    columns : list of str
        The columns of the role.
    logs : list of str
        Those on log axes.

    Returns
    -------
    list of tuple of float
        The ranges as positions.

    Raises
    ------
    ValueError
        Unless there is one range per column, each of positive finite
        values on a log axis.
    """
    if len(ranges) != len(columns):
        raise ValueError("one range per x and y column")
    return [
        positions((float(lo), float(hi)), c in logs)
        for c, (lo, hi) in zip(columns, ranges, strict=True)
    ]
