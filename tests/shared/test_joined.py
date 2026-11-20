"""The names of the columns a join adds (`ddviz.shared.joined`)."""

from __future__ import annotations

from ddviz.shared.joined import join_id, joined_names


def test_the_example_of_the_issue() -> None:
    """``lot, temp`` joined by ``lot`` to ``lot, temp, vendor`` add ``_joined, temp_joined, vendor``."""
    names = joined_names(["lot", "temp"], ["temp", "vendor"], {}, True)
    assert names == {"_joined": None, "temp_joined": "temp", "vendor": "vendor"}


def test_free_names_stay() -> None:
    """Columns whose names are free keep them; a join by rows adds no ``_joined``."""
    names = joined_names(["a"], ["b", "c"], {}, False)
    assert names == {"b": "b", "c": "c"}


def test_taken_names_move_to_the_first_free_one() -> None:
    """A taken name gets ``_joined``, then ``_joined_2``, ...; ``_joined`` itself ``_joined_2``, ..."""
    taken = ["n", "n_joined", "m", "_joined", "_joined_2"]
    names = joined_names(taken, ["n", "m", "N"], {}, True)
    assert list(names) == ["_joined_3", "n_joined_2", "m_joined", "N"]
    assert names["_joined_3"] is None


def test_names_decided_earlier_are_taken() -> None:
    """A name a column took is taken for the next ones: ``x`` then ``x_joined`` of the joined table."""
    names = joined_names(["x"], ["x_joined", "x"], {}, False)
    assert names == {"x_joined": "x_joined", "x_joined_2": "x"}


def test_the_joined_tables_files_are_always_renamed() -> None:
    """A joined table of several files adds ``source_joined`` and ``filename_joined`` last, free or not."""
    names = joined_names(["a"], ["b"], {"source": "source", "filename": "filename"}, True)
    assert list(names) == ["_joined", "b", "source_joined", "filename_joined"]
    assert names["source_joined"] == "source"
    names = joined_names(
        ["source_joined"], ["filename_joined"], {"source_2": "source", "filename": "filename"}, False
    )
    assert names == {
        "filename_joined": "filename_joined",
        "source_joined_2": "source_2",
        "filename_joined_2": "filename",
    }


def test_one_file_adds_no_file_columns() -> None:
    """A joined table of one file has no added columns to add."""
    assert list(joined_names(["a"], ["source", "filename"], {}, False)) == [
        "source",
        "filename",
    ]


def test_a_join_id_changes_with_what_it_depends_on() -> None:
    """The id of a join changes with its kind, the joined table, its files, its keys and their types, and the paths as given."""
    keys = [{"left": "a", "right": "b", "left_dtype": "Int64", "right_dtype": "Int32"}]
    files = {"x.parquet": {"size": 1, "mtime_ns": 2}}
    paths = ["c:\\in", "c:\\t"]
    base = join_id("key", "c:\\t", files, keys, [], paths)
    assert base == join_id("key", "c:\\t", files, keys, [], paths)
    assert base != join_id("rows", "c:\\t", files, [], [], paths)
    assert base != join_id("key", "c:\\u", files, keys, [], paths)
    changed = {"x.parquet": {"size": 1, "mtime_ns": 3}}
    assert base != join_id("key", "c:\\t", changed, keys, [], paths)
    retyped = [{**keys[0], "right_dtype": "Int64"}]
    assert base != join_id("key", "c:\\t", files, retyped, [], paths)
    spelled = ["c:\\x\\..\\in", "c:\\t"]
    assert base != join_id("key", "c:\\t", files, keys, [], spelled)
    by_rows = join_id("rows", "c:\\t", files, [], [1, 2], paths)
    assert by_rows != join_id("rows", "c:\\t", files, [], [2, 1], paths)
