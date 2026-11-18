"""Tests of `ScatterSpec.facet_layout`: the panels and their layout as `facet_grid` and `grid_layout` give them."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ddviz.shared.layout import GAP, WRAP_GAP, facet_grid, grid_layout
from ddviz.shared.scatter import ScatterSpec


def _spec(**fields: object) -> ScatterSpec:
    """Return a spec of two x columns and one y column, with `fields` set."""
    spec = ScatterSpec(
        files={},
        x=["a", "b"],
        y=["c"],
        color=None,
        row="r",
        col="k",
        width=900,
        height=600,
        margin_left=70,
        margin_bottom=50,
    )
    return replace(spec, **fields)


def test_facet_layout_without_wrap() -> None:
    """Without wrap, the panels are row by col by x by y, `GAP` apart."""
    spec = _spec()
    levels = {"row": ["r0", "r1"], "col": ["k0", "k1", "k2"], "color": [None]}
    axes, layout = spec.facet_layout(levels)
    expected_axes = facet_grid(2, 3, 2, 1, False, None, 900, 600, 70, 50)
    assert axes == expected_axes
    assert layout == grid_layout(
        900, 600, expected_axes.rows, expected_axes.cols, GAP, 70, 50
    )
    assert (layout.nrow, layout.ncol) == (2, 6)


@pytest.mark.parametrize("wrap_cols", [None, 3])
def test_facet_layout_with_wrap(wrap_cols: int | None) -> None:
    """With wrap, the col levels wrap into rows, `WRAP_GAP` apart, with or without `wrap_cols`."""
    spec = _spec(x=["a"], row=None, wrap=True, wrap_cols=wrap_cols)
    levels = {"row": [None], "col": [f"k{i}" for i in range(7)]}
    axes, layout = spec.facet_layout(levels)
    expected_axes = facet_grid(1, 7, 1, 1, True, wrap_cols, 900, 600, 70, 50)
    assert axes == expected_axes
    assert layout == grid_layout(
        900, 600, expected_axes.rows, expected_axes.cols, WRAP_GAP, 70, 50
    )
    assert layout.row_gap == WRAP_GAP
    if wrap_cols is not None:
        assert (axes.rows, axes.cols) == (3, 3)
