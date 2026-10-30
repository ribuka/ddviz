"""Tests of listing the Parquet files of an input."""

from __future__ import annotations

from pathlib import Path

from ddviz.shared.inputs import natural_key, parquet_files


def test_natural_order_compares_numbers_by_value() -> None:
    """Numbers compare by value, letters without case, folders part by part."""
    names = ["b/1.parquet", "a_10.parquet", "A_2.parquet", "a_2b.parquet", "a/z"]
    assert sorted(names, key=natural_key) == [
        "a/z",
        "A_2.parquet",
        "a_2b.parquet",
        "a_10.parquet",
        "b/1.parquet",
    ]


def test_a_folder_lists_its_parquet_files(tmp_path: Path) -> None:
    """Only .parquet files count, without hidden or underscored ones; subfolders on request."""
    for name in (
        "part-10.parquet",
        "part-2.PARQUET",
        "notes.txt",
        "_SUCCESS",
        "_metadata.parquet",
        ".hidden.parquet",
        "year=2024/part-1.parquet",
        "_tmp/part-0.parquet",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"")
    flat = parquet_files(tmp_path)
    assert [f.relative_to(tmp_path).as_posix() for f in flat] == [
        "part-2.PARQUET",
        "part-10.parquet",
    ]
    deep = parquet_files(tmp_path, recursive=True)
    assert [f.relative_to(tmp_path).as_posix() for f in deep] == [
        "part-2.PARQUET",
        "part-10.parquet",
        "year=2024/part-1.parquet",
    ]


def test_a_file_is_its_own_list(tmp_path: Path) -> None:
    """A file input is read as is, whatever its name."""
    path = tmp_path / "data.bin"
    assert parquet_files(path) == [path]
