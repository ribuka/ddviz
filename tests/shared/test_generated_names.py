"""The names and values of the columns added to an input of several files."""

from __future__ import annotations

from pathlib import Path

import pytest

from ddviz.shared.generated import generated_names, generated_value, part_key


def test_one_file_adds_no_columns() -> None:
    """One file, or none, adds nothing; two add ``source`` then ``filename``."""
    assert generated_names(["x"], 1) == {}
    assert generated_names([], 0) == {}
    assert generated_names(["x"], 2) == {"source": "source", "filename": "filename"}


def test_taken_names_take_the_next_free_number() -> None:
    """Each kind skips the names in use on its own; case counts."""
    present = ["source", "source_2", "filename", "Filename_2"]
    assert generated_names(present, 3) == {
        "source_3": "source",
        "filename_2": "filename",
    }
    assert generated_names(["Source", "FILENAME"], 2) == {
        "source": "source",
        "filename": "filename",
    }


def test_the_values_are_the_absolute_path_and_the_stem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative path is made absolute; only the last extension goes."""
    monkeypatch.chdir(tmp_path)
    assert generated_value("source", "run.01.parquet") == str(
        tmp_path / "run.01.parquet"
    )
    assert generated_value("filename", r"C:\data\run.01.parquet") == "run.01"
    with pytest.raises(ValueError):
        generated_value("other", "a.parquet")


def test_added_columns_key_their_parts_apart() -> None:
    """A file's column and an added one of the same name and type have other parts."""
    assert part_key("String", None) == "String"
    assert part_key("String", "source") != part_key("String", None)
    assert part_key("String", "source") != part_key("String", "filename")
