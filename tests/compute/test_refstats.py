"""Statistics of the reference lines: each panel's mean, standard deviation and exact quantiles over the rows it draws."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute import boxes
from ddviz.compute.aggregate import Aggregation, aggregate
from ddviz.server.encoding import Encoding
from ddviz.server.plan import scatter_spec
from ddviz.shared.scatter import ONE_BAND, Filter, RefStat, ScatterSpec, View

N = 4000
LEVELS = ["a", "b", "c"]
PERCENTILES = [0, 0.135, 5, 50, 95, 99.865, 100]


@pytest.fixture
def frame() -> pl.DataFrame:
    """Return random rows with three Group X levels, a column whose values gather on one, a long-tailed one, and rows no panel draws."""
    rng = np.random.default_rng(7)
    lumpy = np.where(rng.random(N) < 0.9, 3.0, rng.normal(3, 1, N))
    frame = pl.DataFrame(
        {
            "x": rng.normal(10, 2, N),
            "y": rng.normal(-5, 3, N),
            "tail": rng.standard_cauchy(N),
            "lumpy": lumpy,
            "g": rng.choice(LEVELS, N),
            "color": rng.choice(["r", "s"], N),
            "keep": rng.random(N),
        }
    )
    # Rows no panel draws: a missing x or y, a missing color or Group X.
    nulls = pl.DataFrame(
        {
            "x": [None, 1.0, float("nan"), 2.0, 3.0],
            "y": [1.0, None, 2.0, float("inf"), 4.0],
            "tail": [1.0] * 5,
            "lumpy": [1.0] * 5,
            "g": ["a", "b", "c", "a", None],
            "color": ["r", "r", "s", "s", "r"],
            "keep": [0.5] * 5,
        }
    )
    no_color = nulls.head(1).with_columns(x=pl.lit(1.0), color=pl.lit(None, pl.String))
    return pl.concat([frame, nulls, no_color])


@pytest.fixture
def spec(tmp_path: Path, frame: pl.DataFrame) -> ScatterSpec:
    """Return x against y with Group X g and Color color, asking for the moments of y."""
    path = tmp_path / "rows.parquet"
    frame.write_parquet(path, row_group_size=700)
    return ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x"],
        y=["y"],
        color="color",
        row=None,
        col="g",
        width=600,
        height=300,
        hover=["x", "y"],
        ref_stats=[RefStat("y", moments=True)],
    )


def drawn(frame: pl.DataFrame, x: str = "x", y: str = "y") -> pl.DataFrame:
    """Return the rows a panel of x and y draws: both finite, with a color and a Group X level."""
    return frame.filter(
        pl.col(x).is_finite(),
        pl.col(y).is_finite(),
        pl.col("color").is_not_null(),
        pl.col("g").is_not_null(),
    )


def by_level(agg: Aggregation, x: str, y: str, role: str) -> dict[str, list]:
    """Return the statistics of a pair and role by the Group X level of their panel."""
    (pair,) = [s for s in agg.ref_stats if (s.x, s.y, s.role) == (x, y, role)]
    assert all(row == 0 for row, *_ in pair.stats)
    return {agg.levels["col"][col]: rest for _, col, *rest in pair.stats}


def test_each_panel_has_the_mean_and_deviation_of_its_rows(
    spec: ScatterSpec, frame: pl.DataFrame
) -> None:
    """n, the mean and the sample standard deviation of each panel are numpy's of its rows."""
    agg = aggregate(spec)
    found = by_level(agg, "x", "y", "y")
    assert sorted(found) == LEVELS
    rows = drawn(frame)
    for level, (n, mean, std, quantiles) in found.items():
        values = rows.filter(pl.col("g") == level)["y"].to_numpy()
        assert n == len(values)
        assert mean == pytest.approx(values.mean(), rel=1e-9)
        assert std == pytest.approx(values.std(ddof=1), rel=1e-9)
        assert quantiles == []
    # Only the column asked for: neither x nor another pair.
    assert [(s.x, s.y, s.role) for s in agg.ref_stats] == [("x", "y", "y")]


@pytest.mark.parametrize("column", ["y", "tail", "lumpy"])
@pytest.mark.parametrize("cell_rows", [boxes.CELL_ROWS, 5])
def test_quantiles_are_numpys(
    spec: ScatterSpec,
    frame: pl.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
    column: str,
    cell_rows: int,
) -> None:
    """Each percentile, from the least to the largest value, is numpy's (linear), on a long tail and on values gathered in one cell too."""
    monkeypatch.setattr(boxes, "CELL_ROWS", cell_rows)
    asked = replace(
        spec, y=[column], ref_stats=[RefStat(column, quantiles=PERCENTILES)]
    )
    found = by_level(aggregate(asked), "x", column, "y")
    rows = drawn(frame, y=column)
    for level, (n, mean, std, quantiles) in found.items():
        values = rows.filter(pl.col("g") == level)[column].to_numpy()
        assert n == len(values)
        assert (mean, std) == (None, None)
        assert [p for p, _ in quantiles] == PERCENTILES
        expected = np.percentile(values, PERCENTILES)
        assert [v for _, v in quantiles] == pytest.approx(list(expected), rel=1e-12)
        assert quantiles[0][1] == values.min()
        assert quantiles[-1][1] == values.max()


def test_rows_no_panel_draws_are_left_out(
    spec: ScatterSpec, frame: pl.DataFrame
) -> None:
    """The local filter, a missing x, y, color or Group X, and a value not positive on a log axis leave a row out."""
    asked = replace(
        spec,
        filters=[Filter("keep", range=[0.0, 0.5])],
        log_x=["x"],
        ref_stats=[RefStat("y", moments=True, quantiles=[50])],
    )
    found = by_level(aggregate(asked), "x", "y", "y")
    rows = drawn(frame).filter(pl.col("keep") <= 0.5, pl.col("x") > 0)
    for level, (n, mean, _, quantiles) in found.items():
        values = rows.filter(pl.col("g") == level)["y"].to_numpy()
        assert n == len(values)
        assert mean == pytest.approx(values.mean(), rel=1e-9)
        assert quantiles == [[50, pytest.approx(np.median(values), rel=1e-12)]]


