"""Tests of listing the Parquet files of an input."""

from __future__ import annotations

from pathlib import Path

import pytest

from ddviz.shared.inputs import input_name, parquet_files, path_key, unique


def test_natural_order_compares_numbers_by_value() -> None:
    """Numbers compare by value, letters without case, folders part by part."""
    names = ["b/1.parquet", "a_10.parquet", "A_2.parquet", "a_2b.parquet", "a/z"]
    assert sorted(names, key=path_key) == [
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
    flat = parquet_files([tmp_path])
    assert [f.relative_to(tmp_path).as_posix() for f in flat] == [
        "part-2.PARQUET",
        "part-10.parquet",
    ]
    deep = parquet_files([tmp_path], recursive=True)
    assert [f.relative_to(tmp_path).as_posix() for f in deep] == [
        "part-2.PARQUET",
        "part-10.parquet",
        "year=2024/part-1.parquet",
    ]


def test_a_file_is_its_own_list(tmp_path: Path) -> None:
    """A file input is read as is, whatever its name."""
    path = tmp_path / "data.bin"
    assert parquet_files([path]) == [path]


def test_several_files_are_read_in_natural_order(tmp_path: Path) -> None:
    """Several files follow the natural order of their paths, not the order given."""
    names = ["b/data_10.parquet", "data_2.parquet", "b/data_1.parquet", "a.bin"]
    paths = [tmp_path / name for name in names]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    assert parquet_files(paths) == [paths[3], paths[2], paths[0], paths[1]]
    assert input_name(paths) == ("a.bin", 3)
    assert input_name(paths[:1]) == ("data_10.parquet", 0)


def test_a_folder_among_several_paths_is_refused(tmp_path: Path) -> None:
    """Several paths must all be files."""
    (tmp_path / "data.parquet").write_bytes(b"")
    (tmp_path / "folder").mkdir()
    with pytest.raises(ValueError, match="folder"):
        parquet_files([tmp_path / "data.parquet", tmp_path / "folder"])


def test_a_path_given_twice_counts_once(tmp_path: Path) -> None:
    """Repeats go, keeping the first; on Windows, case does not tell paths apart."""
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    assert unique([a, b, a]) == [a, b]
