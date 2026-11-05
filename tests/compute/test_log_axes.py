"""Tests of the aggregation of the columns on log10 axes (`ddviz.shared.axisscale`)."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute.aggregate import COUNT, aggregate
from ddviz.compute.tasks.plot import run_plot
from ddviz.compute.tasks.plotdata import bins_table
from ddviz.server.derive import box_selection, selection_spec
from ddviz.shared.axisscale import NoPositiveValuesError
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import Filter, ScatterSpec, Smoothing, View


def _spec(tmp_path: Path, frame: pl.DataFrame, **fields: object) -> ScatterSpec:
    """Return a spec of a frame written to a file, x × y by default."""
    path = tmp_path / "log.parquet"
    frame.write_parquet(path)
    return ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        **{
            "x": ["x"],
            "y": ["y"],
            "color": None,
            "row": None,
            "col": None,
            "width": 300,
            "height": 200,
            "hover": list(frame.columns),
            **fields,
        },
    )


def _bin_x(agg: object, value: float) -> int:
    """Return the x bin of a value on the log x axis of a result."""
    lo, hi = agg.x_ranges[0]
    return math.floor((math.log10(value) - lo) * agg.grid.width / (hi - lo))


def test_powers_of_ten_lie_evenly_on_a_log_axis(tmp_path: Path) -> None:
    """1, 10 and 100 lie in bins the same number of pixels apart, along x, y or both."""
    frame = pl.DataFrame({"x": [1.0, 10.0, 100.0], "y": [1.0, 10.0, 100.0]})
    for log_x, log_y in ((["x"], []), ([], ["y"]), (["x"], ["y"])):
        agg = aggregate(_spec(tmp_path, frame, log_x=log_x, log_y=log_y))
        keys = agg.bins["__key"].to_numpy()
        _, _, by, bx = agg.grid.unpack(keys)
        for log, found in ((log_x, np.sort(bx)), (log_y, np.sort(by))):
            steps = np.diff(found)
            if log:
                assert abs(int(steps[0]) - int(steps[1])) <= 1
            else:
                # Linear: 10 lies near 1, far from 100.
                assert steps[0] * 5 < steps[1]
        assert agg.bins[COUNT].sum() == 3
    # The range holds the exponents with a margin.
    lo, hi = agg.x_ranges[0]
    assert lo < 0
    assert hi > 2
    assert _bin_x(agg, 10.0) - _bin_x(agg, 1.0) == pytest.approx(
        _bin_x(agg, 100.0) - _bin_x(agg, 10.0), abs=1
    )


def test_values_not_positive_are_left_out_of_the_log_panels_only(
    tmp_path: Path,
) -> None:
    """A row whose x is 0 or less is not drawn on its log axis, but is in a linear panel of another x; the column is flagged."""
    frame = pl.DataFrame(
        {
            "x": [-1.0, 0.0, 1.0, 10.0, None, math.inf],
            "z": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )
    spec = _spec(tmp_path, frame, x=["x", "z"], log_x=["x"])
    agg = aggregate(spec)
    panel, *_ = agg.grid.unpack(agg.bins["__key"].to_numpy())
    counts = agg.bins[COUNT].to_numpy()
    assert counts[panel == agg.axes.panel(0, 0, 0, 0)].sum() == 2
    assert counts[panel == agg.axes.panel(0, 0, 1, 0)].sum() == 6
    assert agg.nonpositive == [("x", "x")]
    # A filter without such rows clears the flag.
    kept = replace(spec, filters=[Filter("z", range=[3.0, 6.0])])
    assert aggregate(kept).nonpositive == []


def test_the_same_column_on_x_and_y_has_a_scale_each(tmp_path: Path) -> None:
    """A column on a log x and a linear y has its exponents along x only."""
    frame = pl.DataFrame({"x": [1.0, 100.0], "y": [-1.0, 2.0]})
    agg = aggregate(_spec(tmp_path, frame, x=["x"], y=["x"], log_x=["x"]))
    (x_range,), (y_range,) = agg.x_ranges, agg.y_ranges
    assert x_range[0] < 0
    assert x_range[1] > 2
    assert y_range[0] < 1 and y_range[1] > 100


def test_a_log_axis_without_a_positive_value_is_refused(tmp_path: Path) -> None:
    """The overview of a log axis whose rows have no positive value fails with the footer's message."""
    frame = pl.DataFrame({"x": [-1.0, 0.0], "y": [1.0, 2.0]})
    with pytest.raises(NoPositiveValuesError, match="X の x に正の値がない"):
        aggregate(_spec(tmp_path, frame, log_x=["x"]))


