"""Tests of the box plots: exact quartiles, whiskers, the outliers drawn as points and the selection without points."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute import boxes
from ddviz.compute.aggregate import COUNT, INDEX, aggregate
from ddviz.compute.boxes import GROUP, VALUE, box_stats
from ddviz.compute.selection import selection_filter
from ddviz.shared.scatter import Filter, ScatterSpec, Selection, View


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
def test_box_stats_match_numpy(monkeypatch: pytest.MonkeyPatch, cell_rows: int) -> None:
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
    assert agg.piles == []
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
    """With the points, every row is drawn in the bands, under the boxes."""
    agg = aggregate(replace(box_spec, points=True))
    assert len(agg.boxes) == 1
    assert len(agg.piles) == 1
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


def test_box_plots_follow_a_filter_that_drops_facet_levels(
    box_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A filter that leaves a Group X level without rows drops its panel; the other's outliers are found."""
    spec = replace(
        box_spec,
        x=["color"],
        col="facet",
        color=None,
        categorical=["color"],
        filters=[Filter(column="facet", levels=["p"])],
    )
    agg = aggregate(spec)
    assert agg.levels["col"] == ["p"]
    (pair,) = agg.boxes
    assert {tuple(b[:4]) for b in pair.stats} == {(0, 0, i, 0) for i in range(3)}
    assert agg.bins[COUNT].sum() > 0


def test_box_plots_without_series_draw_nothing(
    box_spec: ScatterSpec, tmp_path: Path, scatter_frame: pl.DataFrame
) -> None:
    """A color column with no values makes no series: no boxes and no outliers, and no error."""
    path = tmp_path / "nulls.parquet"
    scatter_frame.with_columns(pl.lit(None, pl.String).alias("color")).write_parquet(
        path
    )
    spec = replace(box_spec, files={**box_spec.files, "color": [str(path)]})
    agg = aggregate(spec)
    assert agg.grid.n_series == 0
    assert agg.boxes[0].stats == []
    assert agg.bins.height == 0


def _months(tmp_path: Path) -> ScatterSpec:
    """Return a spec of box plots of y by ``month``, 420 levels ("1990-01" to "2024-12"), without points."""
    months = [f"{y}-{m:02d}" for y in range(1990, 2025) for m in range(1, 13)]
    rng = np.random.default_rng(0)
    path = tmp_path / "months.parquet"
    pl.DataFrame(
        {"month": [months[i % 420] for i in range(4200)][::-1], "y": rng.normal(size=4200)}
    ).write_parquet(path)
    return ScatterSpec(
        files={c: [str(path)] for c in ("month", "y")},
        x=["month"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=400,
        height=300,
        hover=["month", "y"],
        categorical=["month"],
        points=False,
        box=True,
    )


def test_box_plots_of_420_levels_draw_past_the_series_limit(tmp_path: Path) -> None:
    """A categorical x of 420 levels has a box per level, in natural order, under the default limits."""
    agg = aggregate(_months(tmp_path))
    (pair,) = agg.boxes
    assert sorted(s[2] for s in pair.stats) == list(range(420))
    assert agg.axis_levels["month"][:2] == ["1990-01", "1990-02"]
    assert agg.axis_levels["month"][-1] == "2024-12"


def test_the_box_column_on_color_too_meets_the_series_limit(tmp_path: Path) -> None:
    """The same 420 levels on x and color are refused by color's limit of 100, kept over every row."""
    spec = replace(_months(tmp_path), color="month", keep_unfiltered_color_levels=True)
    with pytest.raises(ValueError, match="month は 420 個で、Color・Symbol・Group・Wrap の上限は 100 個"):
        aggregate(spec)
