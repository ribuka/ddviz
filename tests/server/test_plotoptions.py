"""Tests of checking how the page asks to draw a plot (`POST /api/plot`)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from ddviz.server.plotoptions import (
    parse_color_bins,
    parse_level_shapes,
    parse_line_width,
    parse_shape_size,
    parse_shape_sizes,
    parse_smoothing,
    parse_wrap_cols,
)
from ddviz.shared.scatter import Binning, Smoothing


def test_parse_color_bins_takes_known_counts_only() -> None:
    """The page may cut a color column into 2, 3, 5 or 10 intervals, by rows or by values."""
    assert parse_color_bins({"n": 5, "by": "rows"}) == Binning(5, "rows")
    assert parse_color_bins(None) is None
    for raw in ({"n": 4, "by": "rows"}, {"n": 5, "by": "other"}, {"n": 5}):
        with pytest.raises(ValueError, match="color bins"):
            parse_color_bins(raw)


def test_parse_shape_size() -> None:
    """The size is one of `SHAPE_SIZES`, or null for the default."""
    assert parse_shape_size(None) is None
    assert parse_shape_size(11) == 11
    for bad in (4, 0, True, "7", 7.5):
        with pytest.raises(ValueError, match="shape_size"):
            parse_shape_size(bad)


def test_parse_line_width() -> None:
    """The width is an integer from 1 to 5, or null for the default."""
    assert parse_line_width(None) is None
    assert parse_line_width(1) == 1
    assert parse_line_width(5) == 5
    for bad in (0, 6, True, "2", 2.0, 2.5):
        with pytest.raises(ValueError, match="line_width"):
            parse_line_width(bad)


def test_parse_wrap_cols() -> None:
    """The number to a row is a positive int, or None for square panels."""
    assert parse_wrap_cols(None) is None
    assert parse_wrap_cols(4) == 4
    for raw in (0, -1, 1.5, "2", True):
        with pytest.raises(ValueError, match="wrap_cols"):
            parse_wrap_cols(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ({"method": "gcv"}, Smoothing("gcv")),
        ({"method": "csaps", "p": 0.9}, Smoothing("csaps", p=0.9)),
        ({"method": "csaps", "p": None}, Smoothing("csaps")),
        ({"method": "lowess", "frac": 0.25}, Smoothing("lowess", frac=0.25)),
    ],
)
def test_parse_smoothing(raw: dict | None, expected: Smoothing | None) -> None:
    """The page's smoothing is a method with its own parameter."""
    assert parse_smoothing(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        {"method": "spline"},
        {"p": 0.5},
        {"method": "gcv", "p": 0.5},
        {"method": "csaps", "p": 1.5},
        {"method": "csaps", "p": True},
        {"method": "lowess", "frac": 0},
        {"method": "lowess", "frac": 1.2},
        [],
    ],
)
def test_parse_smoothing_refuses_bad_values(raw: object) -> None:
    """An unknown method, a parameter of another method, or one out of range is refused."""
    with pytest.raises(ValueError):
        parse_smoothing(raw)


def test_parse_shape_sizes() -> None:
    """Each symbol level named takes one of `SHAPE_SIZES`; null is none."""
    assert parse_shape_sizes(None) == {}
    assert parse_shape_sizes({"p": 3, "q": 15}) == {"p": 3, "q": 15}
    assert parse_shape_sizes({"__proto__": 9}) == {"__proto__": 9}
    for bad in ({"p": 4}, {"p": None}, {"p": "7"}):
        with pytest.raises(ValueError, match="shape_size"):
            parse_shape_sizes(bad)


def test_parse_level_shapes() -> None:
    """Each symbol level named takes one of `SHAPES`; two levels may take the same."""
    assert parse_level_shapes(None) == {}
    assert parse_level_shapes({"p": "x", "q": "x"}) == {"p": "x", "q": "x"}
    assert parse_level_shapes({"__proto__": "circle"}) == {"__proto__": "circle"}
    for bad in ({"p": "star"}, {"p": None}, {"p": 3}):
        with pytest.raises(ValueError, match="level_shapes"):
            parse_level_shapes(bad)


@pytest.mark.parametrize(
    ("parse", "raw", "match"),
    [
        (parse_shape_size, 7.0, "shape_size"),
        (parse_wrap_cols, 2.0, "wrap_cols"),
        (parse_line_width, 2.0, "line_width"),
        (parse_shape_sizes, {"p": 7.0}, "shape_size"),
        (parse_color_bins, {"n": 3.0, "by": "rows"}, "color bins are n in"),
        (parse_color_bins, {"n": True, "by": "rows"}, "color bins are n in"),
    ],
)
def test_integers_are_json_integers_only(
    parse: Callable[[object], object], raw: object, match: str
) -> None:
    """An integer setting refuses a float of the same value and a bool."""
    with pytest.raises(ValueError, match=match):
        parse(raw)


def test_json_integers_are_taken_as_before() -> None:
    """An int of the allowed values is returned as it is."""
    assert parse_shape_size(7) == 7
    assert parse_wrap_cols(2) == 2
    assert parse_color_bins({"n": 3, "by": "rows"}) == Binning(3, "rows")