def test_a_view_whose_filter_leaves_no_positive_value_draws_no_row(
    tmp_path: Path,
) -> None:
    """A view keeps the overview's range of the log axis and draws nothing."""
    frame = pl.DataFrame({"x": [-1.0, 1.0, 10.0], "y": [1.0, 2.0, 3.0]})
    spec = _spec(tmp_path, frame, log_x=["x"])
    agg = aggregate(spec)
    view = replace(
        spec,
        filters=[Filter("y", range=[0.0, 1.5])],
        view=_view_of(agg),
    )
    found = aggregate(view)
    assert found.x_ranges == agg.x_ranges
    assert found.bins.height == 0


def _view_of(agg: object) -> View:
    """Return the view of a result over its own ranges."""
    return View(
        x_ranges=[list(r) for r in agg.x_ranges],
        y_ranges=[list(r) for r in agg.y_ranges],
        levels=agg.all_levels,
    )


@pytest.mark.parametrize(
    ("values", "kind"),
    [([5.0, 5.0], "single"), ([1e-300, 1e300], "extreme"), ([5e-324, 1e308], "edge")],
)
def test_log_ranges_stay_finite(tmp_path: Path, values: list, kind: str) -> None:
    """One value has a span of its own; tiny and huge values give exponents whose powers are positive and finite."""
    frame = pl.DataFrame({"x": values, "y": [1.0, 2.0]})
    agg = aggregate(_spec(tmp_path, frame, log_x=["x"]))
    lo, hi = agg.x_ranges[0]
    assert lo < hi, kind
    assert 0 < 10.0**lo < 10.0**hi < math.inf
    assert agg.bins[COUNT].sum() == 2


def test_box_plots_on_a_log_axis_are_of_the_positive_values(tmp_path: Path) -> None:
    """The quartiles are those of the positive values themselves, not of their log10."""
    frame = pl.DataFrame({"g": ["a"] * 6, "y": [-5.0, 0.0, 1.0, 2.0, 3.0, 4.0]})
    spec = _spec(
        tmp_path,
        frame,
        x=["g"],
        log_y=["y"],
        categorical=["g"],
        box=True,
        points=False,
    )
    (boxes,) = aggregate(spec).boxes
    (stats,) = boxes.stats
    # [row, col, level, series, n, low, q1, median, q3, high]
    assert stats[4] == 4
    assert stats[7] == pytest.approx(2.5)


def test_smoothing_lines_on_log_axes_are_fitted_over_the_values(
    tmp_path: Path,
) -> None:
    """The line of y = x over positive x is fitted on the values: its points stay on y = x."""
    xs = np.linspace(-10, 1000, 400)
    frame = pl.DataFrame({"x": xs, "y": xs})
    spec = _spec(
        tmp_path, frame, log_x=["x"], smooth=Smoothing(method="lowess", frac=0.3)
    )
    (smooths,) = aggregate(spec).smooths
    (_, _, _, line_x, line_y) = smooths.lines[0]
    assert min(line_x) > 0
    assert np.allclose(line_x, line_y, rtol=0.05, atol=1.0)


def test_a_box_on_a_log_axis_selects_the_rows_by_their_values(
    tmp_path: Path,
) -> None:
    """A box of values from 5 to 50 picks 10 and 20, and its bins lie in the result's."""
    frame = pl.DataFrame({"x": [-1.0, 1.0, 10.0, 20.0, 100.0], "y": [1.0] * 5})
    spec = _spec(tmp_path, frame, log_x=["x"])
    out = tmp_path / "plot"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    manifest = PlotManifest.read(out)
    selection = box_selection(manifest, 0, (50.0, 5.0), (0.5, 2.0))
    assert selection.x_range == pytest.approx([math.log10(5), math.log10(50)])
    agg = aggregate(selection_spec(manifest, selection), selection_only=True)
    assert agg.selected_rows == 2
    with pytest.raises(ValueError, match="positive"):
        box_selection(manifest, 0, (0.0, 5.0), (0.5, 2.0))


def test_saved_bins_of_a_log_axis_hold_values(tmp_path: Path) -> None:
    """The saved bounds are values, ascending, around each row's value; the counts are the drawn rows."""
    frame = pl.DataFrame({"x": [0.0, 1e-3, 1.0, 1e3], "y": [1.0, 2.0, 3.0, 4.0]})
    spec = _spec(tmp_path, frame, log_x=["x"])
    out = tmp_path / "plot"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    table = bins_table(out).sort("x_lo")
    assert table["count"].sum() == 3
    for value, lo, hi in zip(
        [1e-3, 1.0, 1e3], table["x_lo"], table["x_hi"], strict=True
    ):
        assert 0 < lo <= value < hi
    assert set(table.columns) >= {"x_lo", "x_hi", "y_lo", "y_hi"}
