"""Tests of turning a graph into the scatter plot a worker aggregates."""

from __future__ import annotations

import pytest

from ddviz.server.encoding import Encoding
from ddviz.server.plan import (
    FACET_BINS,
    drawn_columns,
    has_box_pair,
    parse_filters,
    parse_shape_size,
    parse_smoothing,
    parse_wrap_cols,
    scatter_spec,
    undrawn,
)
from ddviz.shared.scatter import SHAPE_SIZE, Binning, Filter, Smoothing


def test_scatter_draws_every_axis_and_overlay_as_shapes() -> None:
    """The n-th axes are drawn, read and hovered; overlay beside color draws shapes."""
    encoding = Encoding(
        x=("a", "a2"), y=("b", "b2", "b3"), color="g", overlay="o", col="h"
    )
    files = {c: [f"{c}.parquet"] for c in encoding.columns()}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"], shape_size=9)
    assert (spec.x, spec.y, spec.color, spec.overlay, spec.row, spec.col) == (
        ["a", "a2"],
        ["b", "b2", "b3"],
        "g",
        "o",
        None,
        "h",
    )
    assert spec.shape_size == 9
    assert spec.hover == ["a", "a2", "b", "b2", "b3", "g", "o", "h"]
    assert spec.hover == drawn_columns(encoding)
    assert sorted(spec.files) == sorted(spec.hover)
    assert spec.view is None
    assert undrawn(encoding, {}) == []


def test_overlay_alone_colors_the_series() -> None:
    """Without a color column, overlay takes its place, without shapes; a numeric one is a gradient."""
    encoding = Encoding(x=("a",), y=("b",), overlay="o")
    files = {c: [f"{c}.parquet"] for c in encoding.columns()}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"])
    assert (spec.color, spec.overlay, spec.gradient) == ("o", None, False)
    numeric = {"a": True, "b": True, "o": True}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"], numeric=numeric)
    assert (spec.color, spec.overlay, spec.gradient) == ("o", None, True)


def test_a_numeric_overlay_beside_color_is_cut_into_intervals() -> None:
    """A numeric overlay column takes shapes by intervals of about the same rows, as a facet."""
    encoding = Encoding(x=("a",), y=("b",), color="g", overlay="o")
    files = {c: [f"{c}.parquet"] for c in encoding.columns()}
    numeric = {"a": True, "b": True, "g": False, "o": True}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"], numeric=numeric)
    assert spec.overlay == "o"
    assert spec.binned == {
        "overlay": Binning(FACET_BINS, "rows", values_up_to=FACET_BINS)
    }


def test_parse_shape_size() -> None:
    """The size is one of `SHAPE_SIZES`, the default for null."""
    assert parse_shape_size(None) == SHAPE_SIZE
    assert parse_shape_size(11) == 11
    for bad in (4, 0, True, "7", 7.5):
        with pytest.raises(ValueError, match="shape_size"):
            parse_shape_size(bad)


def test_a_column_on_several_roles_is_read_once() -> None:
    """Coloring by the facet column reads it once."""
    encoding = Encoding(x=("a",), y=("b",), color="g", col="g")
    assert drawn_columns(encoding) == ["a", "b", "g"]


def test_scatter_needs_x_and_y() -> None:
    """A graph without a y column has no scatter plot."""
    with pytest.raises(ValueError, match="x and y"):
        scatter_spec(Encoding(x=("a",)), {"a": "a.parquet"}, 400, 300, [])


NUMERIC = {"a": True, "b": True, "g": False}


def test_filters_are_read_but_not_hovered() -> None:
    """A filter column is read with the plot's columns, and not hovered."""
    encoding = Encoding(x=("a",), y=("b",))
    files = {c: [f"{c}.parquet"] for c in ("a", "b", "g")}
    filters = [Filter("g", levels=["p"])]
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"], filters)
    assert spec.hover == ["a", "b"]
    assert list(spec.files) == ["a", "b", "g"]
    assert spec.filters == filters


def test_parse_filters_takes_a_range_or_levels_by_column_type() -> None:
    """A numeric column takes a range, a categorical one levels or a text to contain."""
    raw = [{"column": "a", "range": [-1, 2.5]}, {"column": "g", "levels": ["p", "q"]}]
    assert parse_filters(raw, NUMERIC) == [
        Filter("a", range=[-1.0, 2.5]),
        Filter("g", levels=["p", "q"]),
    ]
    raw = [{"column": "g", "contains": "p."}]
    assert parse_filters(raw, NUMERIC) == [Filter("g", contains="p.")]


@pytest.mark.parametrize(
    "raw",
    [
        [{"column": "z", "range": [0, 1]}],
        [{"column": "a", "levels": ["p"]}],
        [{"column": "a", "range": [2, 1]}],
        [{"column": "a", "range": [0, float("inf")]}],
        [{"column": "g", "range": [0, 1]}],
        [{"column": "g", "levels": []}],
        [{"column": "g", "levels": ["p"], "other": 1}],
        [{"column": "a", "contains": "1"}],
        [{"column": "g", "contains": ""}],
        [{"column": "g", "contains": 1}],
        [{"column": "g", "contains": "p", "levels": ["p"]}],
        [{"column": "g", "levels": ["p"]}, {"column": "g", "levels": ["q"]}],
    ],
)
def test_parse_filters_refuses_what_does_not_fit(raw: list) -> None:
    """Unknown columns, mismatched conditions and repeated columns are refused."""
    with pytest.raises(ValueError):
        parse_filters(raw, NUMERIC)


