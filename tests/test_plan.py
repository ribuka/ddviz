"""Tests of turning a graph into the scatter plot a worker aggregates."""

from __future__ import annotations

import pytest

from ddviz.encoding import Encoding
from ddviz.plan import drawn_columns, scatter_spec, undrawn


def test_scatter_draws_the_first_axes_and_leaves_out_the_rest() -> None:
    """The n-th axes and overlay are not drawn, read or hovered."""
    encoding = Encoding(
        x=("a", "a2"), y=("b", "b2", "b3"), color="g", overlay="o", col="h"
    )
    files = {c: f"{c}.parquet" for c in encoding.columns()}
    spec = scatter_spec(encoding, files, 400, 300, ["#000000"])
    assert (spec.x, spec.y, spec.color, spec.row, spec.col) == (
        "a",
        "b",
        "g",
        None,
        "h",
    )
    assert spec.hover == ["a", "b", "g", "h"] == drawn_columns(encoding)
    assert sorted(spec.files) == ["a", "b", "g", "h"]
    assert spec.view is None
    assert undrawn(encoding) == ["x2", "y2", "y3", "overlay"]


def test_a_column_on_several_roles_is_read_once() -> None:
    """Coloring by the facet column reads it once."""
    encoding = Encoding(x=("a",), y=("b",), color="g", col="g")
    assert drawn_columns(encoding) == ["a", "b", "g"]


def test_scatter_needs_x_and_y() -> None:
    """A graph without a y column has no scatter plot."""
    with pytest.raises(ValueError, match="x and y"):
        scatter_spec(Encoding(x=("a",)), {"a": "a.parquet"}, 400, 300, [])
