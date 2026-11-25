"""Tests of checking how the page asks to draw a plot (`POST /api/plot`)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from ddviz.server.models import PlotRequest
from ddviz.server.plotoptions import (
    MAX_SAFE_INTEGER,
    PlotOptions,
    parse_color_bins,
    parse_color_scale,
    parse_cuts,
    parse_keep_axis_levels,
    parse_level_shapes,
    parse_line_aggregation,
    parse_line_width,
    parse_plot_options,
    parse_range_levels,
    parse_ref_stats,
    parse_shape_size,
    parse_shape_sizes,
    parse_smoothing,
    parse_wrap_cols,
    spec_color_kind,
)
from ddviz.shared.scatter import Binning, RefStat, ScatterSpec, Smoothing


@pytest.mark.parametrize("by", ["values", "rows"])
@pytest.mark.parametrize("n", [2, 3, 4, 5, 7, 10, 12, 100])
def test_parse_color_bins_takes_integers_from_2_to_the_limit(n: int, by: str) -> None:
    """The page may cut a color column into 2 to ``plot.max_levels`` intervals, by rows or by values."""
    assert parse_color_bins({"n": n, "by": by}, 100) == Binning(n, by)


def test_parse_color_bins_takes_null_for_a_gradient() -> None:
    """Null asks for a gradient."""
    assert parse_color_bins(None, 100) is None


@pytest.mark.parametrize(
    ("raw", "limit"),
    [
        ({"n": 1, "by": "values"}, 100),
        ({"n": 0, "by": "rows"}, 100),
        ({"n": -3, "by": "rows"}, 100),
        ({"n": 101, "by": "values"}, 100),
        ({"n": 13, "by": "rows"}, 12),
        ({"n": 2, "by": "rows"}, 1),
        ({"n": MAX_SAFE_INTEGER + 1, "by": "rows"}, MAX_SAFE_INTEGER + 10),
        ({"n": 7.0, "by": "rows"}, 100),
        ({"n": "7", "by": "rows"}, 100),
        ({"n": True, "by": "rows"}, 100),
        ({"n": None, "by": "rows"}, 100),
        ({"n": 5, "by": "other"}, 100),
        ({"n": 5}, 100),
        ({"n": 5, "by": "rows", "x": 1}, 100),
        ([5, "rows"], 100),
    ],
)
def test_parse_color_bins_refuses_other_types_forms_and_ranges(
    raw: object, limit: int
) -> None:
    """Another number, type or form is refused, naming color_bins and the range taken."""
    top = min(limit, MAX_SAFE_INTEGER)
    with pytest.raises(ValueError, match=f"color_bins .* from 2 to {top}"):
        parse_color_bins(raw, limit)


def test_parse_color_bins_takes_up_to_the_safe_integers() -> None:
    """Past the safe integers of JavaScript nothing is taken, whatever the limit."""
    big = MAX_SAFE_INTEGER + 10
    assert parse_color_bins({"n": MAX_SAFE_INTEGER, "by": "rows"}, big) == Binning(
        MAX_SAFE_INTEGER, "rows"
    )


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


def test_parse_line_aggregation() -> None:
    """The aggregation is raw, mean or median, raw for null."""
    assert parse_line_aggregation(None) == "raw"
    for aggregation in ("raw", "mean", "median"):
        assert parse_line_aggregation(aggregation) == aggregation
    for bad in ("sum", "Mean", "", 1, True, ["mean"]):
        with pytest.raises(ValueError, match="line_aggregation"):
            parse_line_aggregation(bad)


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


def test_parse_ref_stats() -> None:
    """Each column asks for its moments and percentiles, sorted without repeats; a column asking for nothing is dropped."""
    assert parse_ref_stats({}) == []
    raw = {
        "y1": {"moments": True, "quantiles": [95, 5, 95.0]},
        "x": {"quantiles": [0, 100, 0.135]},
        "z": {"moments": False, "quantiles": []},
        "w": {"moments": True},
    }
    assert parse_ref_stats(raw) == [
        RefStat("y1", True, [5.0, 95.0]),
        RefStat("x", False, [0.0, 0.135, 100.0]),
        RefStat("w", True, []),
    ]


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "y",
        {"y": True},
        {"y": {"moments": "true"}},
        {"y": {"moments": 1}},
        {"y": {"quantiles": [101]}},
        {"y": {"quantiles": [-1]}},
        {"y": {"quantiles": [float("nan")]}},
        {"y": {"quantiles": ["50"]}},
        {"y": {"quantiles": [True]}},
        {"y": {"quantiles": 50}},
        {"y": {"moments": True, "n": 3}},
    ],
)
def test_parse_ref_stats_refuses_other_shapes(raw: object) -> None:
    """Not an object of objects, moments not a bool, or quantiles not a list of numbers from 0 to 100 is refused."""
    with pytest.raises(ValueError):
        parse_ref_stats(raw)


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
        (lambda raw: parse_color_bins(raw, 100), {"n": 3.0, "by": "rows"}, "color_bins"),
        (lambda raw: parse_color_bins(raw, 100), {"n": True, "by": "rows"}, "color_bins"),
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
    assert parse_color_bins({"n": 3, "by": "rows"}, 100) == Binning(3, "rows")


def _color_spec(**fields: object) -> ScatterSpec:
    """Return a spec of x × y colored by c, as `fields` set it."""
    return ScatterSpec(
        **{
            "files": {},
            "x": ["x"],
            "y": ["y"],
            "color": "c",
            "row": None,
            "col": None,
            "width": 1,
            "height": 1,
            **fields,
        }
    )


GRADIENT = _color_spec(gradient=True)
CUT = _color_spec(binned={"color": Binning(3, "values")})


def test_parse_color_scale_takes_a_range_for_a_gradient() -> None:
    """A gradient keeps two finite numbers in order, as floats; null is the scale of the filter."""
    assert parse_color_scale({"range": [1, 2.5]}, "gradient", 100) == {
        "range": [1.0, 2.5]
    }
    assert parse_color_scale({"range": [3, 3]}, "gradient", 100) == {"range": [3.0, 3.0]}
    assert parse_color_scale(None, "gradient", 100) is None


def test_parse_color_scale_takes_the_breaks_of_intervals() -> None:
    """Intervals keep their breaks in ascending order, none or 2 to ``max_levels + 1``, and whether they are values."""
    cuts = {"breaks": [0, 1.5, 3], "values": False}
    assert parse_color_scale(cuts, "bins", 100) == {
        "breaks": [0.0, 1.5, 3.0],
        "values": False,
    }
    values = {"breaks": [1, 2, 2], "values": True}
    assert parse_color_scale(values, "bins", 100) == {
        "breaks": [1.0, 2.0, 2.0],
        "values": True,
    }
    empty = {"breaks": [], "values": False}
    assert parse_color_scale(empty, "bins", 100) == empty
    most = {"breaks": list(range(13)), "values": False}
    assert parse_color_scale(most, "bins", 12)["breaks"] == [float(b) for b in range(13)]


def test_parse_color_scale_leaves_out_that_of_another_color() -> None:
    """A categorical color, or none, has no scale to keep: a dict is left out."""
    assert parse_color_scale({"range": [0, 1]}, None, 100) is None
    assert parse_color_scale({"breaks": []}, None, 100) is None


def test_the_kind_of_a_spec_s_color() -> None:
    """A gradient, intervals, and any other color, as the check takes them."""
    assert [spec_color_kind(s) for s in (GRADIENT, CUT, _color_spec())] == [
        "gradient",
        "bins",
        None,
    ]


@pytest.mark.parametrize(
    ("raw", "spec"),
    [
        ([0, 1], GRADIENT),
        ("range", CUT),
        (True, _color_spec()),
        ({"range": [2, 1]}, GRADIENT),
        ({"range": [0]}, GRADIENT),
        ({"range": [0, 1, 2]}, GRADIENT),
        ({"range": [0, float("inf")]}, GRADIENT),
        ({"range": [0, float("nan")]}, GRADIENT),
        ({"range": [0, "1"]}, GRADIENT),
        ({"range": [False, True]}, GRADIENT),
        ({"range": (0, 1)}, GRADIENT),
        ({"range": [0, 1], "values": False}, GRADIENT),
        ({"breaks": [0, 1], "values": False}, GRADIENT),
        ({"range": [0, 1]}, CUT),
        ({"breaks": [0, 2, 1], "values": False}, CUT),
        ({"breaks": [1], "values": False}, CUT),
        ({"breaks": list(range(14)), "values": False}, CUT),
        ({"breaks": [0, float("inf")], "values": False}, CUT),
        ({"breaks": [0, "1"], "values": False}, CUT),
        ({"breaks": [0, 1], "values": 0}, CUT),
        ({"breaks": [0, 1]}, CUT),
        ({"breaks": [0, 1], "values": False, "range": [0, 1]}, CUT),
    ],
)
def test_parse_color_scale_refuses_another_form(raw: object, spec: ScatterSpec) -> None:
    """Another type, order, length or kind than the spec's is refused, naming ``color_scale``."""
    with pytest.raises(ValueError, match="color_scale"):
        parse_color_scale(raw, spec_color_kind(spec), 12)


