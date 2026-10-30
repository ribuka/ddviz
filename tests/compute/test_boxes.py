"""Tests of the box plots: exact quartiles, whiskers, the outliers drawn as points and the selection without points."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import polars as pl
import pytest

from ddviz.compute import boxes
from ddviz.compute.aggregate import COUNT, INDEX, aggregate
from ddviz.compute.boxes import GROUP, VALUE, box_stats
from ddviz.compute.selection import selection_filter
from ddviz.shared.scatter import ScatterSpec, Selection, View


def _expected(values: np.ndarray) -> list[float]:
    """Return ``[n, low, q1, median, q3, high]`` of `values` worked out in numpy."""
    q1, median, q3 = np.quantile(values, [0.25, 0.5, 0.75])
    iqr = q3 - q1
    inside = values[(values >= q1 - 1.5 * iqr) & (values <= q3 + 1.5 * iqr)]
    return [len(values), inside.min(), q1, median, q3, inside.max()]


def _groups(n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Return groups and values: normal, a few far outliers, and many rows of one value."""
    rng = np.random.default_rng(seed)
    group = rng.integers(0, 4, n)
    value = rng.normal(size=n)
    value[:20] = 1e9
    value[100 : n // 3] = 0.25
    # A group whose rows all have one value.
    group[-50:] = 4
    value[-50:] = 7.0
    return group, value


@pytest.mark.parametrize("cell_rows", [boxes.CELL_ROWS, 5])
def test_box_stats_match_numpy(
    monkeypatch: pytest.MonkeyPatch, cell_rows: int
) -> None:
    """The quartiles are exact, also when a group's values gather in one cell and its cells are cut again."""
    monkeypatch.setattr(boxes, "CELL_ROWS", cell_rows)
    group, value = _groups(5000)
    frame = pl.DataFrame({GROUP: group, VALUE: value}).lazy()
    stats = box_stats(frame)
    assert sorted(stats) == [0, 1, 2, 3, 4]
    for g, found in stats.items():
        assert found == pytest.approx(_expected(value[group == g]), rel=1e-12)
    assert stats[4] == [50, 7.0, 7.0, 7.0, 7.0, 7.0]


def test_box_stats_of_no_rows_is_empty() -> None:
    """No rows make no boxes."""
    frame = pl.DataFrame(
        {GROUP: pl.Series([], dtype=pl.Int64), VALUE: pl.Series([], dtype=pl.Float64)}
    )
    assert box_stats(frame.lazy()) == {}


@pytest.fixture
def box_spec(scatter_spec: ScatterSpec) -> ScatterSpec:
    """Return `scatter_spec` with box plots of y by the facet column, a series per color, and no points."""
    return replace(
        scatter_spec,
        x=["facet"],
        col=None,
        categorical=["facet"],
        hover=["facet", "y", "label"],
        points=False,
        box=True,
    )


def _drawn(frame: pl.DataFrame) -> pl.DataFrame:
    """Return the rows of `frame` a box plot of y by facet and color draws, with their row index."""
    return frame.with_row_index(INDEX).filter(
        pl.col("facet").is_not_null(),
        pl.col("color").is_not_null(),
        pl.col("y").is_finite(),
    )


def test_box_plots_hold_each_level_and_series(
    box_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """Each x level and series has its box; only the outliers are drawn as points, in their series' slot."""
    agg = aggregate(box_spec)
    (pair,) = agg.boxes
    assert (pair.x, pair.y) == ("facet", "y")
    assert agg.spreads == []
    rows = _drawn(scatter_frame)
    outliers = 0
    assert len(pair.stats) == 2 * 3
    for row, col, level, series, *found in pair.stats:
        assert (row, col) == (0, 0)
        values = rows.filter(
            pl.col("facet") == ["p", "q"][level],
            pl.col("color") == ["a", "b", "c"][series],
        )["y"].to_numpy()
        expected = _expected(values)
        assert found == pytest.approx(expected, rel=1e-12)
        fence = 1.5 * (expected[4] - expected[2])
        outliers += int(
            ((values < expected[2] - fence) | (values > expected[4] + fence)).sum()
        )
    assert 0 < agg.bins[COUNT].sum() == outliers


def test_box_plots_over_points_draw_every_row(
    box_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """With the points, every row is drawn, spread in the bands, under the boxes."""
    agg = aggregate(replace(box_spec, points=True))
    assert len(agg.boxes) == 1
    assert len(agg.spreads) == 1
    assert agg.bins[COUNT].sum() == _drawn(scatter_frame).height


def test_a_view_keeps_the_boxes_and_another_filter_finds_them_again(
    box_spec: ScatterSpec,
) -> None:
    """A zoom reuses the overview's boxes; without them, the rows the filter keeps make new ones."""
    overview = aggregate(box_spec)
    view = View(
        x_ranges=[list(r) for r in overview.x_ranges],
        y_ranges=[list(r) for r in overview.y_ranges],
        levels=overview.all_levels,
        axis_levels=overview.axis_levels,
        boxes=overview.boxes,
    )
    known = replace(overview.boxes[0], stats=[[0, 0, 0, 0, 1, 0, 0, 0, 0, 0]])
    zoomed = aggregate(replace(box_spec, view=replace(view, boxes=[known])))
    assert zoomed.boxes == [known]
    again = aggregate(replace(box_spec, view=replace(view, boxes=[])))
    assert again.boxes == overview.boxes


def test_a_selection_without_points_takes_the_rows_of_the_bands_it_covers(
    box_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A box over part of a band selects that level's rows whose y is in it, inside the boxes too."""
    overview = aggregate(box_spec)
    view = View(
        x_ranges=[list(r) for r in overview.x_ranges],
        y_ranges=[list(r) for r in overview.y_ranges],
        levels=overview.all_levels,
        axis_levels=overview.axis_levels,
        boxes=overview.boxes,
    )
    box = Selection(x="facet", y="y", x_range=[0.65, 2.0], y_range=[-0.5, 0.5])
    spec = replace(box_spec, view=view, selection=box)
    found = (
        scatter_frame.lazy()
        .with_row_index(INDEX)
        .filter(*selection_filter(spec, INDEX))
        .collect()
    )
    expected = _drawn(scatter_frame).filter(
        pl.col("facet") == "q", pl.col("y").is_between(-0.5, 0.5)
    )
    assert 0 < found.height == expected.height
    assert found[INDEX].to_list() == expected[INDEX].to_list()
    agg = aggregate(spec, selection_only=True)
    assert agg.selected_rows == expected.height
