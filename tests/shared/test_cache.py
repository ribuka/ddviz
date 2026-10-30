"""Tests of the column cache's layout, invalidation and eviction."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ddviz.shared.cache import DAY, SCHEMA, ColumnCache, evict


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Return a folder of stand-in source files; the cache only looks at their size and time."""
    path = tmp_path / "data"
    (path / "sub").mkdir(parents=True)
    for name in ("a.parquet", "b.parquet", "sub/c.parquet"):
        (path / name).write_bytes(b"0" * 10)
    return path


def _files(folder: Path) -> list[Path]:
    return [folder / "a.parquet", folder / "b.parquet", folder / "sub" / "c.parquet"]


def _fill(cache: ColumnCache, column: str, files: dict[int, tuple[int, float]]) -> None:
    """Write parts of a column: per file position, its size and last use."""
    parts = cache.parts(column, "Float64")
    for i, (size, mtime) in files.items():
        parts[i].parent.mkdir(parents=True, exist_ok=True)
        parts[i].write_bytes(b"0" * size)
        os.utime(parts[i], (mtime, mtime))


def test_parts_are_per_file_and_kept_across_opens(tmp_path: Path, folder: Path) -> None:
    """A column has a part per file, named by its name and type; parts survive reopening."""
    cache = ColumnCache(tmp_path / "cache", folder, _files(folder))
    parts = cache.parts("b/c", "Float64")
    assert len({p.parent for p in parts}) == 3
    assert len({p.name for p in parts}) == 1
    assert cache.parts("b/c", "String")[0] != parts[0]
    assert cache.missing({"a": "Int64", "b/c": "Float64"}) == {
        "a": [0, 1, 2],
        "b/c": [0, 1, 2],
    }
    _fill(cache, "b/c", {0: (1, 0.0), 2: (1, 0.0)})
    reopened = ColumnCache(tmp_path / "cache", folder, _files(folder))
    assert reopened.missing({"b/c": "Float64"}) == {"b/c": [1]}


def test_a_changed_file_discards_only_its_parts(tmp_path: Path, folder: Path) -> None:
    """Rewriting one file drops its parts and the files made from all files; others stay."""
    cache = ColumnCache(tmp_path / "cache", folder, _files(folder))
    _fill(cache, "x", {0: (1, 0.0), 1: (1, 0.0), 2: (1, 0.0)})
    (cache.dir / SCHEMA).write_bytes(b"x")
    (folder / "b.parquet").write_bytes(b"0" * 20)
    reopened = ColumnCache(tmp_path / "cache", folder, _files(folder))
    assert reopened.missing({"x": "Float64"}) == {"x": [1]}
    assert not (cache.dir / SCHEMA).exists()


def test_added_and_removed_files_keep_the_others_parts(
    tmp_path: Path, folder: Path
) -> None:
    """A file added before the others shifts positions but not the parts of the others."""
    cache = ColumnCache(tmp_path / "cache", folder, _files(folder))
    _fill(cache, "x", {0: (1, 0.0), 1: (1, 0.0), 2: (1, 0.0)})
    (cache.dir / SCHEMA).write_bytes(b"x")
    (folder / "0.parquet").write_bytes(b"0")
    (folder / "b.parquet").unlink()
    files = [folder / "0.parquet", folder / "a.parquet", folder / "sub" / "c.parquet"]
    reopened = ColumnCache(tmp_path / "cache", folder, files)
    assert reopened.missing({"x": "Float64"}) == {"x": [0]}
    assert not (cache.dir / SCHEMA).exists()


def test_an_unchanged_input_keeps_its_schema(tmp_path: Path, folder: Path) -> None:
    """Reopening the cache of unchanged files keeps the files made from all of them."""
    cache = ColumnCache(tmp_path / "cache", folder, _files(folder))
    (cache.dir / SCHEMA).write_bytes(b"x")
    ColumnCache(tmp_path / "cache", folder, _files(folder))
    assert (cache.dir / SCHEMA).exists()


def test_a_single_file_is_an_input_of_one(tmp_path: Path, folder: Path) -> None:
    """A file input has its own directory, with one part per column."""
    source = folder / "a.parquet"
    cache = ColumnCache(tmp_path / "cache", source, [source])
    assert len(cache.parts("x", "Float64")) == 1
    assert cache.dir != ColumnCache(tmp_path / "cache", folder, _files(folder)).dir


def test_an_unfinished_conversion_is_removed(tmp_path: Path, folder: Path) -> None:
    """A partial file left by a killed conversion goes when the cache opens."""
    cache = ColumnCache(tmp_path / "cache", folder, _files(folder))
    part = cache.parts("x", "Float64")[1]
    part.parent.mkdir(parents=True)
    partial = part.with_name(part.name + ".tmp")
    partial.write_bytes(b"x")
    ColumnCache(tmp_path / "cache", folder, _files(folder))
    assert not partial.exists()


def test_evict_removes_unused_then_least_recently_used(
    tmp_path: Path, folder: Path
) -> None:
    """Old parts go first, then the oldest until the total fits; kept parts stay."""
    now = 1_000 * DAY
    cache = ColumnCache(tmp_path / "cache", folder, _files(folder))
    _fill(cache, "a", {0: (10, now - 31 * DAY)})
    _fill(cache, "b", {1: (10, now - 3 * DAY)})
    _fill(cache, "c", {2: (10, now - 2 * DAY)})
    _fill(cache, "d", {0: (10, now - 1 * DAY)})
    old, lru = cache.parts("a", "Float64")[0], cache.parts("b", "Float64")[1]
    kept, recent = cache.parts("c", "Float64")[2], cache.parts("d", "Float64")[0]
    removed = evict(tmp_path / "cache", 20, 30, keep=[kept], now=now)
    assert removed == [old, lru]
    assert kept.exists() and recent.exists()


def test_touch_marks_a_column_as_used(tmp_path: Path, folder: Path) -> None:
    """Touched parts are not evicted for age."""
    cache = ColumnCache(tmp_path / "cache", folder, _files(folder))
    _fill(cache, "a", {0: (1, 0.0), 1: (1, 0.0), 2: (1, 0.0)})
    cache.touch({"a": "Float64"})
    assert evict(tmp_path / "cache", 100, 30) == []
    assert all(p.exists() for p in cache.parts("a", "Float64"))
