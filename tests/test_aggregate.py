"""Tests of the pixel-bin aggregation of overviews and views against a brute-force computation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.aggregate import COUNT, INDEX, KEY, aggregate
from ddviz.scatter import ScatterSpec, View


def test_aggregate_matches_brute_force(
    scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """Counts, representative rows (largest index) and hover values match numpy."""
    agg = aggregate(scatter_spec)
    grid = agg.grid
    assert agg.levels == {"color": ["a", "b", "c"], "row": [None], "col": ["p", "q"]}
    assert (grid.n_panels, grid.n_series) == (2, 3)
    assert (grid.width, grid.height) == (
        agg.layout.panel_width,
        agg.layout.panel_height,
    )

    frame = scatter_frame.with_row_index(INDEX)
    valid = frame.filter(
        pl.col("x").is_finite(), pl.col("y").is_finite(), pl.col("color").is_not_null()
    )
    ((x0, x1),), ((y0, y1),) = agg.x_ranges, agg.y_ranges
    bx = np.clip(
        np.floor((valid["x"].to_numpy() - x0) * grid.width / (x1 - x0)),
        0,
        grid.width - 1,
    )
    by = np.clip(
        np.floor((valid["y"].to_numpy() - y0) * grid.height / (y1 - y0)),
        0,
        grid.height - 1,
    )
    series = valid["color"].replace_strict({"a": 0, "b": 1, "c": 2}).to_numpy()
    panel = valid["facet"].replace_strict({"p": 0, "q": 1}).to_numpy()
    keys = grid.pack(panel, series, by.astype(np.int64), bx.astype(np.int64))
    expected = (
        pl.DataFrame({KEY: keys, INDEX: valid[INDEX]})
        .group_by(KEY)
        .agg(pl.len().cast(pl.UInt32).alias(COUNT), pl.col(INDEX).max())
        .sort(KEY)
    )

    bins = agg.bins
    assert bins[KEY].to_list() == expected[KEY].to_list()
    assert bins[COUNT].cast(pl.UInt32).to_list() == expected[COUNT].to_list()
    assert (
        bins[INDEX].cast(pl.Int64).to_list() == expected[INDEX].cast(pl.Int64).to_list()
    )
    assert bins[COUNT].sum() == 2000
    rows = frame[bins[INDEX].to_list()]
    assert bins["label"].to_list() == rows["label"].to_list()
    assert bins["x"].to_list() == rows["x"].to_list()


def test_view_bins_only_the_rows_in_its_ranges(
    scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A view keeps the overview's levels and bins exactly its ranges, leaving out other rows."""
    overview = aggregate(scatter_spec)
    view = replace(
        scatter_spec,
        view=View(
            x_ranges=[[-0.5, 1.0]], y_ranges=[[0.0, 2.0]], levels=overview.levels
        ),
    )
    agg = aggregate(view)
    assert agg.levels == overview.levels
    assert (agg.x_ranges, agg.y_ranges) == ([(-0.5, 1.0)], [(0.0, 2.0)])
    assert agg.grid == overview.grid

    frame = scatter_frame.with_row_index(INDEX)
    inside = frame.filter(
        pl.col("x").is_between(-0.5, 1.0),
        pl.col("y").is_between(0.0, 2.0),
        pl.col("color").is_not_null(),
    )
    grid = agg.grid
    bx = np.clip(
        np.floor((inside["x"].to_numpy() + 0.5) * grid.width / 1.5), 0, grid.width - 1
    )
    by = np.clip(
        np.floor(inside["y"].to_numpy() * grid.height / 2.0), 0, grid.height - 1
    )
    series = inside["color"].replace_strict({"a": 0, "b": 1, "c": 2}).to_numpy()
    panel = inside["facet"].replace_strict({"p": 0, "q": 1}).to_numpy()
    keys = grid.pack(panel, series, by.astype(np.int64), bx.astype(np.int64))
    assert sorted(set(keys.tolist())) == agg.bins[KEY].to_list()
    assert agg.bins[COUNT].sum() == inside.height
    assert 0 < inside.height < 2000


