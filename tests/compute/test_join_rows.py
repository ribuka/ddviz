"""The rows of both tables of a dry run as a file to save: a full outer join with the state of each row (Issue #379)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from ddviz.compute import savefile
from ddviz.compute.join import run_join
from ddviz.compute.joinrows import run_join_rows
from ddviz.compute.tasks.columns import run_schema
from ddviz.shared.cache import SCHEMA
from ddviz.shared.manifest import read_manifest
from ddviz.shared.tasks import JoinRowsTask, JoinTask, SourceFiles


@dataclass
class _Table:
    """A table of Parquet files as a task reads it: every column, its added ones, the parts in the cache and the files."""

    columns: list[str]
    generated: dict[str, str]
    parts: dict[str, list[str]]
    files: SourceFiles
    # The table as it is read, with its added columns.
    frame: pl.DataFrame


def _table(folder: Path, frames: list[pl.DataFrame], cached: list[str]) -> _Table:
    """Write `frames` as the files of a table, and the columns `cached` (by name) as parts in the cache."""
    folder.mkdir(parents=True)
    paths = []
    for i, frame in enumerate(frames):
        paths.append(str(folder / f"f{i}.parquet"))
        frame.write_parquet(paths[-1])
    schema = folder / "schema"
    schema.mkdir()
    run_schema(paths, schema, lambda _: None)
    found = read_manifest(schema)
    generated = found["generated"]
    columns = [c["name"] for c in found["columns"]]
    added = {"source": lambda p: str(p), "filename": lambda p: Path(p).stem}
    whole = pl.concat(
        [
            frame.with_columns(pl.lit(added[k](p)).alias(c) for c, k in generated.items())
            for frame, p in zip(frames, paths, strict=True)
        ]
    )
    parts: dict[str, list[str]] = {}
    for column in cached:
        start = 0
        for i, rows in enumerate(found["rows"]):
            path = folder / "parts" / f"{column}-{i}.parquet"
            path.parent.mkdir(exist_ok=True)
            whole.select(column).slice(start, rows).write_parquet(path)
            parts.setdefault(column, []).append(str(path))
            start += rows
    dtypes = {c["name"]: c["dtype"] for c in found["columns"] if c["name"] not in generated}
    files = SourceFiles(paths, found["rows"], str(schema / SCHEMA), dtypes, generated)
    return _Table(columns, generated, parts, files, whole)


def _key_parts(table: _Table, keys: list[str], folder: Path) -> dict[str, list[str]]:
    """Return the parts of the keys of a table, written apart from its parts."""
    parts: dict[str, list[str]] = {}
    for column in keys:
        start = 0
        for i, rows in enumerate(table.files.rows):
            path = folder / f"{column}-{i}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            table.frame.select(column).slice(start, rows).write_parquet(path)
            parts.setdefault(column, []).append(str(path))
            start += rows
    return parts


def _write(
    tmp_path: Path, left: _Table, right: _Table, keys: list[tuple[str, str]], columns: str, file_format: str
) -> pl.DataFrame:
    """Run the join task and then the rows of both tables; return the file read back, a CSV as texts."""
    pairs = [{"left": a, "right": b} for a, b in keys]
    maps = [str(tmp_path / "maps" / f"{i}.parquet") for i in range(len(left.files.rows))]
    if not (tmp_path / "maps").exists():
        run_join(
            JoinTask(
                pairs,
                _key_parts(left, [a for a, _ in keys], tmp_path / "left-keys"),
                _key_parts(right, [b for _, b in keys], tmp_path / "right-keys"),
                left.files.rows,
                right.frame.height,
                maps,
                "_joined",
                [str(tmp_path / "joined" / f"{i}.parquet") for i in range(len(left.files.rows))],
            ),
            tmp_path / "join",
            lambda _: None,
        )
    out = tmp_path / f"rows-{len(list(tmp_path.glob('rows-*')))}"
    out.mkdir()
    task = JoinRowsTask(
        file_format,
        columns,
        pairs,
        maps,
        left.columns,
        left.generated,
        left.parts,
        left.files,
        right.columns,
        right.generated,
        right.parts,
        right.files,
        "token",
    )
    messages: list[dict] = []
    run_join_rows(task, out, messages.append)
    file = out / read_manifest(out)["file"]
    assert sorted(p.name for p in out.iterdir()) == sorted(["manifest.json", file.name])
    total = messages[-1]["total"]
    assert messages[-1] == {"type": "progress", "stage": "export", "export": "token", "done": total, "total": total}
    if file_format == "csv":
        content = file.read_bytes()
        assert content.startswith("﻿".encode())
        return pl.read_csv(io.BytesIO(content[3:]), infer_schema=False)
    return pl.read_parquet(file)


def _expected(
    left: _Table, right: _Table, keys: list[tuple[str, str]], names: dict[str, str], order: list[str]
) -> pl.DataFrame:
    """Return the full outer join of both tables found apart with polars: the joined table's columns under `names`, in `order`."""
    lefts = [a for a, _ in keys]
    rights = [names[b] for _, b in keys]
    index = pl.get_index_type()
    # Compared as texts: an Int32 key matches an Int64 one of the same value.
    on = [f"__k{i}" for i in range(len(keys))]
    mine = left.frame.with_row_index("__l").with_columns(
        pl.col(c).cast(pl.String).alias(k) for c, k in zip(lefts, on, strict=True)
    )
    theirs = right.frame.rename(names).with_row_index("__r").with_columns(
        pl.col(c).cast(pl.String).alias(k + "_r") for c, k in zip(rights, on, strict=True)
    )
    joined = mine.join(theirs, left_on=on, right_on=[k + "_r" for k in on], how="full", coalesce=False)
    state = (
        pl.when(pl.col("__l").is_null())
        .then(pl.lit("right_only"))
        .when(pl.col("__r").is_null())
        .then(pl.lit("left_only"))
        .otherwise(pl.lit("both"))
    )
    joined = joined.sort(["__l", "__r"], nulls_last=True).with_columns(
        state.alias(order[0]), pl.col("__l").cast(index).alias(order[1]), pl.col("__r").cast(index).alias(order[2])
    )
    return joined.select(order)


