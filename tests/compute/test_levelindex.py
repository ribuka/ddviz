"""The index of a column's levels and its search, for the filter card (`ddviz.compute.levelindex`)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from ddviz.compute import levelindex
from ddviz.compute.levelindex import build_index, search_index


def _parts(tmp_path: Path, *values: list) -> list[str]:
    """Write each list of values as a part of the column ``c``."""
    paths = []
    for i, part in enumerate(values):
        path = tmp_path / f"part{i}.parquet"
        pl.DataFrame({"c": part}, schema={"c": pl.String}).write_parquet(path)
        paths.append(str(path))
    return paths


def _index(tmp_path: Path, *values: list) -> Path:
    """Build the index of parts holding `values` and return its path."""
    path = tmp_path / "index.parquet"
    built = build_index(_parts(tmp_path, *values), "c", path)
    assert built["index"] == str(path)
    return path


def _values(found: dict) -> list:
    """Return the values of a search's levels."""
    return [value for value, _ in found["levels"]]


def test_counts_of_a_value_in_several_parts_add_up(tmp_path: Path) -> None:
    """A value in two parts counts the rows of both."""
    path = _index(tmp_path, ["a", "b", "a"], ["a", "c"], ["b"])
    found = search_index(path, "", "name")
    assert found == {
        "levels": [["a", 3], ["b", 2], ["c", 1]],
        "truncated": False,
        "n_levels": 3,
    }


def test_the_first_of_a_later_part_is_listed(tmp_path: Path) -> None:
    """The first level by name and the most rows, both only in the last part read, are among the 100 listed."""
    first = [f"v{i}" for i in range(10, 400)]
    path = _index(tmp_path, first, ["a0"], ["z"] * 50)
    by_name = search_index(path, "", "name")
    assert _values(by_name)[0] == "a0"
    assert len(by_name["levels"]) == 100
    assert by_name["truncated"]
    assert by_name["n_levels"] == 392
    by_count = search_index(path, "", "count")
    assert by_count["levels"][0] == ["z", 50]


def test_equal_counts_go_in_natural_order(tmp_path: Path) -> None:
    """Count puts the most rows first and equal counts in natural order: ID2 before ID10."""
    path = _index(tmp_path, ["ID10", "ID2", "ID1", "x", "x"])
    assert _values(search_index(path, "", "count")) == ["x", "ID1", "ID2", "ID10"]
    assert _values(search_index(path, "", "name")) == ["ID1", "ID2", "ID10", "x"]


@pytest.mark.parametrize(("matching", "truncated"), [(101, True), (100, False)])
def test_more_than_100_matches_are_truncated(
    tmp_path: Path, matching: int, truncated: bool
) -> None:
    """101 matches list 100 and are truncated; exactly 100 are not."""
    values = [f"hit{i}" for i in range(matching)] + [f"miss{i}" for i in range(50)]
    path = _index(tmp_path, values)
    found = search_index(path, "HIT", "name")
    assert len(found["levels"]) == 100
    assert found["truncated"] is truncated
    assert found["n_levels"] == matching + 50


def test_the_empty_string_is_a_level_and_null_is_not(tmp_path: Path) -> None:
    """An empty string is a level with its rows; nulls are left out."""
    path = _index(tmp_path, ["", "a", None, ""], [None])
    found = search_index(path, "", "name")
    assert found["levels"] == [["", 2], ["a", 1]]
    assert found["n_levels"] == 2


def test_the_keywords_match_in_any_case_and_order_literally(tmp_path: Path) -> None:
    """Every keyword, any case, any order, literally: regex characters are text; no match lists nothing."""
    path = _index(tmp_path, ["ABC-123", "abc", "123 abc", "a.c", "a+c", "x(1)"])
    assert _values(search_index(path, "abc", "name")) == ["abc", "ABC-123", "123 abc"]
    assert _values(search_index(path, "123 ABC", "name")) == ["ABC-123", "123 abc"]
    assert _values(search_index(path, "a.c", "name")) == ["a.c"]
    assert _values(search_index(path, "a+c", "name")) == ["a+c"]
    assert _values(search_index(path, "(1)", "name")) == ["x(1)"]
    none = search_index(path, "nothing", "count")
    assert none == {"levels": [], "truncated": False, "n_levels": 6}


def test_an_unknown_order_is_refused(tmp_path: Path) -> None:
    """Only name and count order the levels."""
    path = _index(tmp_path, ["a"])
    with pytest.raises(ValueError, match="unknown order"):
        search_index(path, "", "size")


def test_an_estimate_past_twice_the_limit_does_not_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A column estimated at more than twice the limit is too many without a group_by and writes no index."""
    monkeypatch.setattr(levelindex, "MAX_SEARCH_LEVELS", 10)

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("grouped")

    monkeypatch.setattr(pl.LazyFrame, "group_by", refuse)
    path = tmp_path / "index.parquet"
    parts = _parts(tmp_path, [f"id{i}" for i in range(100)])
    built = build_index(parts, "c", path)
    assert built["index"] is None
    assert built["n_levels"] > 20
    assert not path.exists()


def test_exact_levels_past_the_limit_are_too_many(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A column of 15 levels against a limit of 10 is grouped, then too many, with its exact count."""
    monkeypatch.setattr(levelindex, "MAX_SEARCH_LEVELS", 10)
    path = tmp_path / "index.parquet"
    parts = _parts(tmp_path, [f"id{i}" for i in range(15)] * 2)
    assert build_index(parts, "c", path) == {"index": None, "n_levels": 15}
    assert not path.exists()


def test_the_limit_itself_is_searched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A column of exactly the limit's levels gets an index."""
    monkeypatch.setattr(levelindex, "MAX_SEARCH_LEVELS", 10)
    path = _index(tmp_path, [f"id{i}" for i in range(10)])
    assert search_index(path, "", "name")["n_levels"] == 10


def test_a_failed_write_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that fails removes the partial file and publishes no index."""
    path = tmp_path / "index.parquet"
    parts = _parts(tmp_path, ["a", "b"])

    def fail(self: pl.DataFrame, file: Path, **_: object) -> None:
        Path(file).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", fail)
    with pytest.raises(OSError, match="disk full"):
        build_index(parts, "c", path)
    assert list(tmp_path.glob("index*")) == []
