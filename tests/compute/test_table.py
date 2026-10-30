"""Tests of the selection table's page task."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl

from ddviz.compute.tasks.columns import run_schema
from ddviz.compute.tasks.table import TABLE_GAP, _spans, run_table
from ddviz.shared.cache import SCHEMA
from ddviz.shared.inputs import parquet_files
from ddviz.shared.manifest import read_manifest
from ddviz.shared.scatter import ScatterSpec, Selection
from ddviz.shared.tasks import SourceFiles, TableTask

# A table task whose columns are all in the cache reads no source file.
NO_SOURCE = SourceFiles([], [], "", {})


def test_spans_split_where_rows_are_far_apart() -> None:
    """Close rows share a slice; rows further apart than TABLE_GAP get their own."""
    rows = [3, 5, 10, 10 + TABLE_GAP + 1, 10 + 3 * TABLE_GAP]
    assert _spans(rows) == [
        (3, 8),
        (10 + TABLE_GAP + 1, 1),
        (10 + 3 * TABLE_GAP, 1),
    ]


def test_table_page_lists_the_selected_rows_in_row_order(
    tmp_path: Path, scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A page holds the selected rows from its offset, with the values of the asked columns."""
    spec = replace(
        scatter_spec,
        selection=Selection(
            x="x", y="y", x_range=[-1.0, 1.0], y_range=[0.0, 1.0], col="q"
        ),
    )
    expected = scatter_frame.with_row_index("i").filter(
        pl.col("x").is_between(-1.0, 1.0),
        pl.col("y").is_between(0.0, 1.0),
        pl.col("facet") == "q",
        pl.col("color").is_not_null(),
    )
    out = tmp_path / "page"
    out.mkdir()
    columns = ["label", "x", "facet"]
    parts = {c: spec.files[c] for c in columns}
    run_table(TableTask(spec, 5, 10, columns, parts, NO_SOURCE), out, lambda _: None)
    page = read_manifest(out)
    rows = expected[5:15]
    assert page["index"] == rows["i"].to_list()
    columns = {c["name"]: c["values"] for c in page["columns"]}
    assert list(columns) == ["label", "x", "facet"]
    assert columns["label"] == rows["label"].to_list()
    assert columns["x"] == rows["x"].to_list()
    assert set(columns["facet"]) == {"q"}


def test_table_page_of_no_rows_has_empty_columns(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A selection without rows (its panel left empty by a filter) gives empty columns."""
    spec = replace(
        scatter_spec,
        selection=Selection(
            x="x", y="y", x_range=[50.0, 60.0], y_range=[50.0, 60.0], col="q"
        ),
    )
    task = TableTask(spec, 0, 100, ["x"], {"x": spec.files["x"]}, NO_SOURCE)
    run_table(task, tmp_path, lambda _: None)
    page = read_manifest(tmp_path)
    assert page["index"] == []
    assert page["columns"] == [{"name": "x", "dtype": "Float64", "values": []}]


def test_table_page_reads_columns_from_the_files_of_a_folder(
    tmp_path: Path,
    scatter_spec: ScatterSpec,
    folder_path: Path,
    folder_frame: pl.DataFrame,
) -> None:
    """Columns not in the cache come from the files holding the rows, cast or null."""
    single = tmp_path / "single.parquet"
    folder_frame.write_parquet(single)
    spec = replace(
        scatter_spec,
        files={c: [str(single)] for c in scatter_spec.files},
        selection=Selection(
            x="x", y="y", x_range=[-0.5, 0.5], y_range=[-0.5, 0.5], col="p"
        ),
    )
    files = parquet_files(folder_path)
    run_schema([str(f) for f in files], tmp_path, lambda _: None)
    schema = {c["name"]: c["dtype"] for c in read_manifest(tmp_path)["columns"]}
    source = SourceFiles(
        [str(f) for f in files],
        read_manifest(tmp_path)["rows"],
        str(tmp_path / SCHEMA),
        {c: schema[c] for c in ("n", "label")},
    )
    out = tmp_path / "page"
    out.mkdir()
    task = TableTask(spec, 0, 1000, ["x", "n", "label"], {"x": spec.files["x"]}, source)
    run_table(task, out, lambda _: None)
    page = read_manifest(out)
    rows = folder_frame.with_row_index("i").filter(
        pl.col("x").is_between(-0.5, 0.5),
        pl.col("y").is_between(-0.5, 0.5),
        pl.col("facet") == "p",
        pl.col("color").is_not_null(),
    )
    assert page["index"] == rows["i"].to_list()
    assert {r < 700 for r in page["index"]} == {True, False}
    assert {r >= 1400 for r in page["index"]} == {True, False}
    columns = {c["name"]: c for c in page["columns"]}
    assert list(columns) == ["x", "n", "label"]
    assert columns["n"]["dtype"] == "Int64"
    assert columns["n"]["values"] == rows["n"].to_list()
    assert columns["label"]["values"] == rows["label"].to_list()
    assert None in columns["label"]["values"]