def _check(found: pl.DataFrame, expected: pl.DataFrame, file_format: str) -> None:
    """Check a file read back against the expected table: its types too for a Parquet file, its texts for a CSV."""
    if file_format == "parquet":
        assert_frame_equal(found, expected)
    else:
        texts = pl.read_csv(io.BytesIO(expected.write_csv().encode()), infer_schema=False)
        assert_frame_equal(found, texts)


FORMATS = ["parquet", "csv"]


@pytest.mark.parametrize("file_format", FORMATS)
def test_the_example_is_the_full_outer_join_with_the_state(tmp_path: Path, file_format: str) -> None:
    """The example of the Issue: every row of the input, then those of the joined table that match none, with the row numbers of both."""
    left = _table(tmp_path / "left", [pl.DataFrame({"lot": ["A", "A", "B", None]})], ["lot"])
    right = _table(tmp_path / "right", [pl.DataFrame({"lot_id": ["A", "C", None]})], [])
    found = _write(tmp_path, left, right, [("lot", "lot_id")], "key", file_format)
    index = pl.get_index_type()
    expected = pl.DataFrame(
        {
            "_joined": ["both", "both", "left_only", "left_only", "right_only", "right_only"],
            "index": pl.Series([0, 1, 2, 3, None, None], dtype=index),
            "index_joined": pl.Series([0, 0, None, None, 1, 2], dtype=index),
            "lot": ["A", "A", "B", None, None, None],
            "lot_id": ["A", "A", None, None, "C", None],
        }
    )
    _check(found, expected, file_format)


@pytest.fixture
def tables(tmp_path: Path) -> tuple[_Table, _Table]:
    """Return an input of 3 files and a joined table of 2: keys of the same name, an Int32 key on an Int64 one, a second key, and the input holding ``index`` and ``_joined``."""
    left = _table(
        tmp_path / "left",
        [
            pl.DataFrame(
                {
                    "lot": pl.Series([1, 1, 2, None], dtype=pl.Int32),
                    "sub": ["a", "a", "b", "a"],
                    "index": [10, 11, 12, 13],
                    "_joined": ["x", "y", "z", "w"],
                    "x": [0.5, 1.5, 2.5, 3.5],
                }
            ),
            pl.DataFrame({"lot": pl.Series([3, 9], dtype=pl.Int32), "sub": ["a", "a"], "index": [14, 15], "_joined": ["v", "u"], "x": [4.5, 5.5]}),
            pl.DataFrame({"lot": pl.Series([4, 2, 1], dtype=pl.Int32), "sub": ["a", "b", "b"], "index": [16, 17, 18], "_joined": ["t", "s", "r"], "x": [6.5, 7.5, 8.5]}),
        ],
        ["lot", "x"],
    )
    right = _table(
        tmp_path / "right",
        [
            pl.DataFrame({"lot": [1, 2, 7], "sub": ["a", "b", "a"], "index": [100, 101, 102], "temp": [1.0, 2.0, 3.0]}),
            pl.DataFrame({"lot": [3, None, 8], "sub": ["a", "a", "b"], "index": [103, 104, 105], "temp": [4.0, 5.0, 6.0]}),
        ],
        ["temp"],
    )
    return left, right


