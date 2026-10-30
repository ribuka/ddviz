"""Tests of turning a graph into the scatter plot a worker aggregates."""

from __future__ import annotations

import pytest

from ddviz.server.encoding import Encoding
from ddviz.server.plan import (
    FACET_BINS,
    drawn_columns,
    parse_filters,
    parse_wrap_cols,
    scatter_spec,
    undrawn,
)
from ddviz.shared.scatter import Binning, Filter


def test_scatter_draws_every_axis_and_leaves_out_overlay() -> None:
    """The n-th axes are drawn, read and hovered; overlay is not."""
    encoding = Encoding(
        x=("a", "a2"), y=("b", "b2", "b3"), color="g", overlay="o", col="h"
    )
    files = {c: [f"{c}.parquet"] for c in encoding.columns()}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"])
    assert (spec.x, spec.y, spec.color, spec.row, spec.col) == (
        ["a", "a2"],
        ["b", "b2", "b3"],
        "g",
        None,
        "h",
    )
    assert spec.hover == ["a", "a2", "b", "b2", "b3", "g", "h"]
    assert spec.hover == drawn_columns(encoding)
    assert sorted(spec.files) == spec.hover
    assert spec.view is None
    assert undrawn(encoding) == ["overlay"]


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
    """A numeric column takes a range, a categorical one levels."""
    raw = [{"column": "a", "range": [-1, 2.5]}, {"column": "g", "levels": ["p", "q"]}]
    assert parse_filters(raw, NUMERIC) == [
        Filter("a", range=[-1.0, 2.5]),
        Filter("g", levels=["p", "q"]),
    ]


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
