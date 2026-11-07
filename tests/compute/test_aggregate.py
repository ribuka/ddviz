"""Tests of the pixel-bin aggregation of overviews and views against a brute-force computation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute import aggregate as aggregate_module
from ddviz.compute.aggregate import (
    COUNT,
    INDEX,
    KEY,
    Aggregation,
    _range_query,
    aggregate,
)
from ddviz.shared.scatter import ScatterSpec, Selection, View


def test_aggregate_matches_brute_force(
    scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """Counts, representative rows (largest index) and hover values match numpy."""
    agg = aggregate(scatter_spec)
    grid = agg.grid
    assert agg.levels == {
        "color": ["a", "b", "c"],
        "overlay": [None],
        "row": [None],
        "col": ["p", "q"],
    }
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
    with pytest.raises(ValueError, match="水準が上限を超えるため描けない"):
        aggregate(replace(scatter_spec, color="x"))


def test_the_level_limit_comes_from_the_spec(scatter_spec: ScatterSpec) -> None:
    """``max_levels`` refuses a color column with more levels and lets one with as many through."""
    assert aggregate(replace(scatter_spec, max_levels=3)).grid.n_series == 3
    spec = ScatterSpec.from_dict(replace(scatter_spec, max_levels=2).to_dict())
    with pytest.raises(
        ValueError, match="（color は 3 個で、Color・Overlay・Group・Wrap の上限は 2 個）"
    ):
        aggregate(spec)


def _axis_spec(scatter_spec: ScatterSpec, **changes: object) -> ScatterSpec:
    """Return the spec with the 3-level ``color`` column on a categorical x, without color and facets."""
    return replace(
        scatter_spec,
        **{"x": ["color"], "color": None, "col": None, "categorical": ["color"], **changes},
    )


@pytest.mark.parametrize("limit", [2, 3, 4])
def test_the_axis_level_limit_is_its_own(
    scatter_spec: ScatterSpec, limit: int
) -> None:
    """``max_axis_levels`` refuses a categorical x past it (3 levels against 2, 3 and 4); ``max_levels`` does not bind the axis."""
    spec = ScatterSpec.from_dict(
        _axis_spec(scatter_spec, max_levels=1, max_axis_levels=limit).to_dict()
    )
    if limit < 3:
        with pytest.raises(
            ValueError,
            match=f"（color は 3 個で、X・Y のカテゴリの軸の上限は {limit} 個）。"
            "水準はフィルタの前の行から数えるため、別の列を使う",
        ):
            aggregate(spec)
    else:
        assert aggregate(spec).levels["color"] == [None]


def test_the_axis_level_limit_binds_a_categorical_y(tmp_path: Path) -> None:
    """A categorical y column is refused past ``max_axis_levels`` as an x is."""
    path = tmp_path / "d.parquet"
    pl.DataFrame({"x": [0.0, 1.0, 2.0], "g": ["a", "b", "c"]}).write_parquet(path)
    spec = ScatterSpec(
        files={"x": [str(path)], "g": [str(path)]},
        x=["x"],
        y=["g"],
        color=None,
        row=None,
        col=None,
        width=100,
        height=100,
        hover=["x", "g"],
        categorical=["g"],
        max_axis_levels=2,
    )
    with pytest.raises(ValueError, match="g は 3 個で、X・Y のカテゴリの軸の上限は 2 個"):
        aggregate(spec)
    assert aggregate(replace(spec, max_axis_levels=3)).axis_levels == {"g": ["a", "b", "c"]}


def test_a_column_on_an_axis_and_color_meets_both_limits(
    scatter_spec: ScatterSpec,
) -> None:
    """The same column on x and color is refused by the lower limit of its roles, either one."""
    both = _axis_spec(scatter_spec, color="color")
    assert aggregate(replace(both, max_levels=3, max_axis_levels=3)).grid.n_series == 3
    with pytest.raises(ValueError, match="Color・Overlay・Group・Wrap の上限は 2 個"):
        aggregate(replace(both, max_levels=2, max_axis_levels=1_000_000))
    with pytest.raises(ValueError, match="X・Y のカテゴリの軸の上限は 2 個"):
        aggregate(replace(both, max_levels=100, max_axis_levels=2))


def test_the_series_limit_stays_100_beside_a_million_axis_levels() -> None:
    """The defaults: 100 levels for color and the other series and panel roles, a million for a categorical x or y."""
    assert ScatterSpec.__dataclass_fields__["max_levels"].default == 100
    assert ScatterSpec.__dataclass_fields__["max_axis_levels"].default == 1_000_000


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
        files={c: [str(path)] for c in frame.columns},
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


def test_selection_bins_the_selected_rows_in_every_panel(tmp_path: Path) -> None:
    """A box on the x1 x y panel of facet p selects rows that every pair's panels highlight."""
    rng = np.random.default_rng(2)
    n = 3000
    frame = pl.DataFrame(
        {
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(10, 5, n),
            "y": rng.normal(0, 1, n),
            "color": rng.choice(["a", "b"], n),
            "facet": rng.choice(["p", "q"], n),
        }
    ).with_columns(
        pl.when(pl.int_range(n) % 3 == 0).then(None).otherwise(pl.col("x2")).alias("x2")
    )
    path = tmp_path / "sel.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x1", "x2"],
        y=["y"],
        color="color",
        row=None,
        col="facet",
        width=600,
        height=400,
        hover=list(frame.columns),
    )
    overview = aggregate(spec)
    selected = replace(
        spec,
        view=View(
            x_ranges=[list(r) for r in overview.x_ranges],
            y_ranges=[list(r) for r in overview.y_ranges],
            levels=overview.levels,
        ),
        selection=Selection(
            x="x1", y="y", x_range=[-0.5, 1.0], y_range=[0.0, 2.0], col="p"
        ),
    )
    agg = aggregate(selected, selection_only=True)
    assert agg.bins is None
    assert agg.grid == overview.grid

    rows = frame.with_row_index(INDEX).filter(
        pl.col("x1").is_between(-0.5, 1.0),
        pl.col("y").is_between(0.0, 2.0),
        pl.col("facet") == "p",
    )
    assert agg.selected_rows == rows.height
    # The selected rows in every panel: the x2 panel shows those with an x2.
    grid, axes = agg.grid, agg.axes
    keys = []
    for xi, x_col in enumerate(spec.x):
        shown = rows.filter(pl.col(x_col).is_not_null())
        (x0, x1), (y0, y1) = agg.x_ranges[xi], agg.y_ranges[0]
        bx = np.clip(
            np.floor((shown[x_col].to_numpy() - x0) * grid.width / (x1 - x0)),
            0,
            grid.width - 1,
        ).astype(np.int64)
        by = np.clip(
            np.floor((shown["y"].to_numpy() - y0) * grid.height / (y1 - y0)),
            0,
            grid.height - 1,
        ).astype(np.int64)
        series = shown["color"].replace_strict({"a": 0, "b": 1}).to_numpy()
        keys.append(grid.pack(axes.panel(0, 0, xi, 0), series, by, bx))
    expected = np.unique(np.concatenate(keys))
    assert agg.selected[KEY].to_list() == expected.tolist()
    panels, *_ = grid.unpack(agg.selected[KEY].to_numpy())
    assert set(panels.tolist()) == {axes.panel(0, 0, 0, 0), axes.panel(0, 0, 1, 0)}