# The names of the joined table's columns: after the input's columns and
# ``_joined_2``, ``index_2`` and ``index_joined``.
NAMES = {
    "lot": "lot_joined",
    "sub": "sub_joined",
    "index": "index_joined_2",
    "temp": "temp",
    "source": "source_joined",
    "filename": "filename_joined",
}
HEAD = ["_joined_2", "index_2", "index_joined"]
CASES = {
    "one": [("lot", "lot")],
    "two": [("lot", "lot"), ("sub", "sub")],
}


@pytest.mark.parametrize("chunks", ["one", "several"])
@pytest.mark.parametrize("file_format", FORMATS)
@pytest.mark.parametrize("columns", ["key", "all"])
@pytest.mark.parametrize("case", list(CASES))
def test_the_rows_are_the_full_outer_join_of_both_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tables: tuple[_Table, _Table],
    case: str,
    columns: str,
    file_format: str,
    chunks: str,
) -> None:
    """The keys of each table keep their types and come first; the added columns come with the keys only, every column with all; names already taken move on.

    A chunk of a few rows writes the same file as one chunk.
    """
    if chunks == "several":
        monkeypatch.setattr(savefile, "MAX_CHUNK_ROWS", 6)
    left, right = tables
    keys = CASES[case]
    lefts, rights = [a for a, _ in keys], [b for _, b in keys]
    if columns == "key":
        order = [*HEAD, *lefts, *(NAMES[b] for b in rights), "source", "filename", "source_joined", "filename_joined"]
    else:
        rest = [c for c in left.columns if c not in lefts]
        others = [NAMES[c] for c in right.columns if c not in rights]
        order = [*HEAD, *lefts, *(NAMES[b] for b in rights), *rest, *others]
    expected = _expected(left, right, keys, NAMES, order)
    assert expected.height == 12
    assert expected.schema["lot"] == pl.Int32
    assert expected.schema["lot_joined"] == pl.Int64
    found = _write(tmp_path, left, right, keys, columns, file_format)
    _check(found, expected, file_format)


@pytest.mark.parametrize("file_format", FORMATS)
def test_columns_named_as_the_internal_ones_keep_their_values(tmp_path: Path, file_format: str) -> None:
    """Columns of either table named as the row numbers the task holds inside, keys or not, are written as any column (review of #382)."""
    left = _table(
        tmp_path / "left",
        [pl.DataFrame({"__ddviz_left": [1, 2, 4], "__ddviz_right": ["a", "b", "c"]})],
        ["__ddviz_left"],
    )
    right = _table(tmp_path / "right", [pl.DataFrame({"k": [2, 3], "__ddviz_left": [0.5, 1.5]})], [])
    keys = [("__ddviz_left", "k")]
    names = {"k": "k", "__ddviz_left": "__ddviz_left_joined"}
    order = ["_joined", "index", "index_joined", "__ddviz_left", "k", "__ddviz_right", "__ddviz_left_joined"]
    found = _write(tmp_path, left, right, keys, "all", file_format)
    _check(found, _expected(left, right, keys, names, order), file_format)


@pytest.mark.parametrize("columns", ["key", "all"])
def test_an_added_column_as_a_key_takes_the_name_of_its_kind(tmp_path: Path, columns: str) -> None:
    """The joined table's ``filename`` as its key is ``filename_joined``, as an added column, even when the input has no such column (review of #382)."""
    left = _table(tmp_path / "left", [pl.DataFrame({"fname": ["f0", "f1", "x"], "v": [1, 2, 3]})], [])
    right = _table(tmp_path / "right", [pl.DataFrame({"w": [10]}), pl.DataFrame({"w": [20]})], [])
    keys = [("fname", "filename")]
    names = {"filename": "filename_joined", "source": "source_joined", "w": "w"}
    rest = ["source_joined"] if columns == "key" else ["v", "w", "source_joined"]
    order = ["_joined", "index", "index_joined", "fname", "filename_joined", *rest]
    found = _write(tmp_path, left, right, keys, columns, "parquet")
    _check(found, _expected(left, right, keys, names, order), "parquet")
    assert found["_joined"].to_list() == ["both", "both", "left_only"]