def test_a_role_with_too_many_levels_is_refused(scatter_spec: ScatterSpec) -> None:
    """A numeric column on color has a level per row and is refused before binning."""
    with pytest.raises(ValueError, match="too many levels"):
        aggregate(replace(scatter_spec, color="x"))


def test_each_pair_of_axis_columns_is_a_panel(tmp_path: Path) -> None:
    """Every pair of an x and a y column bins the rows that have both, in its own panel and ranges."""
    rng = np.random.default_rng(1)
    n = 3000
    frame = pl.DataFrame(
        {
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(10, 5, n),
            "y1": rng.normal(-3, 1, n),
            "y2": rng.normal(100, 20, n),
            "facet": rng.choice(["p", "q"], n),
        }
    )
    # The columns are sparse: each misses a different part of the rows.
    frame = frame.with_columns(
        pl.when(pl.int_range(n) % 3 == 0)
        .then(None)
        .otherwise(pl.col("x2"))
        .alias("x2"),
        pl.when(pl.int_range(n) % 4 == 1)
        .then(None)
        .otherwise(pl.col("y1"))
        .alias("y1"),
    )
    path = tmp_path / "pairs.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: str(path) for c in frame.columns},
        x=["x1", "x2"],
        y=["y1", "y2"],
        color=None,
        row=None,
        col="facet",
        width=600,
        height=500,
        hover=list(frame.columns),
    )
    agg = aggregate(spec)
    axes = agg.axes
    assert (axes.nrow, axes.ncol, axes.nx, axes.ny) == (1, 2, 2, 2)
    assert (agg.layout.nrow, agg.layout.ncol) == (2, 4)
    grid = agg.grid
    assert grid.n_panels == 8

    indexed = frame.with_row_index(INDEX)
    keys = []
    for yj, y_col in enumerate(spec.y):
        for xi, x_col in enumerate(spec.x):
            (x0, x1), (y0, y1) = agg.x_ranges[xi], agg.y_ranges[yj]
            assert x0 < frame[x_col].min() and frame[x_col].max() < x1
            rows = indexed.filter(
                pl.col(x_col).is_not_null(), pl.col(y_col).is_not_null()
            )
            bx = np.clip(
                np.floor((rows[x_col].to_numpy() - x0) * grid.width / (x1 - x0)),
                0,
                grid.width - 1,
            ).astype(np.int64)
            by = np.clip(
                np.floor((rows[y_col].to_numpy() - y0) * grid.height / (y1 - y0)),
                0,
                grid.height - 1,
            ).astype(np.int64)
            col = rows["facet"].replace_strict({"p": 0, "q": 1}).to_numpy()
            panel = axes.panel(0, col, xi, yj)
            keys.append(
                pl.DataFrame(
                    {
                        KEY: grid.pack(panel, 0, by, bx),
                        INDEX: rows[INDEX].cast(pl.Int64),
                    }
                )
            )
    expected = (
        pl.concat(keys)
        .group_by(KEY)
        .agg(pl.len().cast(pl.UInt32).alias(COUNT), pl.col(INDEX).max())
        .sort(KEY)
    )
    bins = agg.bins
    assert bins[KEY].to_list() == expected[KEY].to_list()
    assert bins[COUNT].cast(pl.UInt32).to_list() == expected[COUNT].to_list()
    assert bins[INDEX].cast(pl.Int64).to_list() == expected[INDEX].to_list()
    rows = indexed[bins[INDEX].to_list()]
    assert bins["y2"].to_list() == rows["y2"].to_list()

    # A view keeps the panels and bins each pair over its own columns' ranges.
    view = replace(
        spec,
        view=View(
            x_ranges=[[-1.0, 1.0], [5.0, 15.0]],
            y_ranges=[[-4.0, -2.0], [80.0, 120.0]],
            levels=agg.levels,
        ),
    )
    zoomed = aggregate(view)
    assert zoomed.axes == axes
    panels, *_ = zoomed.grid.unpack(zoomed.bins[KEY].to_numpy())
    for p in np.unique(panels):
        xi, yj = axes.axes(int(p))
        lo, hi = view.view.x_ranges[xi]
        values = indexed[zoomed.bins.filter(pl.Series(panels == p))[INDEX].to_list()]
        assert values[spec.x[xi]].is_between(lo, hi).all()
