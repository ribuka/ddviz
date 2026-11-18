"""A categorical symbol column with `ScatterSpec.keep_unfiltered_symbol_levels` has the levels of every row, the local filter aside (Issue #282)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute.aggregate import aggregate
from ddviz.shared.missing import MISSING
from ddviz.shared.scatter import Filter, ScatterSpec

N = 120
CAT_A = [Filter("c", levels=["a"])]


def _spec(tmp_path: Path, **changes: object) -> ScatterSpec:
    """Return a spec of x against y with the symbol ``s``.

    The rows of ``c`` = ``a`` have ``s`` ``p`` or ``q``; those of ``b``
    have ``r`` or a missing value.
    """
    frame = pl.DataFrame(
        {
            "x": [float(i) for i in range(N)],
            "y": [float(i % 5) for i in range(N)],
            "c": ["a" if i % 2 == 0 else "b" for i in range(N)],
            "s": [
                ("p" if i % 4 == 0 else "q") if i % 2 == 0 else ("r" if i % 3 else None)
                for i in range(N)
            ],
        }
    )
    path = tmp_path / "symbols.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=300,
        height=200,
        hover=["x", "y", "s"],
        symbol="s",
        null_roles=["symbol"],
    )
    return replace(spec, **changes)


def test_the_symbol_levels_are_those_of_the_filter_unless_kept(tmp_path: Path) -> None:
    """Off (the default), the levels of the rows ``c`` = ``a``; on, those of every row with the missing level."""
    off = aggregate(_spec(tmp_path, filters=CAT_A))
    assert off.levels["symbol"] == ["p", "q"]
    on = aggregate(_spec(tmp_path, filters=CAT_A, keep_unfiltered_symbol_levels=True))
    assert on.levels["symbol"] == ["p", "q", "r", MISSING]
    assert on.all_levels["symbol"] == on.levels["symbol"]


def test_kept_symbol_levels_past_the_limit_name_the_setting(tmp_path: Path) -> None:
    """On, the 4 levels of every row pass a limit of 3, which the 2 of the filter meet: refused naming the setting to turn off."""
    spec = _spec(tmp_path, filters=CAT_A, max_levels=3)
    assert aggregate(spec).levels["symbol"] == ["p", "q"]
    with pytest.raises(ValueError) as refused:
        aggregate(replace(spec, keep_unfiltered_symbol_levels=True))
    assert "s は 4 個で、Color・Symbol・Group・Wrap の上限は 3 個" in str(refused.value)
    assert str(refused.value).endswith(
        "水準はフィルタの前の行から数える設定のため、別の列を使うか、"
        "「フィルタで除外された水準も凡例に残す」を外す"
    )