def test_parse_cuts_takes_those_of_the_roles_cut() -> None:
    """The cuts of the roles cut into intervals are kept by role with float breaks; a role left out, or null, is none kept."""
    cuts = {"breaks": [0, 1.5, 3], "values": False}
    assert parse_cuts({"col": cuts}, ["col", "symbol"], 5) == {
        "col": {"breaks": [0.0, 1.5, 3.0], "values": False}
    }
    assert parse_cuts(None, ["col"], 5) == {}
    assert parse_cuts({}, ["col"], 5) == {}
    most = {"breaks": list(range(6)), "values": False}
    assert parse_cuts({"row": most}, ["row"], 5)["row"]["breaks"] == [
        float(b) for b in range(6)
    ]


@pytest.mark.parametrize(
    "raw",
    [
        [],
        "col",
        {"row": {"breaks": [0, 1], "values": False}},
        {"color": {"breaks": [0, 1], "values": False}},
        {"col": {"breaks": [1, 0], "values": False}},
        {"col": {"breaks": [0], "values": False}},
        {"col": {"breaks": list(range(7)), "values": False}},
        {"col": {"breaks": [0, float("inf")], "values": False}},
        {"col": {"breaks": [0, 1]}},
        {"col": {"breaks": [0, 1], "values": 1}},
        {"col": [0, 1]},
        {"col": None},
    ],
)
def test_parse_cuts_refuses_another_form(raw: object) -> None:
    """Cuts of a role not cut, or not of the form of intervals, are refused naming ``cuts``."""
    with pytest.raises(ValueError, match="cuts"):
        parse_cuts(raw, ["col"], 5)


