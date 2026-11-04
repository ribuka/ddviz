"""Tests of the specs derived from a drawn result."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ddviz.server.derive import (
    box_selection,
    resized_spec,
    selection_spec,
    unchanged,
)
from ddviz.shared.keys import BinGrid
from ddviz.shared.layout import WRAP_GAP, AxisGrid, facet_grid, grid_layout
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import Boxes, Filter, ScatterSpec


@pytest.fixture
def manifest(scatter_spec: ScatterSpec) -> PlotManifest:
    """Return the manifest of an overview of `scatter_spec`: two facet columns, p and q."""
    levels = {"row": [None], "col": ["p", "q"], "color": ["a", "b", "c"]}
    return PlotManifest(
        spec=scatter_spec,
        grid=BinGrid(n_panels=2, n_series=3, width=150, height=200),
        layout=grid_layout(400, 300, 1, 2),
        axes=AxisGrid(1, 2),
        x_ranges=[[-4.0, 4.0]],
        y_ranges=[[-3.0, 3.0]],
        levels=levels,
        all_levels=levels,
        cuts={},
        color_range=None,
        colors=["#000000"] * 3,
        columns=[],
        images=[None] * 3,
        rows=2000,
    )


def test_resized_spec_keeps_the_panels_of_the_same_filter(
    manifest: PlotManifest,
) -> None:
    """Another size or range reuses the overview's levels and its facet panels."""
    spec = resized_spec(manifest, 800, 600, [], {}, [[0, 1]], [[0, 2]])
    assert (spec.width, spec.height) == (800, 600)
    assert spec.view.x_ranges == [[0, 1]]
    assert spec.view.y_ranges == [[0, 2]]
    assert spec.view.levels == manifest.all_levels
    assert spec.view.facets == {"row": [None], "col": ["p", "q"]}


def test_resized_spec_with_another_filter_finds_its_panels(
    manifest: PlotManifest,
) -> None:
    """A new filter adds its column's file and leaves the facet panels to the worker."""
    filters = [Filter(column="label", levels=["r1"])]
    spec = resized_spec(
        manifest, 400, 300, filters, {"label": ["label.parquet"]}, [[0, 1]], [[0, 1]]
    )
    assert spec.view.facets is None
    assert spec.filters == filters
    assert spec.files["label"] == ["label.parquet"]


def test_resized_spec_needs_a_range_per_axis_column(manifest: PlotManifest) -> None:
    """A request with the wrong number of ranges is refused."""
    with pytest.raises(ValueError, match="one range"):
        resized_spec(manifest, 400, 300, [], {}, [], [[0, 1]])


def test_unchanged(manifest: PlotManifest) -> None:
    """A result stands for a spec with its layout, ranges and filter."""
    same = resized_spec(
        manifest, 400, 300, [], {}, manifest.x_ranges, manifest.y_ranges
    )
    assert unchanged(manifest, same)
    assert not unchanged(None, same)
    zoomed = resized_spec(manifest, 400, 300, [], {}, [[0, 1]], manifest.y_ranges)
    assert not unchanged(manifest, zoomed)
    larger = resized_spec(
        manifest, 800, 600, [], {}, manifest.x_ranges, manifest.y_ranges
    )
    assert not unchanged(manifest, larger)
    filtered = resized_spec(
        manifest,
        400,
        300,
        [Filter(column="label", levels=["r1"])],
        {"label": ["label.parquet"]},
        manifest.x_ranges,
        manifest.y_ranges,
    )
    assert not unchanged(manifest, filtered)


def test_box_selection(manifest: PlotManifest) -> None:
    """A box on the second panel selects its facet level, with sorted ranges."""
    selection = box_selection(manifest, 1, (2.0, -1.0), (0.0, 1.0))
    assert (selection.x, selection.y) == ("x", "y")
    assert selection.x_range == [-1.0, 2.0]
    assert selection.col == "q"
    assert selection.row is None


@pytest.mark.parametrize(
    ("panel", "x_range", "match"),
    [
        (2, (0.0, 1.0), "no such panel"),
        (-1, (0.0, 1.0), "no such panel"),
        (0, None, "needs"),
    ],
)
def test_box_selection_refuses(
    manifest: PlotManifest, panel: int, x_range: tuple | None, match: str
) -> None:
    """A panel the result lacks, or a box without both ranges, is refused."""
    with pytest.raises(ValueError, match=match):
        box_selection(manifest, panel, x_range, (0.0, 1.0))


def test_selection_spec(manifest: PlotManifest) -> None:
    """A selection's spec is the result's, with its view and panels."""
    selection = box_selection(manifest, 0, (0.0, 1.0), (0.0, 1.0))
    spec = selection_spec(manifest, selection)
    assert spec.selection == selection
    assert spec.view.x_ranges == manifest.x_ranges
    assert spec.view.facets == {"row": [None], "col": ["p", "q"]}


@pytest.fixture
def wrapped(manifest: PlotManifest) -> PlotManifest:
    """Return `manifest` with three wrapped levels, two to a row."""
    levels = {"row": [None], "col": ["p", "q", "r"], "color": ["a", "b", "c"]}
    spec = replace(manifest.spec, wrap=True, wrap_cols=None, width=1000, height=400)
    axes = facet_grid(1, 3, 1, 1, True, None, 1000, 400)
    return replace(
        manifest,
        spec=spec,
        layout=grid_layout(1000, 400, axes.rows, axes.cols, WRAP_GAP),
        axes=axes,
        levels=levels,
        all_levels=levels,
    )


def test_box_selection_on_a_wrapped_grid(wrapped: PlotManifest) -> None:
    """A box on a wrapped panel selects its level; the empty cells are no panels."""
    assert wrapped.axes.ncol == 3
    assert box_selection(wrapped, 2, (0.0, 1.0), (0.0, 1.0)).col == "r"
    with pytest.raises(ValueError, match="no such panel"):
        box_selection(wrapped, 3, (0.0, 1.0), (0.0, 1.0))


def test_a_wrapped_grid_changes_with_the_size(wrapped: PlotManifest) -> None:
    """A tall size puts fewer wrapped panels to a row, so the result no longer stands."""
    ranges = (wrapped.x_ranges, wrapped.y_ranges)
    assert unchanged(wrapped, resized_spec(wrapped, 1000, 400, [], {}, *ranges))
    assert not unchanged(wrapped, resized_spec(wrapped, 400, 1000, [], {}, *ranges))


def test_boxes_are_kept_for_the_same_filter_only(manifest: PlotManifest) -> None:
    """A view and a selection reuse the boxes; another filter finds them again."""
    boxes = Boxes(x="color", y="y", stats=[[0, 0, 0, 0, 3, 0.0, 1.0, 2.0, 3.0, 4.0]])
    boxed = replace(
        manifest,
        spec=replace(manifest.spec, x=["color"], categorical=["color"], box=True),
        axis_levels={"color": ["a", "b", "c"]},
        boxes=[boxes],
    )
    assert resized_spec(boxed, 400, 300, [], {}, [[0, 1]], [[0, 1]]).view.boxes == [
        boxes
    ]
    filters = [Filter(column="label", levels=["r1"])]
    other = resized_spec(
        boxed, 400, 300, filters, {"label": ["label.parquet"]}, [[0, 1]], [[0, 1]]
    )
    assert other.view.boxes == []
    box = box_selection(boxed, 0, (0.5, 1.5), (0, 1))
    assert selection_spec(boxed, box).view.boxes == [boxes]
