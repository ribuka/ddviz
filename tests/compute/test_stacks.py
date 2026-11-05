"""Tests of the points of a categorical axis: stacked where rows share their coordinates, else at the center."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute import stacks
from ddviz.compute.aggregate import COUNT, INDEX, KEY, Aggregation, aggregate
from ddviz.compute.bands import BAND
from ddviz.compute.scan import scan_columns
from ddviz.compute.selection import selection_columns, selection_filter
from ddviz.compute.stacked import ROWS
from ddviz.compute.stacks import KEYS, N
from ddviz.shared.scatter import Filter, ScatterSpec, Selection, View


def _spec(tmp_path: Path, frame: pl.DataFrame, **fields: object) -> ScatterSpec:
    """Return a spec of the columns of `frame`, written to a Parquet file, with `g` on x as a categorical axis."""
    path = tmp_path / "stacks.parquet"
    frame.write_parquet(path, row_group_size=7)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["g"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=400,
        height=300,
        hover=["g", "y"],
        categorical=["g"],
    )
    return replace(spec, **fields)


def _points(agg: Aggregation) -> pl.DataFrame:
    """Return the bins of the points: their panel, series, pixel, rows and largest row index, by row index."""
    panel, series, by, bx = agg.grid.unpack(agg.bins[KEY].to_numpy())
    return pl.DataFrame(
        {
            "panel": panel,
            "series": series,
            "bx": bx,
            "by": by,
            "n": agg.bins[COUNT].cast(pl.Int64),
            "row": agg.bins[INDEX].cast(pl.Int64),
        }
    ).sort("row")


def _center(agg: Aggregation, level: int, axis: str = "x") -> float:
    """Return the center of a level's band in pixels of a panel."""
    lo, hi = (agg.x_ranges if axis == "x" else agg.y_ranges)[0]
    bins = agg.grid.width if axis == "x" else agg.grid.height
    return (level - lo) * bins / (hi - lo)


def _value_bin(agg: Aggregation, value: float, axis: str = "y") -> int:
    """Return the pixel of a value of the numeric axis."""
    lo, hi = (agg.y_ranges if axis == "y" else agg.x_ranges)[0]
    bins = agg.grid.height if axis == "y" else agg.grid.width
    # As the numeric axis bins it (`ddviz.compute.stacks.Axis.pixel`).
    return math.floor((value - lo) * (bins / (hi - lo)))


def _capacity(agg: Aggregation, width: int) -> int:
    """Return the most points of markers `width` pixels wide that fit a stack in the middle band of x."""
    center = _center(agg, 0)
    band = BAND * agg.grid.width / (agg.x_ranges[0][1] - agg.x_ranges[0][0])
    n = 1
    while True:
        half = n / 2 * (width + 1)
        first = math.floor(center - half) - (width - 1) // 2
        last = math.floor(center + half) + (width - 1) // 2
        if first < center - band or last + 1 > center + band:
            return n
        n += 1


def test_rows_of_distinct_values_lie_at_the_center(tmp_path: Path) -> None:
    """One level of 25 distinct values: every point at the band's center, the numeric axis untouched; X and Y swapped too."""
    values = [float(v) * 1.5 for v in range(25)]
    frame = pl.DataFrame({"g": ["T1"] * 25, "y": values})
    spec = _spec(tmp_path, frame)
    agg = aggregate(spec)
    points = _points(agg)
    assert points.height == 25 and agg.pile_bins.height == 0
    assert set(points["bx"]) == {math.floor(_center(agg, 0))}
    assert points["by"].to_list() == [_value_bin(agg, v) for v in values]
    swapped = aggregate(replace(spec, x=["y"], y=["g"]))
    points = _points(swapped)
    assert set(points["by"]) == {math.floor(_center(swapped, 0, "y"))}
    assert points["bx"].to_list() == [_value_bin(swapped, v, "x") for v in values]


