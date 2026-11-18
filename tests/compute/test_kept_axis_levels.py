"""A categorical axis column of `ScatterSpec.keep_unfiltered_axis_levels` has the levels of every row, the local filter aside (Issue #281)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from ddviz.compute import aggregate as aggregate_module
from ddviz.compute.aggregate import aggregate
from ddviz.shared.scatter import Filter, ScatterSpec, View

N = 120
# cat cycles a, b, c; the rows of a (i % 3 == 0) have g0 and g3 alone. The
# levels of g sort in natural order: g2 before g10.
FRAME = pl.DataFrame(
    {
        "cat": [["a", "b", "c"][i % 3] for i in range(N)],
        "g": [["g0", "g1", "g2", "g10", "g4", "g5"][i % 6] for i in range(N)],
        "v": [float(i) for i in range(N)],
    }
)
LEVELS = ["g0", "g1", "g2", "g4", "g5", "g10"]
CAT_A = [Filter("cat", levels=["a"])]


def _spec(tmp_path: Path, **fields: object) -> ScatterSpec:
    """Return a spec of the categorical g × v over `FRAME`, with the fields given."""
    path = tmp_path / "kept.parquet"
    if not path.exists():
        FRAME.write_parquet(path)
    return ScatterSpec(
        **{
            "files": {c: [str(path)] for c in FRAME.columns},
            "x": ["g"],
            "y": ["v"],
            "color": None,
            "row": None,
            "col": None,
            "width": 200,
            "height": 200,
            "hover": ["v"],
            "categorical": ["g"],
            **fields,
        }
    )


def test_a_kept_axis_has_the_levels_of_every_row(tmp_path: Path) -> None:
    """Filtered to cat a, g keeps its 6 levels in natural order, those without rows as empty bands; without the setting it has g0 and g10."""
    off = aggregate(_spec(tmp_path, filters=CAT_A))
    assert off.axis_levels["g"] == ["g0", "g10"]
    on = aggregate(_spec(tmp_path, filters=CAT_A, keep_unfiltered_axis_levels=["g"]))
    assert on.axis_levels["g"] == LEVELS
    assert on.x_auto == on.x_ranges == [(-0.5, 5.5)]
    assert on.bins["__n"].sum() == N // 3


def test_a_kept_axis_column_is_not_read_among_the_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overview finds the levels of a kept axis column in its pass over every row, not among the rows of the filter."""
    read = []
    among = aggregate_module._levels_among_filter

    def counted(spec: ScatterSpec, column: str, limit: int) -> object:
        read.append(column)
        return among(spec, column, limit)

    monkeypatch.setattr(aggregate_module, "_levels_among_filter", counted)
    aggregate(_spec(tmp_path, filters=CAT_A, keep_unfiltered_axis_levels=["g"]))
    assert read == []


def test_the_limit_of_a_kept_axis_counts_every_row(tmp_path: Path) -> None:
    """``max_axis_levels`` 4 refuses the 6 levels of every row of a kept axis, with the advice to turn the setting off; the levels of the filter fit without it."""
    with pytest.raises(ValueError) as refused:
        aggregate(
            _spec(
                tmp_path,
                filters=CAT_A,
                max_axis_levels=4,
                keep_unfiltered_axis_levels=["g"],
            )
        )
    assert str(refused.value) == (
        "水準が上限を超えるため描けない（g は 6 個で、X・Y のカテゴリの軸の上限は 4 個）。"
        "水準はフィルタの前の行から数える設定のため、別の列を使うか、"
        "「フィルタで除外された水準も軸に残す」を外す"
    )
    agg = aggregate(_spec(tmp_path, filters=CAT_A, max_axis_levels=4))
    assert agg.axis_levels["g"] == ["g0", "g10"]


def test_without_a_filter_the_advice_names_the_setting(tmp_path: Path) -> None:
    """Without a filter too, a kept axis past its limit is told to turn the setting off; an axis without it, to filter."""
    with pytest.raises(ValueError, match="「フィルタで除外された水準も軸に残す」を外す"):
        aggregate(_spec(tmp_path, max_axis_levels=4, keep_unfiltered_axis_levels=["g"]))
    with pytest.raises(ValueError, match="フィルタで水準を絞るか、別の列を使う"):
        aggregate(_spec(tmp_path, max_axis_levels=4))


def test_a_view_of_another_filter_keeps_the_levels_of_a_kept_axis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A view of another filter asked to find the levels of a kept axis keeps those of every row it is given, and reads none among its filter."""
    kept = {"keep_unfiltered_axis_levels": ["g"]}
    whole = aggregate(_spec(tmp_path, filters=CAT_A, **kept))
    read = []
    among = aggregate_module._levels_among_filter

    def counted(spec: ScatterSpec, column: str, limit: int) -> object:
        read.append(column)
        return among(spec, column, limit)

    monkeypatch.setattr(aggregate_module, "_levels_among_filter", counted)
    view = View(
        x_ranges=[[1.5, 3.5]],
        y_ranges=[None],
        levels=whole.all_levels,
        cuts=whole.cuts,
        axis_levels=whole.axis_levels,
        find_axis_levels=["g"],
        range_levels={"g": LEVELS},
    )
    agg = aggregate(
        _spec(tmp_path, filters=[Filter("cat", levels=["b"])], view=view, **kept)
    )
    assert read == []
    assert agg.axis_levels["g"] == LEVELS
    # The range is of the same levels: it stays.
    assert agg.x_ranges == [(1.5, 3.5)]
