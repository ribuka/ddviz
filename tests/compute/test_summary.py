"""Tests of the summary of a column for the filter pane: its missing values and its finite range."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

from ddviz.compute.summary import summarize_column


def test_missing_values_are_null_and_nan_in_a_float_column(tmp_path: Path) -> None:
    """A float column counts its nulls and NaNs as missing; other columns their nulls; min and max leave out NaN and ±inf."""
    path = tmp_path / "missing.parquet"
    nan, inf = float("nan"), float("inf")
    pl.DataFrame(
        {
            "f": [1.0, None, nan, -inf, inf, 3.0, nan],
            "i": [1, None, 2, 3, None, 4, 5],
            "d": [dt.date(2024, 1, d) if d else None for d in [1, 2, 0, 4, 5, 6, 7]],
            "s": ["a", None, "NaN", "b", None, None, "a"],
        }
    ).write_parquet(path)
    files = [str(path)]
    f = summarize_column(files, "f")
    assert (f["nulls"], f["min"], f["max"]) == (3, 1.0, 3.0)
    assert summarize_column(files, "i")["nulls"] == 2
    assert summarize_column(files, "d")["nulls"] == 1
    s = summarize_column(files, "s")
    assert s["nulls"] == 3
    assert {level: n for level, n in s["levels"]} == {"a": 2, "b": 1, "NaN": 1}