def test_equal_rows_stack_symmetrically_by_row_index(tmp_path: Path) -> None:
    """Two and three equal rows lie their marker plus a pixel apart around the center, the first row leftmost; a row alone stays."""
    frame = pl.DataFrame({"g": ["a"] * 6, "y": [1.0, 2.0, 1.0, 2.0, 3.0, 2.0]})
    agg = aggregate(_spec(tmp_path, frame))
    center = _center(agg, 0)
    # The default marker is a circle 5 pixels wide: 6 pixels apart.
    expected = {
        0: math.floor(center - 3),
        2: math.floor(center + 3),
        1: math.floor(center - 6),
        3: math.floor(center),
        5: math.floor(center + 6),
        4: math.floor(center),
    }
    points = _points(agg)
    assert dict(zip(points["row"], points["bx"], strict=True)) == expected
    assert points["n"].to_list() == [1] * 6


def test_values_one_float_cannot_tell_apart_do_not_stack(tmp_path: Path) -> None:
    """Neighboring floats, and integers past 2**53, stay alone at the center (in one pixel); -0.0 and 0.0 stack."""
    floats = pl.DataFrame(
        {"g": ["a"] * 4, "y": [1.0, float(np.nextafter(1.0, 2.0)), -0.0, 0.0]}
    )
    agg = aggregate(_spec(tmp_path, floats))
    points = _points(agg)
    center = math.floor(_center(agg, 0))
    # Both alone at the center: one bin of their two rows, no pile.
    assert points.filter(pl.col("row") < 2).select("bx", "n").rows() == [(center, 2)]
    assert agg.pile_bins.height == 0
    assert sorted(points.filter(pl.col("row") >= 2)["bx"]) == [
        math.floor(_center(agg, 0) - 3),
        math.floor(_center(agg, 0) + 3),
    ]
    big = pl.DataFrame({"g": ["a"] * 3, "y": [0, 2**53, 2**53 + 1]})
    agg = aggregate(_spec(tmp_path, big))
    points = _points(agg).filter(pl.col("row") > 0)
    assert points.select("bx", "n").rows() == [(math.floor(_center(agg, 0)), 2)]

    assert agg.pile_bins.height == 0


def test_two_categorical_axes_stack_in_a_grid(tmp_path: Path) -> None:
    """A pair of levels alone lies at its center; five equal rows fill a grid of three columns from the top, each row centered."""
    frame = pl.DataFrame(
        {"g": ["a"] + ["b"] * 5, "h": ["u"] + ["v"] * 5, "y": [0.0] * 6}
    )
    spec = _spec(tmp_path, frame, y=["h"], categorical=["g", "h"], hover=["g", "h"])
    agg = aggregate(spec)
    points = _points(agg)
    alone = points.row(0, named=True)
    assert (alone["bx"], alone["by"]) == (
        math.floor(_center(agg, 0)),
        math.floor(_center(agg, 0, "y")),
    )
    cx, cy = _center(agg, 1), _center(agg, 1, "y")
    expected = [(-6, 3), (0, 3), (6, 3), (-3, -3), (3, -3)]
    found = points.filter(pl.col("row") > 0)
    assert list(zip(found["bx"], found["by"], strict=True)) == [
        (math.floor(cx + dx), math.floor(cy + dy)) for dx, dy in expected
    ]


def test_facets_and_series_count_their_stacks_apart_and_together(
    tmp_path: Path,
) -> None:
    """Equal rows of two facet panels are each alone; equal rows of two series stack together."""
    frame = pl.DataFrame(
        {"g": ["a"] * 4, "y": [1.0] * 4, "f": ["p", "q", "p", "q"], "c": list("xxyz")}
    )
    agg = aggregate(_spec(tmp_path, frame, col="f", color="c"))
    points = _points(agg)
    left, right = math.floor(_center(agg, 0) - 3), math.floor(_center(agg, 0) + 3)
    # Rows 0 and 2 share panel p, rows 1 and 3 panel q, whatever their color.
    assert points["bx"].to_list() == [left, left, right, right]
    assert points["panel"].to_list() == [0, 1, 0, 1]


