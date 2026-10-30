"""Tests of the positions of rows on categorical axes, and of their aggregation and selection."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import polars as pl
import pytest

from ddviz.compute.aggregate import COUNT, INDEX, KEY, aggregate
from ddviz.compute.bands import (
    BAND,
    JITTER_X,
    JITTER_Y,
    SPREAD_CELLS,
    band_range,
    count_spread,
    pair_positions,
)
from ddviz.compute.selection import selection_filter
from ddviz.shared.scatter import ScatterSpec, Selection, Spread, View


def test_band_range_holds_one_band_per_level() -> None:
    """Level i is centered on i; the axis ends half a step beyond the outer levels."""
    assert band_range(["a", "b", "c"]) == (-0.5, 2.5)
    assert band_range([]) == (-0.5, 0.5)


def test_count_spread_scales_each_level_to_its_fullest_cell() -> None:
    """With one categorical axis, widths are the square root of rows over the level's fullest cell."""
    frame = pl.LazyFrame(
        {"g": ["a"] * 4 + ["a"] + ["b"] * 9, "y": [0.1] * 4 + [0.9] + [0.5] * 9}
    )
    spread = count_spread(frame, "g", "y", {"g"}, {"g": ["a", "b"]}, [0.0, 1.0])
    assert spread.bounds == [0.0, 1.0]
    widths = np.array(spread.widths).reshape(2, SPREAD_CELLS)
    a_low, a_high = int(0.1 * SPREAD_CELLS), int(0.9 * SPREAD_CELLS)
    assert widths[0, a_low] == 1.0
    assert widths[0, a_high] == pytest.approx(0.5)
    assert widths[1, SPREAD_CELLS // 2] == 1.0
    assert widths.sum() == pytest.approx(2.5)


def test_count_spread_of_two_categorical_axes_scales_to_the_fullest_cell() -> None:
    """With two categorical axes, a cell is a pair of levels, over the fullest of all."""
    frame = pl.LazyFrame({"g": ["a"] * 4 + ["b"], "h": ["p"] * 4 + ["q"]})
    levels = {"g": ["a", "b"], "h": ["p", "q"]}
    spread = count_spread(frame, "g", "h", {"g", "h"}, levels, None)
    assert spread.bounds is None
    assert spread.widths == [1.0, 0.0, 0.0, 0.5]


def test_positions_stay_in_their_band_by_row_index() -> None:
    """A row lies within BAND times its width of its level, jittered by its row index alone."""
    frame = pl.LazyFrame(
        {"g": ["a", "b", None, "b"], "y": [0.2, 0.7, 0.5, 0.7]}
    ).with_row_index(INDEX)
    levels = {"g": ["a", "b"]}
    spread = count_spread(frame, "g", "y", {"g"}, levels, [0.0, 1.0])
    x, y = pair_positions("g", "y", {"g"}, levels, spread, INDEX)
    found = frame.select(x.alias("x"), y.alias("y")).collect()
    jitter = (np.arange(4) * JITTER_X) % 1.0 * 2 - 1
    assert found["x"].to_list()[0] == pytest.approx(0 + BAND * jitter[0])
    assert found["x"].to_list()[1] == pytest.approx(1 + BAND * jitter[1])
    assert found["x"].to_list()[2] is None
    assert found["x"].to_list()[3] == pytest.approx(1 + BAND * jitter[3])
    assert found["y"].to_list() == [0.2, 0.7, 0.5, 0.7]


def test_two_categorical_axes_jitter_apart() -> None:
    """The x and y of a pair of categorical axes take different steps, so the points do not line up."""
    frame = pl.LazyFrame({"g": ["a"] * 5, "h": ["p"] * 5}).with_row_index(INDEX)
    levels = {"g": ["a"], "h": ["p"]}
    spread = count_spread(frame, "g", "h", {"g", "h"}, levels, None)
    x, y = pair_positions("g", "h", {"g", "h"}, levels, spread, INDEX)
    found = frame.select(x.alias("x"), y.alias("y")).collect()
    index = np.arange(5)
    assert found["x"].to_numpy() == pytest.approx(
        BAND * ((index * JITTER_X) % 1.0 * 2 - 1)
    )
    assert found["y"].to_numpy() == pytest.approx(
        BAND * ((index * JITTER_Y) % 1.0 * 2 - 1)
    )


@pytest.fixture
def band_spec(scatter_spec: ScatterSpec) -> ScatterSpec:
    """Return `scatter_spec` with the color column on x as a categorical axis, unfaceted and in one series."""
    return replace(
        scatter_spec,
        x=["color"],
        color=None,
        col=None,
        categorical=["color"],
        hover=["color", "y", "label"],
    )


def _positions(agg_spread: Spread, frame: pl.DataFrame) -> pl.DataFrame:
    """Return the drawn rows of `frame` with their x position worked out in numpy."""
    valid = frame.with_row_index(INDEX).filter(
        pl.col("color").is_not_null(), pl.col("y").is_finite()
    )
    level = valid["color"].replace_strict({"a": 0, "b": 1, "c": 2}).to_numpy()
    lo, hi = agg_spread.bounds
    cell = np.clip(
        np.floor((valid["y"].to_numpy() - lo) * SPREAD_CELLS / (hi - lo)),
        0,
        SPREAD_CELLS - 1,
    ).astype(np.int64)
    width = np.array(agg_spread.widths)[level * SPREAD_CELLS + cell]
    jitter = (valid[INDEX].to_numpy().astype(float) * JITTER_X) % 1.0 * 2 - 1
    return valid.with_columns(pos=pl.Series(level + BAND * width * jitter))


def test_a_categorical_x_bins_the_positions_in_its_bands(
    band_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """The overview spans the bands, counts the spread over every drawn row and bins each row at its position."""
    agg = aggregate(band_spec)
    assert agg.axis_levels == {"color": ["a", "b", "c"]}
    assert agg.x_ranges == [(-0.5, 2.5)]
    (spread,) = agg.spreads
    assert (spread.x, spread.y, spread.bounds) == ("color", "y", list(agg.y_ranges[0]))
    assert max(spread.widths) == 1.0

    rows = _positions(spread, scatter_frame)
    assert rows["pos"].min() > -0.5
    assert rows["pos"].max() < 2.5
    grid = agg.grid
    ((x0, x1),), ((y0, y1),) = agg.x_ranges, agg.y_ranges
    bx = np.clip(
        np.floor((rows["pos"].to_numpy() - x0) * grid.width / (x1 - x0)),
        0,
        grid.width - 1,
    )
    by = np.clip(
        np.floor((rows["y"].to_numpy() - y0) * grid.height / (y1 - y0)),
        0,
        grid.height - 1,
    )
    keys = grid.pack(0, 0, by.astype(np.int64), bx.astype(np.int64))
    expected = (
        pl.DataFrame({KEY: keys}).group_by(KEY).agg(pl.len().alias(COUNT)).sort(KEY)
    )
    assert agg.bins[KEY].to_list() == expected[KEY].to_list()
    assert agg.bins[COUNT].to_list() == expected[COUNT].to_list()
    # The hover shows the level's name.
    assert set(agg.bins["color"].to_list()) == {"a", "b", "c"}


def test_a_view_of_a_categorical_axis_keeps_its_spread(
    band_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A zoom reuses the overview's spread; one without widths is counted again over its bounds."""
    overview = aggregate(band_spec)
    view = View(
        x_ranges=[[0.5, 1.5]],
        y_ranges=[list(overview.y_ranges[0])],
        levels=overview.all_levels,
        axis_levels=overview.axis_levels,
        spreads=overview.spreads,
    )
    zoomed = aggregate(replace(band_spec, view=view))
    assert zoomed.spreads == overview.spreads
    # Only the band of b is in the view.
    in_b = scatter_frame.filter(pl.col("color") == "b", pl.col("y").is_finite())
    assert zoomed.bins[COUNT].sum() == in_b.height
    again = aggregate(
        replace(
            band_spec,
            view=replace(view, spreads=[replace(overview.spreads[0], widths=None)]),
        )
    )
    assert again.spreads == overview.spreads


def test_a_box_on_a_band_selects_the_points_drawn_in_it(
    band_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """The selected rows are those whose position in the band lies in the box."""
    overview = aggregate(band_spec)
    view = View(
        x_ranges=[list(r) for r in overview.x_ranges],
        y_ranges=[list(r) for r in overview.y_ranges],
        levels=overview.all_levels,
        axis_levels=overview.axis_levels,
        spreads=overview.spreads,
    )
    box = Selection(x="color", y="y", x_range=[0.9, 1.3], y_range=[-1.0, 1.0])
    spec = replace(band_spec, view=view, selection=box)
    agg = aggregate(spec, selection_only=True)

    rows = _positions(overview.spreads[0], scatter_frame).filter(
        pl.col("pos").is_between(0.9, 1.3), pl.col("y").is_between(-1.0, 1.0)
    )
    assert 0 < agg.selected_rows == rows.height
    found = (
        scatter_frame.lazy()
        .with_row_index(INDEX)
        .filter(*selection_filter(spec, INDEX))
        .collect()
    )
    assert found[INDEX].to_list() == rows[INDEX].to_list()


def test_two_categorical_axes_make_cells_of_level_pairs(
    scatter_spec: ScatterSpec,
) -> None:
    """Both axes span their bands, and every row is drawn near its pair of levels."""
    spec = replace(
        scatter_spec,
        x=["color"],
        y=["facet"],
        color=None,
        col=None,
        categorical=["color", "facet"],
        hover=["color", "facet"],
    )
    agg = aggregate(spec)
    assert (agg.x_ranges, agg.y_ranges) == ([(-0.5, 2.5)], [(-0.5, 1.5)])
    (spread,) = agg.spreads
    assert spread.bounds is None
    assert len(spread.widths) == 6
    assert max(spread.widths) == 1.0
    assert agg.bins[COUNT].sum() == 2002