def test_wrap_takes_the_col_role_of_the_scatter() -> None:
    """A wrap column is drawn as col, wrapped; a numeric one is cut like Group X."""
    encoding = Encoding(x=("a",), y=("b",), wrap="w")
    files = {c: [f"{c}.parquet"] for c in encoding.columns()}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"], wrap_cols=3)
    assert (spec.row, spec.col, spec.wrap, spec.wrap_cols) == (None, "w", True, 3)
    assert spec.hover == ["a", "b", "w"]
    assert spec.binned == {}
    numeric = {"a": True, "b": True, "w": True}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"], numeric=numeric)
    assert spec.binned == {"col": Binning(FACET_BINS, "rows", values_up_to=FACET_BINS)}
    assert spec.wrap_cols is None
    # The number to a row is kept only for a wrapped grid.
    plain = Encoding(x=("a",), y=("b",), col="w")
    spec = scatter_spec(plain, files, 400, 300, ["#000000"], wrap_cols=3)
    assert (spec.col, spec.wrap, spec.wrap_cols) == ("w", False, None)


@pytest.mark.parametrize(
    ("encoding", "match"),
    [
        (Encoding(x=("a",), y=("b",), wrap="w", row="r"), "row or col"),
        (Encoding(x=("a",), y=("b",), wrap="w", col="r"), "row or col"),
        (Encoding(x=("a", "c"), y=("b",), wrap="w"), "n-th axes"),
        (Encoding(x=("a",), y=("b", "c"), wrap="w"), "n-th axes"),
    ],
)
def test_wrap_is_refused_beside_facets_and_nth_axes(
    encoding: Encoding, match: str
) -> None:
    """Wrap replaces Group X and Group Y and takes no n-th axes."""
    files = {c: [f"{c}.parquet"] for c in encoding.columns()}
    with pytest.raises(ValueError, match=match):
        scatter_spec(encoding, files, 400, 300, ["#000000"])


def test_parse_wrap_cols() -> None:
    """The number to a row is a positive int, or None for square panels."""
    assert parse_wrap_cols(None) is None
    assert parse_wrap_cols(4) == 4
    for raw in (0, -1, 1.5, "2", True):
        with pytest.raises(ValueError, match="wrap_cols"):
            parse_wrap_cols(raw)


def test_categorical_axis_columns_are_drawn_in_bands() -> None:
    """A text column on x or y is categorical; a column missing from numeric stays numeric."""
    encoding = Encoding(x=("g", "a"), y=("b",), color="h")
    files = {c: [f"{c}.parquet"] for c in encoding.columns()}
    numeric = {"g": False, "a": True, "h": False}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"], numeric=numeric)
    assert spec.categorical == ["g"]
    assert scatter_spec(encoding, files, 400, 300, ["#000000"]).categorical == []


def test_smoothing_lines_need_a_numeric_x_and_a_numeric_y() -> None:
    """Smoothing lines are drawn with a numeric x and a numeric y; otherwise they are undrawn and the points stay."""
    files = {c: [f"{c}.parquet"] for c in ("g", "a", "b")}
    numeric = {"g": False, "a": True, "b": True}
    smooth = Encoding(x=("a",), y=("b",), elements=("smooth",))
    assert undrawn(smooth, numeric) == []
    spec = scatter_spec(smooth, files, 400, 300, ["#000000"], numeric=numeric)
    assert spec.smooth == Smoothing()
    assert spec.smooth_pairs() == {("a", "b")}
    assert not spec.draws_points("a", "b")
    lowess = Smoothing("lowess", frac=0.3)
    spec = scatter_spec(
        smooth, files, 400, 300, ["#000000"], numeric=numeric, smoothing=lowess
    )
    assert spec.smooth == lowess
    banded = Encoding(x=("g",), y=("b",), elements=("smooth",))
    assert undrawn(banded, numeric) == ["smooth"]
    spec = scatter_spec(banded, files, 400, 300, ["#000000"], numeric=numeric)
    assert spec.smooth is None
    assert spec.draws_points("g", "b")
    both = Encoding(x=("g", "a"), y=("b",), elements=("smooth",))
    spec = scatter_spec(both, files, 400, 300, ["#000000"], numeric=numeric)
    assert spec.smooth_pairs() == {("a", "b")}
    assert spec.draws_points("g", "b")


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


def test_box_plots_need_a_categorical_x_and_a_numeric_y() -> None:
    """Box plots are drawn with a categorical x and a numeric y; otherwise they are undrawn and the points stay."""
    files = {c: [f"{c}.parquet"] for c in ("g", "a", "b")}
    numeric = {"g": False, "a": True, "b": True}
    boxed = Encoding(x=("g",), y=("b",), elements=("box",))
    assert has_box_pair(boxed, numeric)
    assert undrawn(boxed, numeric) == []
    spec = scatter_spec(boxed, files, 400, 300, ["#000000"], numeric=numeric)
    assert (spec.points, spec.box) == (False, True)
    assert spec.box_pairs() == {("g", "b")}
    assert not spec.draws_points("g", "b")

    numeric_x = Encoding(x=("a",), y=("b",), elements=("box",))
    assert not has_box_pair(numeric_x, numeric)
    assert undrawn(numeric_x, numeric) == ["box"]
    spec = scatter_spec(numeric_x, files, 400, 300, ["#000000"], numeric=numeric)
    assert (spec.points, spec.box) == (False, False)
    assert spec.draws_points("a", "b")

    # With n-th axes, only the pairs of a categorical x and a numeric y have boxes.
    mixed = Encoding(x=("g", "a"), y=("b",), elements=("box",))
    spec = scatter_spec(mixed, files, 400, 300, ["#000000"], numeric=numeric)
    assert spec.box_pairs() == {("g", "b")}
    assert spec.draws_points("a", "b")