def test_wrapped_levels_are_panels_in_rows(
    scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """Each wrapped level is the panel of its index, two to a row."""
    wrapped = replace(scatter_spec, col="color", wrap=True, wrap_cols=2)
    agg = aggregate(wrapped)
    assert agg.levels["col"] == ["a", "b", "c"]
    assert (agg.axes.nrow, agg.axes.ncol, agg.axes.panels) == (2, 2, 3)
    assert (agg.layout.nrow, agg.layout.ncol) == (2, 2)
    assert agg.grid.n_panels == 4
    panels, *_ = agg.grid.unpack(agg.bins[KEY].to_numpy())
    levels = scatter_frame[agg.bins[INDEX].to_list()]["color"].to_list()
    assert [agg.levels["col"][p] for p in panels] == levels
    assert sorted(set(panels.tolist())) == [0, 1, 2]


def test_levels_are_in_natural_order(tmp_path: Path) -> None:
    """Color, overlay and facet levels compare numbers by value (``2_`` before ``10_``), nulls left out."""
    n = 600
    names = ["10_", "1_", "2_", None]
    frame = pl.DataFrame(
        {
            "x": np.linspace(0, 1, n),
            "y": np.linspace(1, 2, n),
            "g": [names[i % 4] for i in range(n)],
            "h": [["b10", "B2", "a"][i % 3] for i in range(n)],
        }
    )
    path = tmp_path / "levels.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in ["x", "y", "g", "h"]},
        x=["x"],
        y=["y"],
        color="g",
        overlay="h",
        row="h",
        col="g",
        width=400,
        height=300,
        hover=["x", "y"],
    )
    levels = aggregate(spec).levels
    assert levels["color"] == levels["col"] == ["1_", "2_", "10_"]
    assert levels["overlay"] == levels["row"] == ["a", "B2", "b10"]


