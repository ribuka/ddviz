"""Tests of the column cache's layout, invalidation and eviction."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ddviz.shared.cache import DAY, ColumnCache, evict


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """Return a stand-in source file; the cache only looks at its size and time."""
    path = tmp_path / "data.parquet"
    path.write_bytes(b"0" * 10)
    return path


def _fill(cache: ColumnCache, column: str, size: int, mtime: float) -> Path:
    """Write a column file of `size` bytes last used at `mtime`."""
    path = cache.file(column)
    path.write_bytes(b"0" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_files_are_named_by_position_and_kept_across_opens(
    tmp_path: Path, source: Path
) -> None:
    """A converted column survives reopening the cache of an unchanged source."""
    cache = ColumnCache(tmp_path / "cache", source, ["a", "b/c"])
    assert cache.file("b/c").name == "c000001.parquet"
    assert cache.missing(["a", "b/c", "a"]) == ["a", "b/c"]
    cache.file("a").write_bytes(b"x")
    reopened = ColumnCache(tmp_path / "cache", source, ["a", "b/c"])
    assert reopened.missing(["a", "b/c"]) == ["b/c"]


def test_a_changed_source_discards_its_columns(tmp_path: Path, source: Path) -> None:
    """Rewriting the source with another size drops the files made from it."""
    cache = ColumnCache(tmp_path / "cache", source, ["a"])
    cache.file("a").write_bytes(b"x")
    source.write_bytes(b"0" * 20)
    assert ColumnCache(tmp_path / "cache", source, ["a"]).missing(["a"]) == ["a"]


def test_an_unfinished_conversion_is_removed(tmp_path: Path, source: Path) -> None:
    """A partial file left by a killed conversion goes when the cache opens."""
    cache = ColumnCache(tmp_path / "cache", source, ["a"])
    partial = cache.dir / "c000000.parquet.tmp"
    partial.write_bytes(b"x")
    ColumnCache(tmp_path / "cache", source, ["a"])
    assert not partial.exists()


def test_evict_removes_unused_then_least_recently_used(
    tmp_path: Path, source: Path
) -> None:
    """Old files go first, then the oldest until the total fits; kept files stay."""
    now = 1_000 * DAY
    cache = ColumnCache(tmp_path / "cache", source, ["a", "b", "c", "d"])
    old = _fill(cache, "a", 10, now - 31 * DAY)
    lru = _fill(cache, "b", 10, now - 3 * DAY)
    kept = _fill(cache, "c", 10, now - 2 * DAY)
    recent = _fill(cache, "d", 10, now - 1 * DAY)
    removed = evict(tmp_path / "cache", 20, 30, keep=[kept], now=now)
    assert removed == [old, lru]
    assert kept.exists() and recent.exists()


def test_touch_marks_a_column_as_used(tmp_path: Path, source: Path) -> None:
    """A touched file is not evicted for age."""
    cache = ColumnCache(tmp_path / "cache", source, ["a"])
    path = _fill(cache, "a", 1, 0.0)
    cache.touch(["a"])
    assert evict(tmp_path / "cache", 100, 30) == []
    assert path.exists()
