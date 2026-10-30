"""Tests of the non-null values counted from the Parquet footer."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ddviz.compute.nonnull import nonnull_counts


def test_counts_sum_nulls_over_row_groups(tmp_path: Path) -> None:
    """Each flat column's count takes its nulls in every row group."""
    path = tmp_path / "data.parquet"
    pl.DataFrame(
        {
            "dense": [1.0, 2.0, 3.0, 4.0],
            "sparse": [None, None, 3.0, None],
            "empty": pl.Series([None] * 4, dtype=pl.String),
            "nested": [{"a": 1}, None, {"a": 2}, {"a": 3}],
        }
    ).write_parquet(path, row_group_size=2)
    counts = nonnull_counts([str(path)], ["sparse", "dense", "empty", "nested"])
    assert counts == ([1, 4, 0, None], 4)


def test_no_statistics_give_no_count(tmp_path: Path) -> None:
    """A file written without statistics has no count for any column."""
    path = tmp_path / "data.parquet"
    pl.DataFrame({"x": [1.0, None]}).write_parquet(path, statistics=False)
    assert nonnull_counts([str(path)], ["x"]) == ([None], 2)


def test_no_rows_give_no_count(tmp_path: Path) -> None:
    """Files without rows have no count for any column."""
    path = tmp_path / "data.parquet"
    pl.DataFrame({"x": pl.Series([], dtype=pl.Float64)}).write_parquet(path)
    assert nonnull_counts([str(path)], ["x"]) == ([None], 0)


def test_counts_of_files_take_a_missing_column_as_nulls(tmp_path: Path) -> None:
    """Over several files, a file without a column adds its rows as nulls."""
    first, second = tmp_path / "1.parquet", tmp_path / "2.parquet"
    pl.DataFrame({"x": [1.0, None], "y": [1, 2]}).write_parquet(first)
    pl.DataFrame({"x": [1.0, 2.0, 3.0]}).write_parquet(second)
    assert nonnull_counts([str(first), str(second)], ["x", "y"]) == ([4, 2], 5)