def _sliced_and_whole(
    spec: ScatterSpec, monkeypatch: pytest.MonkeyPatch, selection_only: bool = False
) -> tuple[Aggregation, Aggregation]:
    """Return the aggregation of `spec` 7 rows at a time and in one pass."""
    monkeypatch.setattr(aggregate_module, "ROWS_PER_PASS", 7)
    sliced = aggregate(spec, selection_only=selection_only)
    monkeypatch.setattr(aggregate_module, "ROWS_PER_PASS", 2**32 - 1)
    whole = aggregate(spec, selection_only=selection_only)
    return sliced, whole


def test_bins_in_slices_match_one_pass(
    scatter_spec: ScatterSpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Binning a few rows at a time gives the keys, counts and representative rows of one pass."""
    sliced, whole = _sliced_and_whole(scatter_spec, monkeypatch)
    assert sliced.bins.equals(whole.bins)
    # Few values: the rows of a bin fall in many slices.
    path = tmp_path / "few.parquet"
    i = pl.int_range(100, eager=True)
    pl.DataFrame(
        {"x": (i % 5).cast(pl.Float32), "y": (i % 3).cast(pl.Float32)}
    ).write_parquet(path)
    spec = replace(
        scatter_spec,
        files={"x": [str(path)], "y": [str(path)]},
        color=None,
        col=None,
        hover=["x", "y"],
    )
    sliced, whole = _sliced_and_whole(spec, monkeypatch)
    assert sliced.bins.equals(whole.bins)
    assert sliced.bins[COUNT].dtype == pl.UInt32
    # i mod 15 picks the bin: 10 bins of 7 rows and 5 of 6, each over many slices.
    assert sorted(sliced.bins[COUNT].to_list()) == [6] * 5 + [7] * 10
    assert sliced.bins[INDEX].max() == 99


def test_outliers_in_slices_match_one_pass(
    scatter_spec: ScatterSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pair drawing only the outliers of its box plots bins the same rows in slices."""
    spec = replace(
        scatter_spec,
        x=["facet"],
        col=None,
        categorical=["facet"],
        hover=["facet", "y", "label"],
        points=False,
        box=True,
    )
    sliced, whole = _sliced_and_whole(spec, monkeypatch)
    assert sliced.bins.height > 0
    assert sliced.bins.equals(whole.bins)


def test_selection_in_slices_matches_one_pass(
    scatter_spec: ScatterSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bins of a selection are the same in slices and in one pass."""
    overview = aggregate(scatter_spec)
    spec = replace(
        scatter_spec,
        view=View(
            x_ranges=[list(r) for r in overview.x_ranges],
            y_ranges=[list(r) for r in overview.y_ranges],
            levels=overview.levels,
        ),
        selection=Selection(
            x="x", y="y", x_range=list(overview.x_ranges[0]), y_range=[-1.0, 1.0]
        ),
    )
    sliced, whole = _sliced_and_whole(spec, monkeypatch, selection_only=True)
    assert sliced.selected.height > 0
    assert sliced.selected.equals(whole.selected)
    assert sliced.selected_rows == whole.selected_rows


def test_range_skips_nan_inf_and_null(tmp_path: Path) -> None:
    """The range of a column is that of its finite values; one without any has none."""
    path = tmp_path / "r.parquet"
    pl.DataFrame(
        {
            "v": [3.0, float("nan"), None, float("inf"), -2.5, float("-inf")],
            "nan": [float("nan")] * 6,
        }
    ).write_parquet(path)
    spec = ScatterSpec(
        files={"v": [str(path)], "nan": [str(path)]},
        x=["v"],
        y=["nan"],
        color=None,
        row=None,
        col=None,
        width=100,
        height=100,
        hover=[],
    )
    assert _range_query(spec, "v").collect().row(0) == (-2.5, 3.0)
    assert _range_query(spec, "nan").collect().row(0) == (None, None)
