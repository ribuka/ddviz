"""Tests of the scales of the axis columns and the positions on them."""

from __future__ import annotations

import math

import pytest

from ddviz.shared.axisscale import (
    axis_positions,
    padded_log_range,
    parse_axis_scales,
    positions,
    values,
)

NUMERIC = {"n": True, "d": True, "t": True, "c": False}
TEMPORAL = {"d": "duration", "t": "datetime"}


def test_numbers_and_durations_may_be_log() -> None:
    """A number and a duration take log; the columns left out are linear; X and Y are apart."""
    found = parse_axis_scales(
        {"x": {"n": "log", "d": "linear"}, "y": {"d": "log"}},
        ["n", "d"],
        ["d", "c"],
        NUMERIC,
        TEMPORAL,
    )
    assert found == (["n"], ["d"])
    assert parse_axis_scales(None, ["n"], ["c"], NUMERIC, TEMPORAL) == ([], [])


@pytest.mark.parametrize(
    "raw",
    [{"x": {"t": "log"}}, {"x": {"c": "log"}}, {"x": {"n": "symlog"}}, {"y": {"n": "log"}}],
)
def test_dates_categories_and_unplaced_columns_are_refused(raw: dict) -> None:
    """A datetime, a categorical column, another scale or a column not on its role is a ValueError."""
    with pytest.raises(ValueError, match="axis_scales"):
        parse_axis_scales(raw, ["n", "t", "c"], ["c"], NUMERIC, TEMPORAL)


def test_positions_and_values_are_inverse() -> None:
    """A log axis holds exponents; a linear one the values; a value not positive has none."""
    assert positions((0.1, 1000.0), True) == pytest.approx((-1.0, 3.0))
    assert values((-1.0, 3.0), True) == pytest.approx((0.1, 1000.0))
    assert positions((-1.0, 2.0), False) == (-1.0, 2.0)
    with pytest.raises(ValueError, match="positive"):
        positions((0.0, 1.0), True)
    with pytest.raises(ValueError, match="one range"):
        axis_positions([[1, 2]], ["a", "b"], [])


@pytest.mark.parametrize(
    ("lo", "hi"),
    [(5.0, 5.0), (1e-300, 1e300), (5e-324, 5e-324), (1.7e308, 1.7e308), (5e-324, 1.7e308)],
)
def test_padded_log_ranges_stay_within_finite_powers(lo: float, hi: float) -> None:
    """The padded exponents hold the values, have a span, and their powers of 10 are positive and finite."""
    a, b = padded_log_range(lo, hi)
    assert a < b
    assert a <= math.log10(lo) and math.log10(hi) <= b
    assert 0 < 10.0**a and 10.0**b < math.inf
