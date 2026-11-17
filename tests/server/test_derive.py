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
from ddviz.shared.scatter import Binning, Boxes, Filter, ScatterSpec


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
        x_auto=[[-4.0, 4.0]],
        y_auto=[[-3.0, 3.0]],
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


def test_resized_spec_keeps_the_margins_within_the_size(manifest: PlotManifest) -> None:
    """The margins asked for are kept within the size (`left_margin`, `bottom_margin`), and another margin is another layout."""
    spec = resized_spec(
        manifest,
        400,
        300,
        [],
        {},
        manifest.x_ranges,
        manifest.y_ranges,
        margin_left=10,
        margin_bottom=1000,
    )
    assert (spec.margin_left, spec.margin_bottom) == (50, 300 - 54 - 17 - 1)
    assert not unchanged(manifest, spec)


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


def test_another_filter_finds_the_color_levels_unless_known(
    manifest: PlotManifest,
) -> None:
    """Another filter asks the worker for the color levels of its rows, unless a result of that filter gives them; the same filter keeps them."""
    filters = [Filter(column="label", levels=["r1"])]
    files = {"label": ["label.parquet"]}
    same = resized_spec(manifest, 400, 300, [], {}, [[0, 1]], [[0, 1]])
    assert not same.view.find_color
    other = resized_spec(manifest, 400, 300, filters, files, [[0, 1]], [[0, 1]])
    assert other.view.find_color
    assert not other.keep_unfiltered_color_levels
    known = replace(
        manifest,
        spec=replace(manifest.spec, filters=filters),
        all_levels={**manifest.all_levels, "color": ["b"]},
    )
    taken = resized_spec(
        manifest, 400, 300, filters, files, [[0, 1]], [[0, 1]], known=known
    )
    assert not taken.view.find_color
    assert taken.view.levels["color"] == ["b"]
    # A result of another filter gives nothing.
    elsewhere = resized_spec(
        manifest, 400, 300, [], {}, [[0, 1]], [[0, 1]], known=known
    )
    assert elsewhere.view.levels["color"] == ["a", "b", "c"]


def test_kept_color_levels_stay_with_another_filter(manifest: PlotManifest) -> None:
    """Kept over every row, another filter keeps the color levels, and the setting goes with the spec."""
    kept = replace(
        manifest, spec=replace(manifest.spec, keep_unfiltered_color_levels=True)
    )
    filters = [Filter(column="label", levels=["r1"])]
    spec = resized_spec(
        kept, 400, 300, filters, {"label": ["l.parquet"]}, [[0, 1]], [[0, 1]]
    )
    assert spec.keep_unfiltered_color_levels
    assert not spec.view.find_color
    assert spec.view.levels["color"] == ["a", "b", "c"]
    selected = selection_spec(kept, box_selection(kept, 0, (0.0, 1.0), (0.0, 1.0)))
    assert selected.keep_unfiltered_color_levels


def test_the_automatic_ranges_come_from_a_result_of_the_filter(
    manifest: PlotManifest,
) -> None:
    """A view reuses the automatic ranges of a result of its filter and fills its auto columns from them; another filter leaves them to the worker."""
    filters = [Filter(column="label", levels=["r1"])]
    files = {"label": ["label.parquet"]}
    same = resized_spec(manifest, 400, 300, [], {}, [None], [[0, 1]])
    assert same.view.x_auto == [[-4.0, 4.0]]
    assert same.view.y_auto == [[-3.0, 3.0]]
    assert same.view.x_ranges == [[-4.0, 4.0]]
    assert same.view.y_ranges == [[0, 1]]
    other = resized_spec(manifest, 400, 300, filters, files, [None], [[0, 1]])
    assert other.view.x_auto is None
    assert other.view.x_ranges == [None]
    known = replace(
        manifest,
        spec=replace(manifest.spec, filters=filters),
        x_auto=[[-1.0, 1.0]],
        y_auto=[[0.0, 2.0]],
    )
    taken = resized_spec(
        manifest, 400, 300, filters, files, [None], [None], known=known
    )
    assert taken.view.x_auto == [[-1.0, 1.0]]
    assert (taken.view.x_ranges, taken.view.y_ranges) == ([[-1.0, 1.0]], [[0.0, 2.0]])
    # The overview of the filter at another size is unchanged when it has them.
    assert not unchanged(manifest, other)
    assert unchanged(manifest, same) is (same.view.y_ranges == manifest.y_ranges)


def test_a_selection_keeps_the_automatic_ranges_of_its_result(
    manifest: PlotManifest,
) -> None:
    """The layer of a selection finds no range again."""
    spec = selection_spec(manifest, box_selection(manifest, 0, (0.0, 1.0), (0.0, 1.0)))
    assert spec.view.x_auto == manifest.x_auto
    assert spec.view.y_auto == manifest.y_auto


