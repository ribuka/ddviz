"""Tests of the share of non-null values from the Parquet footer."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from ddviz.compute.nonnull import nonnull_shares


def test_shares_sum_nulls_over_row_groups(tmp_path: Path) -> None:
    """Each flat column's share counts its nulls in every row group."""
    path = tmp_path / "data.parquet"
    pl.DataFrame(
        {
            "dense": [1.0, 2.0, 3.0, 4.0],
            "sparse": [None, None, 3.0, None],
            "empty": pl.Series([None] * 4, dtype=pl.String),
            "nested": [{"a": 1}, None, {"a": 2}, {"a": 3}],
        }
    ).write_parquet(path, row_group_size=2)
    shares = nonnull_shares([str(path)], ["sparse", "dense", "empty", "nested"])
    assert shares[:3] == pytest.approx([0.25, 1.0, 0.0])
    assert shares[3] is None


def test_no_statistics_give_no_share(tmp_path: Path) -> None:
    """A file written without statistics has no share for any column."""
    path = tmp_path / "data.parquet"
    pl.DataFrame({"x": [1.0, None]}).write_parquet(path, statistics=False)
    assert nonnull_shares([str(path)], ["x"]) == [None]


def test_shares_of_files_count_a_missing_column_as_nulls(tmp_path: Path) -> None:
    """Over several files, a file without a column adds its rows as nulls."""
    first, second = tmp_path / "1.parquet", tmp_path / "2.parquet"
    pl.DataFrame({"x": [1.0, None], "y": [1, 2]}).write_parquet(first)
    pl.DataFrame({"x": [1.0, 2.0, 3.0]}).write_parquet(second)
    shares = nonnull_shares([str(first), str(second)], ["x", "y"])
    assert shares == pytest.approx([0.8, 0.4])