def test_x_and_y_of_one_pair_have_their_own_statistics(
    spec: ScatterSpec, frame: pl.DataFrame
) -> None:
    """A column on X has the statistics of its values, apart from those of Y."""
    asked = replace(
        spec, ref_stats=[RefStat("x", quantiles=[5]), RefStat("y", moments=True)]
    )
    agg = aggregate(asked)
    rows = drawn(frame)
    for level, (n, mean, std, quantiles) in by_level(agg, "x", "y", "x").items():
        values = rows.filter(pl.col("g") == level)["x"].to_numpy()
        assert (n, mean, std) == (len(values), None, None)
        assert quantiles == [[5, pytest.approx(np.percentile(values, 5), rel=1e-12)]]
    assert sorted(by_level(agg, "x", "y", "y")) == LEVELS


def test_a_panel_without_rows_has_none_and_one_row_has_no_deviation(
    tmp_path: Path, spec: ScatterSpec, frame: pl.DataFrame
) -> None:
    """A second Y column with no row in one panel has no statistics there, and one with a single row its mean alone."""
    sparse = frame.with_columns(
        y2=pl.when(pl.col("g") == "a")
        .then(pl.col("y"))
        .when((pl.col("g") == "b") & (pl.int_range(pl.len()).over("g") == 0))
        .then(pl.lit(2.5))
        .otherwise(None)
    )
    path = tmp_path / "sparse.parquet"
    sparse.write_parquet(path)
    asked = replace(
        spec,
        files={c: [str(path)] for c in sparse.columns},
        y=["y", "y2"],
        ref_stats=[RefStat("y2", moments=True, quantiles=[50])],
    )
    found = by_level(aggregate(asked), "x", "y2", "y")
    assert sorted(found) == ["a", "b"]
    assert found["b"] == [1, 2.5, None, [[50, 2.5]]]


def test_a_zoom_keeps_the_statistics_and_another_filter_finds_them_again(
    spec: ScatterSpec, frame: pl.DataFrame
) -> None:
    """A view that knows the statistics draws them without finding them; one of another filter finds those of its rows."""
    stages: list[str] = []
    agg = aggregate(spec, stages.append)
    assert "ref_stats" in stages
    view = View(
        x_ranges=[[9.0, 11.0]],
        y_ranges=[[-6.0, -4.0]],
        levels=agg.all_levels,
        facets={"row": agg.levels["row"], "col": agg.levels["col"]},
        ref_stats=agg.ref_stats,
    )
    stages.clear()
    zoomed = aggregate(replace(spec, view=view), stages.append)
    assert zoomed.ref_stats == agg.ref_stats
    assert "ref_stats" not in stages
    narrowed = aggregate(
        replace(
            spec,
            view=replace(view, facets=None, ref_stats=[]),
            filters=[Filter("keep", range=[0.0, 0.3])],
        )
    )
    rows = drawn(frame).filter(pl.col("keep") <= 0.3)
    for level, (n, mean, _, _) in by_level(narrowed, "x", "y", "y").items():
        values = rows.filter(pl.col("g") == level)["y"].to_numpy()
        assert n == len(values)
        assert mean == pytest.approx(values.mean(), rel=1e-9)


def test_only_the_numeric_axis_columns_asked_for_are_found(
    spec: ScatterSpec,
) -> None:
    """A column the graph has not on X or Y, a categorical one, and one left out of ref_stats have none; the plan keeps only the numeric, not temporal, axis columns."""
    asked = replace(
        spec,
        x=["g"],
        categorical=["g"],
        col=None,
        ref_stats=[RefStat("g", moments=True), RefStat("tail", moments=True)],
    )
    assert aggregate(asked).ref_stats == []
    encoding = Encoding(x=("x", "at"), y=("y", "g"))
    numeric = {"x": True, "y": True, "at": True, "g": False, "tail": True}
    planned = scatter_spec(
        encoding,
        {c: ["f.parquet"] for c in ["x", "y", "at", "g"]},
        400,
        300,
        ["#000000"],
        numeric=numeric,
        temporal={"at": "datetime"},
        ref_stats=[
            RefStat(c, moments=True) for c in ["x", "y", "at", "g", "tail"]
        ],
    )
    assert [r.column for r in planned.ref_stats] == ["x", "y"]


def test_a_categorical_x_and_the_one_band_give_y_one_set_per_panel(
    spec: ScatterSpec, frame: pl.DataFrame
) -> None:
    """A categorical X takes the rows of every band of a panel together; so does an empty X."""
    banded = replace(spec, x=["color"], categorical=["color"], color=None)
    one_band = replace(
        spec,
        files={**spec.files, ONE_BAND: []},
        x=[ONE_BAND],
        categorical=[ONE_BAND],
        color=None,
    )
    rows = frame.filter(pl.col("y").is_finite(), pl.col("g").is_not_null())
    for graph, x, kept in [
        (banded, "color", rows.filter(pl.col("color").is_not_null())),
        (one_band, ONE_BAND, rows),
    ]:
        found = by_level(aggregate(graph), x, "y", "y")
        assert sorted(found) == LEVELS
        for level, (n, mean, _, _) in found.items():
            values = kept.filter(pl.col("g") == level)["y"].to_numpy()
            assert n == len(values)
            assert mean == pytest.approx(values.mean(), rel=1e-9)