@pytest.fixture
def gradient(manifest: PlotManifest) -> PlotManifest:
    """Return the overview of `manifest` colored by a gradient of x over 0 to 10, every row."""
    return replace(
        manifest,
        spec=replace(manifest.spec, color="x", gradient=True),
        color_range=[0.0, 10.0],
        all_levels={**manifest.all_levels, "color": [None]},
    )


def test_the_color_scale_comes_from_a_result_of_the_filter(
    gradient: PlotManifest,
) -> None:
    """A view of the overview's filter draws its color range; another filter asks the worker, unless a result of that filter gives one; one kept by the page wins."""
    filters = [Filter(column="label", levels=["r1"])]
    files = {"label": ["label.parquet"]}
    same = resized_spec(gradient, 400, 300, [], {}, [[0, 1]], [[0, 1]])
    assert not same.view.find_color_scale
    assert same.view.color_range == [0.0, 10.0]
    assert same.color_scale is None
    other = resized_spec(gradient, 400, 300, filters, files, [[0, 1]], [[0, 1]])
    assert other.view.find_color_scale
    known = replace(
        gradient, spec=replace(gradient.spec, filters=filters), color_range=[2.0, 3.0]
    )
    taken = resized_spec(
        gradient, 400, 300, filters, files, [[0, 1]], [[0, 1]], known=known
    )
    assert not taken.view.find_color_scale
    assert taken.view.color_range == [2.0, 3.0]
    assert taken.color_scale is None
    # A result of another filter, or one drawn with a scale kept, gives none.
    elsewhere = resized_spec(
        gradient, 400, 300, [], {}, [[0, 1]], [[0, 1]], known=known
    )
    assert elsewhere.view.color_range == [0.0, 10.0]
    held = replace(known, spec=replace(known.spec, color_scale={"range": [2.0, 3.0]}))
    unknown = resized_spec(
        gradient, 400, 300, filters, files, [[0, 1]], [[0, 1]], known=held
    )
    assert unknown.view.find_color_scale
    # The scale kept by the page is drawn as it is, and the spec holds it.
    kept = {"range": [0.0, 10.0]}
    frozen = resized_spec(
        gradient, 400, 300, filters, files, [[0, 1]], [[0, 1]], color_scale=kept
    )
    assert not frozen.view.find_color_scale
    assert frozen.view.color_range == [0.0, 10.0]
    assert frozen.color_scale == kept
    # One that is the filter's own is none kept.
    own = resized_spec(gradient, 400, 300, [], {}, [[0, 1]], [[0, 1]], color_scale=kept)
    assert own.color_scale is None


def test_a_kept_scale_drawn_is_not_that_of_the_filter(gradient: PlotManifest) -> None:
    """The overview drawn with a scale kept stands for a request keeping that scale, not for one of the filter's own; the next view finds the filter's."""
    held = replace(
        gradient,
        spec=replace(gradient.spec, color_scale={"range": [0.0, 10.0]}),
    )
    ranges = (held.x_ranges, held.y_ranges)
    kept = resized_spec(
        held, 400, 300, [], {}, *ranges, color_scale={"range": [0.0, 10.0]}
    )
    assert unchanged(held, kept)
    own = resized_spec(held, 400, 300, [], {}, *ranges)
    assert own.view.find_color_scale
    assert not unchanged(held, own)
    assert not unchanged(
        gradient,
        resized_spec(
            gradient, 400, 300, [], {}, *ranges, color_scale={"range": [1.0, 2.0]}
        ),
    )


def test_intervals_carry_the_cuts_of_the_color(manifest: PlotManifest) -> None:
    """A color cut into intervals carries the cuts of a result of the filter, or those kept, beside those of the other roles."""
    cut = {"breaks": [0.0, 5.0, 10.0], "values": False}
    binned = replace(
        manifest,
        spec=replace(manifest.spec, color="x", binned={"color": Binning(2, "values")}),
        cuts={"color": cut, "col": {"breaks": [0.0, 1.0], "values": False}},
    )
    filters = [Filter(column="label", levels=["r1"])]
    kept = {"breaks": [1.0, 2.0, 3.0], "values": False}
    spec = resized_spec(
        binned,
        400,
        300,
        filters,
        {"label": ["l"]},
        [[0, 1]],
        [[0, 1]],
        color_scale=kept,
    )
    assert spec.view.cuts == {**binned.cuts, "color": kept}
    assert spec.color_scale == kept
    selected = selection_spec(binned, box_selection(binned, 0, (0.0, 1.0), (0.0, 1.0)))
    assert not selected.view.find_color_scale
    assert selected.view.cuts == binned.cuts


def test_a_categorical_color_has_no_scale(manifest: PlotManifest) -> None:
    """A categorical color finds no scale, and keeps none."""
    filters = [Filter(column="label", levels=["r1"])]
    spec = resized_spec(
        manifest,
        400,
        300,
        filters,
        {"label": ["l"]},
        [[0, 1]],
        [[0, 1]],
        color_scale=None,
    )
    assert not spec.view.find_color_scale
    assert spec.color_scale is None