def test_a_stack_past_the_band_becomes_one_pile(tmp_path: Path) -> None:
    """At the capacity of the band the points stack; one more row makes a pile of all the rows, and a bigger marker lowers the capacity."""
    probe = aggregate(_spec(tmp_path, pl.DataFrame({"g": ["a"], "y": [0.0]})))
    fits = _capacity(probe, 5)
    frame = pl.DataFrame(
        {"g": ["a"] * (2 * fits + 1), "y": [1.0] * fits + [2.0] * (fits + 1)}
    )
    spec = _spec(tmp_path, frame)
    agg = aggregate(spec)
    points = _points(agg)
    assert points.height == fits
    assert points["bx"].n_unique() == fits
    assert set(points["by"]) == {_value_bin(agg, 1.0)}
    (pair,) = agg.piles
    assert pair.piles[N].to_list() == [fits + 1]
    assert agg.pile_bins[COUNT].sum() == fits + 1
    assert pair.series[ROWS].sum() == fits + 1
    bigger = aggregate(replace(spec, shape_size=9))
    assert _capacity(bigger, 9) < fits
    assert bigger.piles[0].piles[N].to_list() == [fits, fits + 1]


def test_a_zoom_turns_a_pile_into_points_and_back(tmp_path: Path) -> None:
    """Zoomed in on the level, the band is wider and the pile becomes points; the same view places them alike again."""
    probe = aggregate(_spec(tmp_path, pl.DataFrame({"g": ["a"], "y": [0.0]})))
    n = _capacity(probe, 5) + 3
    frame = pl.DataFrame({"g": ["a", "b"] * n, "y": [1.0] * (2 * n)})
    spec = _spec(tmp_path, frame)
    overview = aggregate(spec)
    assert [p.piles[N].to_list() for p in overview.piles] == [[n, n]]
    view = View(
        x_ranges=[[-0.3, 0.3]],
        y_ranges=[list(overview.y_ranges[0])],
        levels=overview.all_levels,
        facets={"row": [None], "col": [None]},
        axis_levels=overview.axis_levels,
    )
    zoomed = aggregate(replace(spec, view=view))
    assert zoomed.piles[0].piles.height == 0
    assert _points(zoomed).height == n
    again = aggregate(replace(spec, view=view))
    assert _points(again).equals(_points(zoomed))


def test_null_and_non_finite_rows_and_the_filter_leave_their_stacks(
    tmp_path: Path,
) -> None:
    """Rows not drawn count in no stack; rows the filter drops leave the rest alone."""
    frame = pl.DataFrame(
        {
            "g": ["a", "a", None, "a", "a"],
            "y": [1.0, 1.0, 1.0, float("inf"), 1.0],
            "k": [1.0, 2.0, 1.0, 1.0, 1.0],
        }
    )
    agg = aggregate(_spec(tmp_path, frame))
    assert sorted(_points(agg)["row"]) == [0, 1, 4]
    assert _points(agg)["bx"].n_unique() == 3
    kept = aggregate(_spec(tmp_path, frame, filters=[Filter("k", range=[1.5, 3.0])]))
    points = _points(kept)
    assert points["row"].to_list() == [1]
    assert points["bx"].to_list() == [math.floor(_center(kept, 0))]
    empty = aggregate(_spec(tmp_path, frame, filters=[Filter("k", range=[5.0, 6.0])]))
    assert empty.bins.height == 0 and empty.pile_bins.height == 0


