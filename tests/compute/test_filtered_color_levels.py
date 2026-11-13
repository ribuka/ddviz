"""Tests of the color levels found among the rows of the local filter (`ScatterSpec.filters_color`)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute import aggregate as aggregate_module
from ddviz.compute.aggregate import aggregate
from ddviz.compute.tasks.plot import run_plot
from ddviz.server.figure import build_figure
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.missing import MISSING
from ddviz.shared.scatter import (
    Filter,
    FilteredColorLevelsError,
    ScatterSpec,
)

N = 1500


def _frame(levels: list[str | None] | None = None) -> pl.DataFrame:
    """Return rows whose ``g`` cycles over 150 levels ``v1`` to ``v150`` (or `levels`).

    ``n`` is the row's number, ``h`` is ``a`` for the first 30 levels of
    the cycle and ``b`` for the others, and ``k`` is the row's place in the
    cycle.
    """
    cycle = levels or [f"v{i + 1}" for i in range(150)]
    return pl.DataFrame(
        {
            "x": [float(i) for i in range(N)],
            "y": [float(i % 7) for i in range(N)],
            "g": [cycle[i % len(cycle)] for i in range(N)],
            "n": list(range(N)),
            "h": ["a" if i % len(cycle) < 30 else "b" for i in range(N)],
            "k": [i % len(cycle) for i in range(N)],
        }
    )


def _spec(tmp_path: Path, frame: pl.DataFrame, **changes: object) -> ScatterSpec:
    """Return a spec of x against y colored by ``g``."""
    path = tmp_path / "levels.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x"],
        y=["y"],
        color="g",
        row=None,
        col=None,
        width=300,
        height=200,
        hover=["x", "y", "g"],
        colors=["#000001", "#000002", "#000003"],
    )
    return replace(spec, **changes)


def _first(n: int) -> Filter:
    """Return the condition keeping the levels ``v1`` to ``v<n>`` of ``g``."""
    return Filter("g", levels=[f"v{i + 1}" for i in range(n)])


def test_the_color_levels_are_those_of_the_filter(tmp_path: Path) -> None:
    """150 levels filtered down to 10 draw those 10 in natural order; kept over every row, the 150 pass the limit."""
    spec = _spec(tmp_path, _frame(), filters=[_first(10)])
    agg = aggregate(spec)
    assert agg.levels["color"] == [f"v{i + 1}" for i in range(10)]
    assert agg.all_levels["color"] == agg.levels["color"]
    assert agg.grid.n_series == 10
    with pytest.raises(
        ValueError, match="g は 150 個で、Color・Symbol・Group・Wrap の上限は 100 個"
    ):
        aggregate(replace(spec, keep_unfiltered_color_levels=True))


def test_without_a_filter_the_levels_are_those_of_every_row(tmp_path: Path) -> None:
    """No filter: the levels of every row, as kept over every row."""
    frame = _frame([f"v{i + 1}" for i in range(12)])
    spec = _spec(tmp_path, frame)
    kept = aggregate(replace(spec, keep_unfiltered_color_levels=True))
    assert aggregate(spec).levels["color"] == kept.levels["color"]


def test_kept_levels_leave_the_filtered_out_ones_in_the_legend(tmp_path: Path) -> None:
    """Kept over every row, the 30 levels stay with 5 filtered in: the series keep their places."""
    frame = _frame([f"v{i + 1}" for i in range(30)])
    spec = _spec(
        tmp_path, frame, filters=[_first(5)], keep_unfiltered_color_levels=True
    )
    assert aggregate(spec).levels["color"] == [f"v{i + 1}" for i in range(30)]
    off = aggregate(replace(spec, keep_unfiltered_color_levels=False))
    assert off.levels["color"] == [f"v{i + 1}" for i in range(5)]


def test_exactly_the_limit_draws_and_one_more_is_refused(tmp_path: Path) -> None:
    """100 levels of the filter draw; 101 are refused with the message of the spec."""
    spec = _spec(tmp_path, _frame(), filters=[_first(100)])
    assert len(aggregate(spec).levels["color"]) == 100
    with pytest.raises(FilteredColorLevelsError) as refused:
        aggregate(replace(spec, filters=[_first(101)]))
    assert str(refused.value) == (
        "Color の水準がフィルタの後も上限の 100 個を超えるため描けない（g）。"
        "フィルタで水準を絞るか、別の列を使う"
    )


def test_the_limit_comes_from_the_spec(tmp_path: Path) -> None:
    """``max_levels`` sets the limit and its number in the message."""
    spec = _spec(tmp_path, _frame(), filters=[_first(4)], max_levels=3)
    with pytest.raises(FilteredColorLevelsError, match="上限の 3 個を超える"):
        aggregate(spec)
    assert len(aggregate(replace(spec, max_levels=4)).levels["color"]) == 4


def _with_nulls() -> pl.DataFrame:
    """Return `_frame` with ``g`` null where ``k`` is 149 (its last level)."""
    return _frame().with_columns(
        pl.when(pl.col("k") == 149).then(None).otherwise(pl.col("g")).alias("g")
    )


@pytest.mark.parametrize(
    ("kept", "null_roles", "drawn"),
    [
        (99, ["color"], 100),  # 99 levels and the missing one
        (100, [], 100),  # the missing rows not drawn: not counted
        (100, ["color"], None),  # 101 with the missing one
    ],
)
def test_the_missing_level_counts_when_drawn(
    tmp_path: Path, kept: int, null_roles: list[str], drawn: int | None
) -> None:
    """With Show null rows, the missing rows of the filter add the missing level, which counts against the limit."""
    # The filter keeps the first `kept` places of the cycle and its last, null one.
    places = [*range(kept), 149]
    spec = _spec(
        tmp_path,
        _with_nulls(),
        filters=[Filter("k", levels=[str(p) for p in places])],
        null_roles=null_roles,
    )
    if drawn is None:
        with pytest.raises(FilteredColorLevelsError):
            aggregate(spec)
        return
    levels = aggregate(spec).levels["color"]
    assert len(levels) == drawn
    assert (levels[-1] == MISSING) == bool(null_roles)


def test_missing_rows_left_out_by_the_filter_add_no_level(tmp_path: Path) -> None:
    """The missing level comes only when the rows of the filter have a null color."""
    spec = _spec(tmp_path, _with_nulls(), filters=[_first(5)], null_roles=["color"])
    assert MISSING not in aggregate(spec).levels["color"]


def test_the_empty_text_is_a_level(tmp_path: Path) -> None:
    """An empty text is one of the levels, first in natural order."""
    spec = _spec(
        tmp_path,
        _frame(["", "b", "a", "c"]),
        filters=[Filter("g", levels=["", "a"])],
    )
    assert aggregate(spec).levels["color"] == ["", "a"]


def test_no_level_left_draws_no_series(tmp_path: Path) -> None:
    """A filter that keeps no row leaves no color level: the figure has no series and no rows."""
    spec = _spec(tmp_path, _frame(), filters=[Filter("n", range=[-5.0, -1.0])])
    out = tmp_path / "task"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    manifest = PlotManifest.read(out)
    assert manifest.levels["color"] == []
    meta = build_figure(manifest)["meta"]
    assert meta["series"] == []
    assert meta["rows"] == 0


def test_every_condition_of_the_filter_counts(tmp_path: Path) -> None:
    """A categorical and a numeric condition together keep the levels of the rows that meet both."""
    spec = _spec(
        tmp_path,
        _frame(),
        filters=[Filter("h", levels=["a"]), Filter("n", range=[5.0, 40.0])],
    )
    # h is a for v1 to v30; n of 5 to 40 is in v6 to v41.
    assert aggregate(spec).levels["color"] == [f"v{i + 1}" for i in range(5, 30)]


@pytest.mark.parametrize(("role", "name"), [("symbol", "symbol"), ("col", "col")])
def test_the_same_column_on_another_role_keeps_its_limit_over_every_row(
    tmp_path: Path, role: str, name: str
) -> None:
    """``g`` on color and on symbol (or Group X) is refused by the other role's limit over every row, in its own words."""
    spec = _spec(tmp_path, _frame(), filters=[_first(10)], **{role: "g"})
    with pytest.raises(ValueError) as refused:
        aggregate(spec)
    assert not isinstance(refused.value, FilteredColorLevelsError)
    assert str(refused.value) == (
        "水準が上限を超えるため描けない（g は 150 個で、Color・Symbol・Group・Wrap の"
        "上限は 100 個）。水準はフィルタの前の行から数えるため、別の列を使う"
    )


