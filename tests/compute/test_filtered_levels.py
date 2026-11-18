"""Whatever the plot draws follows the rows of the local filter: the levels of the categorical axes and roles, and the missing levels (`ddviz.compute.aggregate._found_levels`)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute import aggregate as aggregate_module
from ddviz.compute.aggregate import aggregate
from ddviz.server.plan import FACET_BINS
from ddviz.shared.missing import MISSING
from ddviz.shared.scatter import (
    Binning,
    Filter,
    FilteredLevelsError,
    ScatterSpec,
    View,
)

N = 120
# cat cycles a, b, c; the rows of a (i % 3 == 0) have cx x0 and x3 only, s
# p or null, and every cy. h is null where i % 5 == 0.
FRAME = pl.DataFrame(
    {
        "cat": [["a", "b", "c"][i % 3] for i in range(N)],
        "cx": [f"x{i % 6}" for i in range(N)],
        "cy": [f"y{i % 4}" for i in range(N)],
        "v": [float(i) for i in range(N)],
        "s": [["p", "q", "r"][i % 3] if i % 7 else None for i in range(N)],
        "h": [None if i % 5 == 0 else float(i) for i in range(N)],
        "f": [f"f{i % 6}" for i in range(N)],
    }
)
CAT_A = [Filter("cat", levels=["a"])]
# No row passes.
NONE = [Filter("v", range=[-5.0, -1.0])]
BINNING = Binning(FACET_BINS, "rows", values_up_to=FACET_BINS)


def _spec(tmp_path: Path, **fields: object) -> ScatterSpec:
    """Return a spec of v × v over `FRAME`, with the fields given."""
    path = tmp_path / "levels.parquet"
    if not path.exists():
        FRAME.write_parquet(path)
    return ScatterSpec(
        **{
            "files": {c: [str(path)] for c in FRAME.columns},
            "x": ["v"],
            "y": ["v"],
            "color": None,
            "row": None,
            "col": None,
            "width": 200,
            "height": 200,
            "hover": ["v"],
            **fields,
        }
    )


def _axes(tmp_path: Path, **fields: object) -> ScatterSpec:
    """Return a spec of the categorical cx × cy."""
    return _spec(tmp_path, x=["cx"], y=["cy"], categorical=["cx", "cy"], **fields)


def test_a_categorical_axis_has_the_levels_of_the_filter(tmp_path: Path) -> None:
    """Filtered to cat a, x has the bands of x0 and x3 alone, and spans them; y keeps its 4, which those rows all have."""
    whole = aggregate(_axes(tmp_path))
    assert whole.axis_levels["cx"] == [f"x{i}" for i in range(6)]
    agg = aggregate(_axes(tmp_path, filters=CAT_A))
    assert agg.axis_levels == {"cx": ["x0", "x3"], "cy": ["y0", "y1", "y2", "y3"]}
    assert agg.x_auto == agg.x_ranges == [(-0.5, 1.5)]
    assert agg.y_auto == [(-0.5, 3.5)]
    assert agg.bins["__n"].sum() == N // 3


def test_a_filter_without_rows_leaves_an_axis_without_levels(tmp_path: Path) -> None:
    """A filter that keeps no row leaves no band, and the axis spans one."""
    agg = aggregate(_axes(tmp_path, filters=NONE))
    assert agg.axis_levels == {"cx": [], "cy": []}
    assert agg.x_auto == [(-0.5, 0.5)]


def test_the_axis_limit_is_of_the_rows_of_the_filter(tmp_path: Path) -> None:
    """``max_axis_levels`` 4 refuses the 6 levels of every row, and draws the 2 of the filter; 3 refuses the 4 of cy among them."""
    with pytest.raises(ValueError, match="cx は 6 個"):
        aggregate(_axes(tmp_path, max_axis_levels=4))
    agg = aggregate(_axes(tmp_path, filters=CAT_A, max_axis_levels=4))
    assert agg.axis_levels["cx"] == ["x0", "x3"]
    with pytest.raises(FilteredLevelsError) as refused:
        aggregate(_axes(tmp_path, filters=CAT_A, max_axis_levels=3))
    assert str(refused.value) == (
        "水準がフィルタの後も上限を超えるため描けない（X・Y のカテゴリの軸の cy は"
        "上限 3 個）。フィルタで水準を絞るか、別の列を使う"
    )


def test_a_symbol_has_the_levels_of_the_filter(tmp_path: Path) -> None:
    """Filtered to cat a, the symbol has p and its missing level, not q and r of every row."""
    spec = _spec(tmp_path, symbol="s", null_roles=["symbol"], filters=CAT_A)
    assert aggregate(spec).levels["symbol"] == ["p", MISSING]
    assert aggregate(replace(spec, filters=[])).levels["symbol"] == [
        "p",
        "q",
        "r",
        MISSING,
    ]


def test_the_symbol_limit_is_of_the_rows_of_the_filter(tmp_path: Path) -> None:
    """``max_levels`` 3 refuses the 6 levels of f over every row, and draws the 2 of the filter."""
    with pytest.raises(ValueError, match="f は 6 個"):
        aggregate(_spec(tmp_path, symbol="f", max_levels=3))
    agg = aggregate(_spec(tmp_path, symbol="f", max_levels=3, filters=CAT_A))
    assert agg.levels["symbol"] == ["f0", "f3"]


@pytest.mark.parametrize("role", ["row", "col"])
def test_the_facet_levels_are_those_of_the_filter(tmp_path: Path, role: str) -> None:
    """Filtered to cat a, a facet has the levels f0 and f3, all of them as drawn."""
    agg = aggregate(_spec(tmp_path, filters=CAT_A, **{role: "f"}))
    assert agg.all_levels[role] == agg.levels[role] == ["f0", "f3"]


def test_a_filter_without_rows_keeps_the_panels_of_every_row(tmp_path: Path) -> None:
    """A filter that keeps no row keeps the facet levels of every row, empty panels, and leaves no symbol level."""
    agg = aggregate(_spec(tmp_path, filters=NONE, col="f", symbol="s"))
    assert agg.levels["col"] == [f"f{i}" for i in range(6)]
    assert agg.levels["symbol"] == []
    assert agg.grid.n_panels == 6


@pytest.mark.parametrize(
    ("fields", "role"),
    [
        ({"color": "h", "gradient": True}, "color"),
        ({"color": "h", "binned": {"color": BINNING}}, "color"),
        ({"symbol": "h", "binned": {"symbol": BINNING}}, "symbol"),
    ],
)
def test_a_numeric_role_has_the_missing_level_of_the_filter(
    tmp_path: Path, fields: dict, role: str
) -> None:
    """A numeric role drawing its missing rows has the missing level while the rows of the filter have a null value, and none when they have none."""
    null_roles = [role]
    assert (
        aggregate(_spec(tmp_path, null_roles=null_roles, **fields)).levels[role][-1]
        == MISSING
    )
    without = [Filter("h", range=[0.0, 200.0])]
    levels = aggregate(
        _spec(tmp_path, null_roles=null_roles, filters=without, **fields)
    ).levels[role]
    assert MISSING not in levels


def test_a_view_of_another_filter_finds_the_levels_it_is_asked_for(
    tmp_path: Path,
) -> None:
    """A view asked to find the levels of the symbol and of the axis finds those of its filter; one that knows them reads nothing."""
    spec = _spec(tmp_path, x=["cx"], categorical=["cx"], symbol="s")
    whole = aggregate(spec)
    find = View(
        x_ranges=[None],
        y_ranges=[None],
        levels=whole.all_levels,
        cuts=whole.cuts,
        axis_levels={},
        find_levels=["symbol"],
        find_axis_levels=["cx"],
    )
    agg = aggregate(
        _spec(
            tmp_path, x=["cx"], categorical=["cx"], symbol="s", filters=CAT_A, view=find
        )
    )
    assert agg.axis_levels == {"cx": ["x0", "x3"]}
    assert agg.levels["symbol"] == ["p"]
    assert agg.x_ranges[0] == (-0.5, 1.5)


def test_a_view_that_knows_the_levels_reads_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A view given the levels of its filter does not look for them again."""
    spec = _spec(tmp_path, x=["cx"], categorical=["cx"], symbol="s", filters=CAT_A)
    whole = aggregate(spec)
    read = []
    among = aggregate_module._levels_among_filter

    def counted(spec: ScatterSpec, column: str, limit: int) -> object:
        read.append(column)
        return among(spec, column, limit)

    monkeypatch.setattr(aggregate_module, "_levels_among_filter", counted)
    known = View(
        x_ranges=[None],
        y_ranges=[None],
        levels=whole.all_levels,
        cuts=whole.cuts,
        axis_levels=whole.axis_levels,
    )
    agg = aggregate(
        _spec(
            tmp_path,
            x=["cx"],
            categorical=["cx"],
            symbol="s",
            filters=CAT_A,
            view=known,
        )
    )
    assert read == []
    assert agg.axis_levels == whole.axis_levels
    assert agg.levels["symbol"] == whole.levels["symbol"]