def test_parts_and_sub_parts_place_the_rows_alike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counting the stacks in parts by hash, and ranking in sub-parts, changes no bin."""
    rng = np.random.default_rng(1)
    frame = pl.DataFrame(
        {
            "g": rng.choice(["a", "b", "c"], 300),
            "y": rng.integers(0, 40, 300).astype(float),
        }
    )
    spec = _spec(tmp_path, frame)
    whole = aggregate(spec)
    monkeypatch.setattr(stacks, "PART_KEYS", 7)
    monkeypatch.setattr(stacks, "PART_ROWS", 5)
    parted = aggregate(spec)
    assert parted.bins.equals(whole.bins)
    assert parted.pile_bins.equals(whole.pile_bins)
    sort = KEYS
    assert parted.piles[0].piles.sort(sort).equals(whole.piles[0].piles.sort(sort))


def _selected(spec: ScatterSpec, agg: Aggregation, selection: Selection) -> list[int]:
    """Return the rows a box selects over a drawn result, by the table's filter."""
    view = View(
        x_ranges=[list(r) for r in agg.x_ranges],
        y_ranges=[list(r) for r in agg.y_ranges],
        levels=agg.all_levels,
        facets={"row": agg.levels["row"], "col": agg.levels["col"]},
        axis_levels=agg.axis_levels,
    )
    selecting = replace(spec, view=view, selection=selection)
    columns = selection_columns(selecting)
    return (
        scan_columns({c: spec.files[c] for c in columns}, INDEX)
        .filter(*selection_filter(selecting, INDEX))
        .collect()[INDEX]
        .to_list()
    )


def test_a_box_selects_the_points_where_their_stack_puts_them(tmp_path: Path) -> None:
    """A box over the left points of a stack selects only those; a box around a pile's center selects all its rows."""
    probe = aggregate(_spec(tmp_path, pl.DataFrame({"g": ["a"], "y": [0.0]})))
    pile = _capacity(probe, 5) + 1
    frame = pl.DataFrame({"g": ["a"] * (4 + pile), "y": [1.0] * 4 + [2.0] * pile})
    spec = _spec(tmp_path, frame)
    agg = aggregate(spec)
    scale = agg.grid.width / (agg.x_ranges[0][1] - agg.x_ranges[0][0])
    left = Selection(x="g", y="y", x_range=[-0.45, -0.5 / scale], y_range=[0.9, 1.1])
    assert _selected(spec, agg, left) == [0, 1]
    right = Selection(x="g", y="y", x_range=[0.0, 0.45], y_range=[0.9, 1.1])
    assert _selected(spec, agg, right) == [2, 3]
    around = Selection(x="g", y="y", x_range=[-0.05, 0.05], y_range=[1.5, 2.5])
    assert _selected(spec, agg, around) == list(range(4, 4 + pile))
    beside = Selection(x="g", y="y", x_range=[0.1, 0.45], y_range=[1.5, 2.5])
    assert _selected(spec, agg, beside) == []
    view = View(
        x_ranges=[list(r) for r in agg.x_ranges],
        y_ranges=[list(r) for r in agg.y_ranges],
        levels=agg.all_levels,
        facets={"row": [None], "col": [None]},
        axis_levels=agg.axis_levels,
    )
    # The layer of the selected rows keeps their places among all the rows.
    layer = aggregate(replace(spec, view=view, selection=left), selection_only=True)
    assert layer.selected_rows == 2
    drawn = _points(agg).filter(pl.col("row") < 2)
    *_, bx = agg.grid.unpack(layer.selected[KEY].to_numpy())
    assert sorted(bx.tolist()) == sorted(drawn["bx"].to_list())
    assert layer.selected_piles.height == 0
    layer = aggregate(replace(spec, view=view, selection=around), selection_only=True)
    assert layer.selected.height == 0
    assert layer.selected_piles[COUNT].sum() == pile


def test_too_many_piles_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plot of more piles than the page draws fails with a message."""
    from ddviz.compute import aggregate as module

    probe = aggregate(_spec(tmp_path, pl.DataFrame({"g": ["a"], "y": [0.0]})))
    n = _capacity(probe, 5) + 1
    frame = pl.DataFrame({"g": ["a"] * (2 * n), "y": [1.0] * n + [2.0] * n})
    monkeypatch.setattr(module, "MAX_PILES", 1)
    with pytest.raises(ValueError, match="上限"):
        aggregate(_spec(tmp_path, frame))


def test_a_stack_spaces_its_points_by_its_largest_marker(tmp_path: Path) -> None:
    """With shapes of their own sizes, a stack of a small and a large shape lies the large one plus a pixel apart; one of small shapes, the small one's."""
    frame = pl.DataFrame(
        {"g": ["a"] * 4, "y": [1.0, 1.0, 2.0, 2.0], "s": ["u", "v", "u", "u"]}
    )
    spec = _spec(tmp_path, frame, overlay="s", shape_sizes={"v": 11}, shape_size=5)
    agg = aggregate(spec)
    points = _points(agg)
    center = _center(agg, 0)
    rows = dict(zip(points["row"], points["bx"], strict=True))
    # The square of size 5 is 5 pixels wide, the circle of 11 is 11 wide.
    assert rows[0] == math.floor(center - 6) and rows[1] == math.floor(center + 6)
    assert rows[2] == math.floor(center - 3) and rows[3] == math.floor(center + 3)