def test_parse_range_levels_takes_the_levels_of_categorical_axes() -> None:
    """The levels of the categorical axis columns are kept by column, up to the most of an axis; null is none."""
    assert parse_range_levels({"g": ["a", "b"]}, ["g", "h"], 2) == {"g": ["a", "b"]}
    assert parse_range_levels({}, ["g"], 2) == {}
    assert parse_range_levels(None, ["g"], 2) == {}
    assert parse_range_levels({"g": []}, ["g"], 2) == {"g": []}


@pytest.mark.parametrize(
    "raw",
    [
        [],
        "g",
        {"x": ["a"]},
        {"g": "a"},
        {"g": None},
        {"g": ["a", 1]},
        {"g": ["a", "b", "c"]},
    ],
)
def test_parse_range_levels_refuses_another_form(raw: object) -> None:
    """Levels of a column that is no categorical axis, or not a list of at most the most levels of strings, are refused naming ``range_levels``."""
    with pytest.raises(ValueError, match="range_levels"):
        parse_range_levels(raw, ["g"], 2)


def test_parse_keep_axis_levels_takes_categorical_axis_columns() -> None:
    """The categorical axis columns named are kept once each; none is an empty list."""
    assert parse_keep_axis_levels(["g", "h", "g"], ["g", "h"]) == ["g", "h"]
    assert parse_keep_axis_levels([], ["g"]) == []
    assert parse_keep_axis_levels([], []) == []


