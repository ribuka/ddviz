"""The color scale of a numeric color column (a gradient's range, the breaks of its intervals) follows the rows of the local filter (Issue #264)."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute import aggregate as aggregate_module
from ddviz.compute.aggregate import COUNT, Aggregation, aggregate
from ddviz.compute.cuts import cut_labels
from ddviz.shared.missing import MISSING
from ddviz.shared.scatter import Binning, Filter, ScatterSpec, View

# c is 0, 10, ..., 100 at x 0..10; then null, NaN, inf and -inf at x 11..14.
# The y of c = 20 is missing.
FRAME = pl.DataFrame(
    {
        "x": [float(i) for i in range(15)],
        "y": [1.0, 1.0, None, *[1.0] * 12],
        "c": [
            *[10.0 * i for i in range(11)],
            None,
            float("nan"),
            float("inf"),
            float("-inf"),
        ],
        "g": ["a", "b"] * 7 + ["a"],
    }
)


def _spec(tmp_path: Path, frame: pl.DataFrame = FRAME, **fields: object) -> ScatterSpec:
    """Return a spec of x × y colored by c as a gradient, over a frame written to a file."""
    path = tmp_path / "scale.parquet"
    frame.write_parquet(path)
    return ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        **{
            "x": ["x"],
            "y": ["y"],
            "color": "c",
            "row": None,
            "col": None,
            "width": 100,
            "height": 100,
            "hover": ["x"],
            "gradient": True,
            **fields,
        },
    )


def _binned(tmp_path: Path, n: int, by: str, **fields: object) -> ScatterSpec:
    """Return the spec of c cut into `n` intervals `by` values or rows."""
    return _spec(tmp_path, gradient=False, binned={"color": Binning(n, by)}, **fields)


def _view(agg: Aggregation, **fields: object) -> View:
    """Return the view of a result's levels, cuts and color range over its ranges."""
    return View(
        **{
            "x_ranges": [list(r) for r in agg.x_ranges],
            "y_ranges": [list(r) for r in agg.y_ranges],
            "levels": agg.all_levels,
            "axis_levels": agg.axis_levels,
            "cuts": agg.cuts,
            "color_range": None if agg.color_range is None else list(agg.color_range),
            **fields,
        }
    )


C_10_20 = [Filter("c", range=[10.0, 20.0])]


def test_a_gradient_spans_the_rows_of_the_filter(tmp_path: Path) -> None:
    """A c of 0 to 100 filtered to 10..20 colors over 10 to 20, the filter's ends included; without the filter over 0 to 100."""
    agg = aggregate(_spec(tmp_path, filters=C_10_20))
    assert agg.color_range == (10.0, 20.0)
    whole = aggregate(_spec(tmp_path))
    assert whole.color_range == (0.0, 100.0)


def test_intervals_of_values_cut_the_rows_of_the_filter(tmp_path: Path) -> None:
    """Two intervals of equal width over the filtered 10..20 break at 10, 15 and 20, and name the levels so."""
    agg = aggregate(_binned(tmp_path, 2, "values", filters=C_10_20))
    assert agg.cuts["color"] == {"breaks": [10.0, 15.0, 20.0], "values": False}
    assert agg.all_levels["color"] == cut_labels(agg.cuts["color"])
    assert agg.levels["color"] == agg.all_levels["color"]
    whole = aggregate(_binned(tmp_path, 2, "values"))
    assert whole.cuts["color"]["breaks"] == [0.0, 50.0, 100.0]


def test_intervals_of_rows_cut_at_the_quantiles_of_the_filter(tmp_path: Path) -> None:
    """Two intervals of as many rows over the filtered 10, 20, 30, 40, 50 break at its quantiles 10, 30 and 50."""
    filters = [Filter("c", range=[10.0, 50.0])]
    agg = aggregate(_binned(tmp_path, 2, "rows", filters=filters))
    assert agg.cuts["color"] == {"breaks": [10.0, 30.0, 50.0], "values": False}
    whole = aggregate(_binned(tmp_path, 2, "rows"))
    assert whole.cuts["color"]["breaks"] == [0.0, 50.0, 100.0]


def test_the_filters_meet_all_together(tmp_path: Path) -> None:
    """A range of c and a level of g keep the rows of both: c 0, 20, 40."""
    filters = [Filter("c", range=[0.0, 50.0]), Filter("g", levels=["a"])]
    agg = aggregate(_spec(tmp_path, filters=filters))
    assert agg.color_range == (0.0, 40.0)


def test_null_nan_and_inf_take_no_part(tmp_path: Path) -> None:
    """The rows of x 9..14 hold c 90, 100, null, NaN, inf and -inf: the scale spans 90 to 100."""
    filters = [Filter("x", range=[9.0, 14.0])]
    assert aggregate(_spec(tmp_path, filters=filters)).color_range == (90.0, 100.0)
    binned = aggregate(_binned(tmp_path, 2, "values", filters=filters))
    assert binned.cuts["color"]["breaks"] == [90.0, 95.0, 100.0]