def test_temporal_values_stack_by_their_own_values(tmp_path: Path) -> None:
    """Datetimes a nanosecond apart stay alone; equal ones stack, and a pile of them lies at their value."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    day = base + timedelta(days=1)
    frame = pl.DataFrame(
        {
            "g": ["a"] * 4,
            "y": pl.Series([base, base, day, day], dtype=pl.Datetime("ns", "UTC")),
        }
    ).with_columns(
        pl.when(pl.int_range(pl.len()) == 3)
        .then(pl.col("y") + pl.duration(nanoseconds=1))
        .otherwise(pl.col("y"))
        .alias("y")
    )
    spec = _spec(tmp_path, frame, temporal={"y": "datetime"})
    agg = aggregate(spec)
    points = _points(agg)
    center = _center(agg, 0)
    assert sorted(points.filter(pl.col("row") < 2)["bx"]) == [
        math.floor(center - 3),
        math.floor(center + 3),
    ]
    # A nanosecond apart: each alone at the center, in one bin of two rows.
    assert points.filter(pl.col("row") >= 2).select("bx", "n").rows() == [
        (math.floor(center), 2)
    ]
    probe = aggregate(_spec(tmp_path, pl.DataFrame({"g": ["a"], "y": [0.0]})))
    n = _capacity(probe, 5) + 1
    many = pl.DataFrame(
        {
            "g": ["a"] * (n + 1),
            "y": pl.Series(
                [base] * n + [base + timedelta(days=3)], dtype=pl.Datetime("ns", "UTC")
            ),
        }
    )
    agg = aggregate(_spec(tmp_path, many, temporal={"y": "datetime"}))
    (pair,) = agg.piles
    (pile,) = pair.piles.iter_rows(named=True)
    ms = base.timestamp() * 1000

    assert pile[N] == n
    assert pile["by"] == _value_bin(agg, ms)


def test_wrapped_panels_place_their_piles_in_their_own_panel(tmp_path: Path) -> None:
    """With Wrap, a pile lies in the panel of its level, as its points would."""
    probe = aggregate(_spec(tmp_path, pl.DataFrame({"g": ["a"], "y": [0.0]})))
    n = _capacity(probe, 5) * 2
    frame = pl.DataFrame(
        {
            "g": ["a"] * (2 * n),
            "y": [1.0] * (2 * n),
            "w": ["p"] * n + ["r"] * n,
        }
    )
    spec = _spec(tmp_path, frame, col="w", wrap=True, wrap_cols=1)
    agg = aggregate(spec)
    (pair,) = agg.piles
    assert sorted(pair.piles[stacks.PANEL].to_list()) == [0, 1]
    assert agg.pile_bins[COUNT].sum() == 2 * n
    panels = {int(p) for p in agg.grid.unpack(agg.pile_bins[KEY].to_numpy())[0]}
    assert panels == {0, 1}


def test_one_categorical_column_on_both_axes_with_nulls(tmp_path: Path) -> None:
    """A column with nulls on x and y draws its rows on the diagonal, the nulls left out."""
    frame = pl.DataFrame({"g": ["a", None, "b", "a"], "y": [0.0] * 4})
    spec = _spec(tmp_path, frame, y=["g"], hover=["g"])
    agg = aggregate(spec)
    points = _points(agg)
    assert points["row"].to_list() == [0, 2, 3]
    assert agg.pile_bins.height == 0