@pytest.mark.parametrize(
    "raw", [None, "g", {"g": True}, ["g", 1], [None], ["v"], ["unknown"]]
)
def test_parse_keep_axis_levels_refuses_another_form(raw: object) -> None:
    """Not a list of strings, or a column that is not a categorical axis column of the graph (a numeric one, one unknown), is refused naming ``keep_unfiltered_axis_levels``."""
    with pytest.raises(ValueError, match="keep_unfiltered_axis_levels"):
        parse_keep_axis_levels(raw, ["g"])


# The body of a plot request without a setting of the drawing.
BARE = {"encoding": {}, "width": 400, "height": 300}


def test_parse_plot_options_of_a_bare_request_is_the_default() -> None:
    """A request with the graph and the size only takes every default."""
    assert parse_plot_options(PlotRequest(**BARE), 100) == PlotOptions()


def test_parse_plot_options_takes_each_setting() -> None:
    """Each setting of the request reaches its attribute, checked by its ``parse_*``."""
    request = PlotRequest(
        **BARE,
        color_bins={"n": 3, "by": "values"},
        wrap_cols=2,
        smooth={"method": "lowess", "frac": 0.5},
        shape_size=7,
        line_width=3,
        line_aggregation="mean",
        shape_sizes={"p": 11},
        level_shapes={"p": "square"},
        ref_stats={"y": {"moments": True, "quantiles": [90, 10]}},
        show_null_rows={"color": False, "wrap": False},
        keep_unfiltered_color_levels=True,
        keep_unfiltered_symbol_levels=True,
    )
    assert parse_plot_options(request, 100) == PlotOptions(
        color_bins=Binning(3, "values"),
        wrap_cols=2,
        smoothing=Smoothing("lowess", None, 0.5),
        shape_size=7,
        line_width=3,
        line_aggregation="mean",
        shape_sizes={"p": 11},
        level_shapes={"p": "square"},
        ref_stats=[RefStat("y", moments=True, quantiles=[10.0, 90.0])],
        show_null_rows={
            "color": False,
            "symbol": True,
            "row": True,
            "col": True,
            "wrap": False,
        },
        keep_unfiltered_color_levels=True,
        keep_unfiltered_symbol_levels=True,
    )


@pytest.mark.parametrize(
    ("field", "raw", "parse"),
    [
        ("color_bins", {"n": 1, "by": "rows"}, lambda r: parse_color_bins(r, 100)),
        ("wrap_cols", 0, parse_wrap_cols),
        ("smooth", {"method": "spline"}, parse_smoothing),
        ("shape_size", 4, parse_shape_size),
        ("line_width", 9, parse_line_width),
        ("line_aggregation", "sum", parse_line_aggregation),
        ("shape_sizes", {"p": 4}, parse_shape_sizes),
        ("level_shapes", {"p": "star"}, parse_level_shapes),
        ("ref_stats", ["y"], parse_ref_stats),
    ],
)
def test_parse_plot_options_refuses_as_each_parse_does(
    field: str, raw: object, parse: Callable[[object], object]
) -> None:
    """A wrong setting is refused with the very error of its ``parse_*``."""
    with pytest.raises(ValueError) as expected:
        parse(raw)
    with pytest.raises(ValueError) as error:
        parse_plot_options(PlotRequest(**BARE, **{field: raw}), 100)
    assert str(error.value) == str(expected.value)


def test_parse_plot_options_leaves_the_settings_checked_against_the_columns() -> None:
    """The axes that keep their levels, the color scale and the cuts are left at their defaults for ``POST /api/plot`` to check against the graph."""
    request = PlotRequest(
        **BARE,
        keep_unfiltered_axis_levels=["g"],
        color_scale={"range": [0, 1]},
        cuts={"row": {"breaks": [0, 1], "values": False}},
    )
    options = parse_plot_options(request, 100)
    assert options.keep_unfiltered_axis_levels == []
    assert options.color_scale is None
    assert options.cuts == {}
