"""Tests of reading the schema of an input, converting its columns into parts and reading them back."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from ddviz.compute.aggregate import aggregate
from ddviz.compute.convert import convert_columns
from ddviz.compute.scan import scan_columns
from ddviz.compute.tasks.columns import run_schema
from ddviz.shared.cache import SCHEMA, ColumnCache
from ddviz.shared.generated import part_key
from ddviz.shared.inputs import parquet_files
from ddviz.shared.manifest import read_manifest
from ddviz.shared.scatter import ScatterSpec
from ddviz.shared.tasks import ConvertTask


def _schema(source: Path, out: Path) -> dict:
    """Run the schema task on an input and return its manifest."""
    out.mkdir()
    run_schema([str(f) for f in parquet_files([source])], out, lambda _: None)
    return read_manifest(out)


def _convert(source: Path, tmp_path: Path, columns: list[str]) -> dict[str, list[str]]:
    """Convert `columns` of an input into a column cache and return the parts of each."""
    files = parquet_files([source])
    manifest = _schema(source, tmp_path / "schema")
    dtypes = {
        c["name"]: c["dtype"] for c in manifest["columns"] if c["name"] in columns
    }
    generated = {c: k for c, k in manifest["generated"].items() if c in columns}
    keys = {c: part_key(dtypes[c], generated.get(c), [str(source)]) for c in columns}
    cache = ColumnCache(tmp_path / "cache", [source], files)
    parts = {c: [str(p) for p in cache.parts(c, keys[c])] for c in columns}
    task = ConvertTask(
        str(tmp_path / "schema" / SCHEMA),
        dtypes,
        [str(f) for f in files],
        [{c: parts[c][i] for c in columns} for i in range(len(files))],
        generated,
    )
    messages = []
    convert_columns(task, messages.append)
    total = len(files) * len(columns)
    assert [(m["done"], m["total"]) for m in messages] == [
        (i, total) for i in range(total)
    ]
    assert cache.missing(keys) == {}
    return parts


def test_the_schema_of_a_folder_unites_its_files(
    folder_path: Path, folder_frame: pl.DataFrame, tmp_path: Path
) -> None:
    """Columns come in the order they first appear; differing types are cast and listed."""
    manifest = _schema(folder_path, tmp_path / "out")
    added = ["source", "filename"]
    assert [c["name"] for c in manifest["columns"]] == [*folder_frame.columns, *added]
    assert {c["name"]: c["dtype"] for c in manifest["columns"]}["n"] == "Int64"
    assert manifest["rows"] == [700, 700, folder_frame.height - 1400]
    assert manifest["casts"] == [
        {"name": "n", "dtypes": ["Int32", "Int64"], "dtype": "Int64"}
    ]
    assert pl.read_parquet_schema(tmp_path / "out" / SCHEMA) == {
        **folder_frame.schema,
        **dict.fromkeys(added, pl.String),
    }


def test_a_schema_without_a_common_type_fails(tmp_path: Path) -> None:
    """Types that cannot be cast to one another refuse the input, naming the column."""
    (tmp_path / "in").mkdir()
    pl.DataFrame({"a": [[1]]}).write_parquet(tmp_path / "in" / "1.parquet")
    pl.DataFrame({"a": [{"b": 1}]}).write_parquet(tmp_path / "in" / "2.parquet")
    with pytest.raises(ValueError, match="^a: "):
        _schema(tmp_path / "in", tmp_path / "out")


def test_converted_columns_read_back_side_by_side(
    scatter_path: Path, scatter_frame: pl.DataFrame, tmp_path: Path
) -> None:
    """Columns from separate files come back in order, with the source's row index."""
    parts = _convert(scatter_path, tmp_path, ["label", "x"])
    frame = scan_columns(parts, row_index="i").collect()
    assert_frame_equal(
        frame, scatter_frame.with_row_index("i").select("i", "label", "x")
    )


def test_a_folder_reads_back_as_one_table(
    folder_path: Path, folder_frame: pl.DataFrame, tmp_path: Path
) -> None:
    """Parts of the files read in order: missing columns are nulls, types are cast."""
    parts = _convert(folder_path, tmp_path, ["x", "label", "n"])
    frame = scan_columns(parts, row_index="i").collect()
    expected = folder_frame.with_row_index("i").select("i", "x", "label", "n")
    assert_frame_equal(frame, expected)
    assert frame["label"][700:1400].null_count() == 700


def test_aggregate_from_the_cache_matches_the_source(
    scatter_spec: ScatterSpec, tmp_path: Path, scatter_path: Path
) -> None:
    """Aggregating from per-column files gives the same bins as from the source."""
    parts = _convert(scatter_path, tmp_path, list(scatter_spec.files))
    cached = ScatterSpec.from_dict({**scatter_spec.to_dict(), "files": parts})
    assert_frame_equal(aggregate(cached).bins, aggregate(scatter_spec).bins)


def test_aggregate_of_a_folder_matches_one_file(
    scatter_spec: ScatterSpec,
    folder_path: Path,
    folder_frame: pl.DataFrame,
    tmp_path: Path,
) -> None:
    """A folder aggregates like one file holding its rows in reading order."""
    single = tmp_path / "single.parquet"
    folder_frame.write_parquet(single)
    parts = _convert(folder_path, tmp_path, list(scatter_spec.files))
    from_folder = ScatterSpec.from_dict({**scatter_spec.to_dict(), "files": parts})
    from_file = ScatterSpec.from_dict(
        {**scatter_spec.to_dict(), "files": {c: [str(single)] for c in parts}}
    )
    assert_frame_equal(aggregate(from_folder).bins, aggregate(from_file).bins)