def test_the_reading_stops_once_past_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read 100 rows at a time, the second slice passes 100 levels: no slice after it is read, and nothing is binned."""
    monkeypatch.setattr(aggregate_module, "COLOR_ROWS_PER_PASS", 100)
    read = []
    values = aggregate_module._color_values

    def counted(spec: ScatterSpec, start: int, length: int) -> pl.Series:
        read.append(start)
        return values(spec, start, length)

    def no_bins(*args: object, **kwargs: object) -> None:
        raise AssertionError("binned")

    monkeypatch.setattr(aggregate_module, "_color_values", counted)
    monkeypatch.setattr(aggregate_module, "_binned", no_bins)
    monkeypatch.setattr(aggregate_module, "stacked_bins", no_bins)
    # Every level is kept: the first slice has v1 to v100, the second v101
    # to v150 and v1 to v50.
    spec = _spec(tmp_path, _frame(), filters=[Filter("n", range=[0.0, N])])
    with pytest.raises(FilteredColorLevelsError):
        aggregate(spec)
    assert read == [0, 100]


def test_the_levels_of_slices_are_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read 100 rows at a time, the levels are those of every slice, in natural order."""
    monkeypatch.setattr(aggregate_module, "COLOR_ROWS_PER_PASS", 100)
    spec = _spec(tmp_path, _frame(), filters=[Filter("k", levels=["149", "3", "120"])])
    assert aggregate(spec).levels["color"] == ["v4", "v121", "v150"]
