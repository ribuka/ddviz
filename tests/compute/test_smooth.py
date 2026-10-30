"""Tests of the smoothing lines: the three fits, and the lines of a scatter plot's aggregation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute.aggregate import aggregate
from ddviz.compute.smooth import SMOOTH_BINS, fit
from ddviz.shared.scatter import Filter, ScatterSpec, Selection, Smoothing, View


@pytest.fixture
def noisy() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return 100 strictly increasing x, a noisy sine at them, and weights."""
    rng = np.random.default_rng(3)
    x = np.sort(rng.uniform(0, 10, 100))
    y = np.sin(x) + rng.normal(0, 0.3, x.size)
    w = rng.integers(1, 50, x.size).astype(float)
    return x, y, w


def test_csaps_runs_from_the_least_squares_line_to_the_points(
    noisy: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """A p of 0 is the weighted least-squares line, a p of 1 goes through the points."""
    x, y, w = noisy
    line = fit(x, y, w, Smoothing("csaps", p=0))
    slope, intercept = np.polyfit(x, y, 1, w=np.sqrt(w))
    np.testing.assert_allclose(line, slope * x + intercept, atol=1e-6)
    np.testing.assert_allclose(fit(x, y, w, Smoothing("csaps", p=1)), y, atol=1e-6)


@pytest.mark.parametrize(
    "smoothing",
    [Smoothing("gcv"), Smoothing("csaps"), Smoothing("csaps", p=0.99)],
    ids=["gcv", "csaps-auto", "csaps-p"],
)
def test_splines_ignore_the_units_of_x_and_of_the_weights(
    noisy: tuple[np.ndarray, np.ndarray, np.ndarray], smoothing: Smoothing
) -> None:
    """Shifting and scaling x, or scaling the weights, keeps the line."""
    x, y, w = noisy
    line = fit(x, y, w, smoothing)
    np.testing.assert_allclose(fit(x * 1e4 - 7, y, w * 1e3, smoothing), line, atol=1e-6)


def test_gcv_finds_the_curve_under_the_noise(
    noisy: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """The GCV spline is much nearer the sine than the noisy points, and smoother."""
    x, y, w = noisy
    line = fit(x, y, np.ones_like(w), Smoothing("gcv"))
    assert np.abs(line - np.sin(x)).mean() < 0.4 * np.abs(y - np.sin(x)).mean()
    assert np.abs(np.diff(line, 2)).sum() < 0.2 * np.abs(np.diff(y, 2)).sum()


def test_lowess_keeps_a_straight_line_and_weighs_the_points(
    noisy: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """A straight line stays as it is; a heavy point pulls the line to it."""
    x, _, w = noisy
    for frac in (0.1, 2 / 3, 1.0):
        line = fit(x, 2 * x + 1, w, Smoothing("lowess", frac=frac))
        np.testing.assert_allclose(line, 2 * x + 1, atol=1e-9)
    y = np.zeros_like(x)
    y[50] = 1.0
    light = fit(x, y, np.ones_like(x), Smoothing("lowess", frac=0.2))
    heavy = np.ones_like(x)
    heavy[50] = 100.0
    assert fit(x, y, heavy, Smoothing("lowess", frac=0.2))[50] > light[50] + 0.3


@pytest.mark.parametrize("method", ["gcv", "csaps", "lowess"])
def test_two_points_are_their_own_line(method: str) -> None:
    """With fewer than three points, the line goes through them."""
    line = fit(
        np.array([0.0, 1.0]), np.array([3.0, 5.0]), np.ones(2), Smoothing(method)
    )
    assert line.tolist() == [3.0, 5.0]


@pytest.fixture
def smooth_spec(scatter_spec: ScatterSpec) -> ScatterSpec:
    """Return `scatter_spec` with smoothing lines and no points."""
    return replace(scatter_spec, points=False, smooth=Smoothing())


def test_lines_of_each_facet_cell_and_series(
    smooth_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A line per facet cell and series, through the mean x of its bins; without points, no bin."""
    agg = aggregate(smooth_spec)
    assert agg.bins.height == 0
    (pair,) = agg.smooths
    assert (pair.x, pair.y) == ("x", "y")
    assert sorted((r, c, s) for r, c, s, _, _ in pair.lines) == [
        (0, c, s) for c in range(2) for s in range(3)
    ]
    valid = scatter_frame.filter(pl.col("x").is_finite(), pl.col("color").is_not_null())
    ((lo, hi),) = agg.x_ranges
    for _, col, series, xs, ys in pair.lines:
        rows = valid.filter(
            pl.col("facet") == ["p", "q"][col],
            pl.col("color") == ["a", "b", "c"][series],
        )
        bins = np.clip(
            np.floor((rows["x"].to_numpy() - lo) * SMOOTH_BINS / (hi - lo)),
            0,
            SMOOTH_BINS - 1,
        )
        means = (
            pl.DataFrame({"b": bins, "x": rows["x"]})
            .group_by("b")
            .agg(pl.col("x").mean())
            .sort("b")
        )
        np.testing.assert_allclose(xs, means["x"].to_numpy())
        assert len(ys) == len(xs)


def test_a_view_keeps_the_lines_and_another_filter_fits_them_again(
    smooth_spec: ScatterSpec,
) -> None:
    """A zoom draws the overview's lines; a filter fits lines to the rows it keeps."""
    agg = aggregate(smooth_spec)
    view = View(
        x_ranges=[[0.0, 1.0]],
        y_ranges=[list(r) for r in agg.y_ranges],
        levels=agg.all_levels,
        facets={"row": agg.levels["row"], "col": agg.levels["col"]},
        smooths=agg.smooths,
    )
    assert aggregate(replace(smooth_spec, view=view)).smooths == agg.smooths
    narrowed = aggregate(
        replace(
            smooth_spec,
            view=replace(view, facets=None, smooths=[]),
            filters=[Filter("x", range=[0.0, 5.0])],
        )
    )
    xs = [x for line in narrowed.smooths[0].lines for x in line[3]]
    assert min(xs) >= 0


def test_points_and_lines_draw_every_row(smooth_spec: ScatterSpec) -> None:
    """With points, the lines are drawn over every row's point."""
    agg = aggregate(replace(smooth_spec, points=True))
    assert agg.bins["__n"].sum() == 2000
    assert len(agg.smooths[0].lines) == 6


def test_a_selection_without_points_takes_the_rows_in_the_box(
    smooth_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """Without points, a box selects the rows whose x and y are in it."""
    agg = aggregate(smooth_spec)
    view = View(
        x_ranges=[list(r) for r in agg.x_ranges],
        y_ranges=[list(r) for r in agg.y_ranges],
        levels=agg.all_levels,
        facets={"row": agg.levels["row"], "col": agg.levels["col"]},
        smooths=agg.smooths,
    )
    selection = Selection("x", "y", [0.0, 9.0], [-9.0, 9.0], col="p")
    selected = aggregate(
        replace(smooth_spec, view=view, selection=selection), selection_only=True
    )
    expected = scatter_frame.filter(
        pl.col("x").is_between(0, 9),
        pl.col("color").is_not_null(),
        pl.col("facet") == "p",
    ).height
    assert selected.selected_rows == expected
    assert selected.selected.height == 0


@pytest.mark.parametrize(
    "smoothing",
    [Smoothing("gcv"), Smoothing("csaps"), Smoothing("csaps", p=0.5)],
    ids=["gcv", "csaps-auto", "csaps-p"],
)
@pytest.mark.parametrize(
    ("x", "w"),
    [
        (np.array([0, 0.4999999999, 0.5000000001, 1]), np.ones(4)),
        (np.r_[np.linspace(0, 0.5, 30), 0.5 + 1e-7, np.linspace(0.6, 1, 30)], None),
        (np.linspace(0, 1, 128), np.r_[1.0, np.full(126, 1e8), 1.0]),
    ],
    ids=["close-pair", "close-in-many", "tiny-weights"],
)
def test_splines_keep_a_straight_line(
    x: np.ndarray, w: np.ndarray | None, smoothing: Smoothing
) -> None:
    """A straight line has no roughness and no residual: the splines keep it, even with points almost together or weights far apart."""
    w = np.ones_like(x) if w is None else w
    line = fit(x, 2 * x + 1, w, smoothing)
    np.testing.assert_allclose(line, 2 * x + 1, atol=1e-6)


def test_bins_on_either_side_of_a_border_keep_a_straight_line(
    tmp_path: Path,
) -> None:
    """Rows a hair apart across a bin border are two bins whose line is still the rows' straight line."""
    x = [0.0, 0.4999999999, 0.5000000001, 1.0]
    path = tmp_path / "line.parquet"
    pl.DataFrame({"x": x, "y": [2 * v + 1 for v in x]}).write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in ["x", "y"]},
        x=["x"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=400,
        height=300,
        hover=["x", "y"],
        smooth=Smoothing("csaps", p=0.5),
    )
    ((_, _, _, xs, ys),) = aggregate(spec).smooths[0].lines
    assert len(xs) == 4
    np.testing.assert_allclose(ys, [2 * v + 1 for v in xs], atol=1e-6)