def test_a_filter_without_a_finite_color_takes_every_row(tmp_path: Path) -> None:
    """The rows of x 11..14 have no finite c: the scale is that of every row, as is a view's of that filter."""
    filters = [Filter("x", range=[11.0, 14.0])]
    agg = aggregate(_spec(tmp_path, filters=filters))
    assert agg.color_range == (0.0, 100.0)
    binned = aggregate(_binned(tmp_path, 2, "values", filters=filters))
    assert binned.cuts["color"]["breaks"] == [0.0, 50.0, 100.0]
    # A view of that filter, from a result of another, finds every row's.
    other = aggregate(_spec(tmp_path, filters=C_10_20))
    view = _view(other, find_color_scale=True)
    again = aggregate(_spec(tmp_path, filters=filters, view=view))
    assert again.color_range == (0.0, 100.0)


def test_a_missing_other_role_does_not_narrow_the_scale(tmp_path: Path) -> None:
    """The row of c = 20 has no y and is not drawn, but its c is of the scale."""
    agg = aggregate(_spec(tmp_path, filters=C_10_20))
    assert agg.color_range == (10.0, 20.0)
    assert agg.bins[COUNT].sum() == 1


def test_the_missing_level_follows_the_rows_of_the_filter(tmp_path: Path) -> None:
    """A color drawing its null rows has the missing level after the intervals of the filter while its rows have a null value, and none when they have none."""
    with_nulls = [Filter("c", range=[10.0, 20.0], nulls=True)]
    agg = aggregate(
        _binned(tmp_path, 2, "values", filters=with_nulls, null_roles=["color"])
    )
    assert agg.all_levels["color"] == [*cut_labels(agg.cuts["color"]), MISSING]
    agg = aggregate(
        _binned(tmp_path, 2, "values", filters=C_10_20, null_roles=["color"])
    )
    assert agg.all_levels["color"] == cut_labels(agg.cuts["color"])


def test_a_temporal_color_spans_the_rows_of_the_filter(tmp_path: Path) -> None:
    """A datetime color filtered to its 2nd and 3rd hours spans those, in the units of every row's."""
    start = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    frame = pl.DataFrame(
        {
            "x": [0.0, 1.0, 2.0, 3.0],
            "y": [1.0, 1.0, 1.0, 1.0],
            "c": [start + dt.timedelta(hours=h) for h in range(4)],
        }
    )
    hour = 3_600_000.0
    first = start.timestamp() * 1000
    filters = [Filter("c", range=[first + hour, first + 2 * hour])]
    spec = _spec(tmp_path, frame, filters=filters, temporal={"c": "datetime"})
    agg = aggregate(spec)
    whole = aggregate(replace(spec, filters=[]))
    lo, hi = whole.color_range
    step = (hi - lo) / 3
    assert agg.color_range == pytest.approx((lo + step, lo + 2 * step))


def test_a_view_finds_the_scale_of_its_filter_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A view of the same filter (a zoom, a size, a selection) keeps the scale it is given; one of another filter finds it once; one given a scale kept uses it."""
    calls = []
    found = aggregate_module._found_color_scale

    def counted(*args: object, **kwargs: object) -> object:
        calls.append(kwargs.get("filtered"))
        return found(*args, **kwargs)

    monkeypatch.setattr(aggregate_module, "_found_color_scale", counted)
    spec = _binned(tmp_path, 2, "values")
    overview = aggregate(spec)
    # Without a filter, the overview's every row is the scale: no pass more.
    assert calls == []
    zoomed = replace(spec, view=_view(overview, x_ranges=[[0.0, 5.0]]))
    assert aggregate(zoomed).cuts["color"] == overview.cuts["color"]
    assert calls == []
    filtered = replace(
        spec, filters=C_10_20, view=_view(overview, find_color_scale=True)
    )
    stages = []
    agg = aggregate(filtered, stages.append)
    assert calls == [True]
    assert "scale" in stages
    assert agg.cuts["color"]["breaks"] == [10.0, 15.0, 20.0]
    assert agg.all_levels["color"] == cut_labels(agg.cuts["color"])
    calls.clear()
    # The next view of that filter knows the scale and its levels' names.
    known = replace(filtered, view=_view(agg))
    again = aggregate(known)
    assert calls == []
    assert again.cuts["color"] == agg.cuts["color"]
    assert again.all_levels["color"] == agg.all_levels["color"]
    # A scale kept by the page is drawn as it is, with no pass.
    kept = {"breaks": [0.0, 50.0, 100.0], "values": False}
    frozen = replace(filtered, color_scale=kept)
    held = aggregate(frozen)
    assert calls == []
    assert held.cuts["color"] == kept
    assert held.all_levels["color"] == overview.all_levels["color"]


def test_an_overview_draws_the_scale_kept(tmp_path: Path) -> None:
    """The overview of a filter with a gradient's range kept draws over it, not over the filter's."""
    spec = _spec(tmp_path, filters=C_10_20, color_scale={"range": [0.0, 100.0]})
    assert aggregate(spec).color_range == (0.0, 100.0)
