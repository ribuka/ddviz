"""Tests of the task that writes the rows of a plot as a file to save."""

from __future__ import annotations

import io
import itertools
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow.parquet as pq
import pytest
from polars.testing import assert_frame_equal

from ddviz.compute.tasks import plotdata
from ddviz.compute.tasks.columns import run_schema
from ddviz.compute.tasks.plot import run_plot
from ddviz.compute.tasks.plotdata import index_name, run_plot_data
from ddviz.compute.tasks.table import run_table
from ddviz.server.derive import box_selection, selection_spec
from ddviz.shared.cache import SCHEMA
from ddviz.shared.inputs import parquet_files
from ddviz.shared.manifest import PlotManifest, read_manifest
from ddviz.shared.scatter import Filter, ScatterSpec
from ddviz.shared.tasks import PlotDataTask, SourceFiles, TableTask

# Every column in the cache: no source file is read.
NO_SOURCE = SourceFiles([], [], "", {}, {})
# The value of a temporal column, without a time zone.
AT = datetime.fromisoformat("2026-01-02T03:04:05")


def _export(
    tmp_path: Path,
    spec: ScatterSpec,
    rows: str = "drawn",
    columns: list[str] | None = None,
    source: SourceFiles = NO_SOURCE,
    file_format: str = "parquet",
    messages: list[dict] | None = None,
) -> pl.DataFrame:
    """Draw a spec, write its rows as a file and return the file read back.

    Without `columns`, the spec's columns, all read from the cache.
    """
    result = tmp_path / "plot"
    result.mkdir(exist_ok=True)
    run_plot(spec, result, lambda _: None)
    if columns is None:
        columns = list(spec.files)
    parts = {c: spec.files[c] for c in columns if c in spec.files}
    out = tmp_path / f"data-{len(list(tmp_path.glob('data-*')))}"
    out.mkdir()
    task = PlotDataTask(
        str(result), file_format, rows, columns, parts, source, "token"
    )
    run_plot_data(task, out, (messages if messages is not None else []).append)
    file = out / read_manifest(out)["file"]
    assert sorted(p.name for p in out.iterdir()) == sorted(["manifest.json", file.name])
    if file_format == "csv":
        content = file.read_bytes()
        assert content.startswith("﻿".encode())
        return pl.read_csv(io.BytesIO(content), try_parse_dates=True)
    return pl.read_parquet(file)


def _halved(file_format: str, value: int) -> int:
    """Return a chunk's bytes or rows at most of a format: those of a CSV, half of them for Parquet."""
    return value // 2 if file_format == "parquet" else value


def _indexed(frame: pl.DataFrame) -> pl.DataFrame:
    """Return a frame with its row index first, as the file names it."""
    return frame.with_row_index("index")


def test_drawn_rows_are_those_the_plot_draws(
    tmp_path: Path, scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """The drawn rows leave out a null or infinite x, a null color and the rows the filter leaves; the count is the plot's."""
    spec = replace(scatter_spec, filters=[Filter("facet", levels=["p"])])
    saved = _export(tmp_path, spec)
    expected = _indexed(scatter_frame).filter(
        pl.col("x").is_finite(),
        pl.col("y").is_finite(),
        pl.col("color").is_not_null(),
        pl.col("facet") == "p",
    )
    assert saved.equals(expected)
    assert "null-color" not in saved["label"]
    assert saved.height == PlotManifest.read(tmp_path / "plot").rows

    # A color whose missing rows are drawn keeps them.
    shown = _export(tmp_path, replace(spec, null_roles=["color"]))
    assert "null-color" in shown["label"]
    assert "null-x" not in shown["label"]


def test_filtered_rows_are_those_the_filter_keeps(
    tmp_path: Path, scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """All filtered rows keep the null and infinite values; without a filter, every row."""
    spec = replace(scatter_spec, filters=[Filter("facet", levels=["p"])])
    saved = _export(tmp_path, spec, rows="filtered")
    assert saved.equals(_indexed(scatter_frame).filter(pl.col("facet") == "p"))
    assert {"null-x", "inf-x", "null-color"} <= set(saved["label"])
    every = _export(tmp_path, scatter_spec, rows="filtered")
    assert every.equals(_indexed(scatter_frame))


@pytest.mark.parametrize("file_format", ["csv", "parquet"])
def test_selected_rows_are_those_the_selection_table_lists(
    tmp_path: Path, scatter_frame: pl.DataFrame, file_format: str
) -> None:
    """The selected rows are the table's rows, once each in row order, with the columns asked after the row index."""
    frame = scatter_frame.with_columns(x2=pl.col("x") * 0.5 + pl.col("y"))
    path = tmp_path / "pairs.parquet"
    frame.write_parquet(path, row_group_size=500)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x", "x2"],
        y=["y"],
        color="color",
        row=None,
        col=None,
        width=400,
        height=300,
        hover=["x", "x2", "y", "color"],
        filters=[Filter("facet", levels=["p"])],
    )
    result = tmp_path / "plot"
    result.mkdir()
    run_plot(spec, result, lambda _: None)
    manifest = PlotManifest.read(result)
    # The box on the panel of x2.
    selected = selection_spec(manifest, box_selection(manifest, 1, (-1.0, 1.5), (-0.5, 2.0)))

    table = []
    while True:
        page = tmp_path / f"page-{len(table)}"
        page.mkdir()
        task = TableTask(selected, len(table), 100, [], {}, NO_SOURCE)
        run_table(task, page, lambda _: None)
        rows = read_manifest(page)["index"]
        table += rows
        if len(rows) < 100:
            break
    assert 100 < len(table) < frame.height

    columns = ["x", "x2", "label"]
    out = tmp_path / "data"
    out.mkdir()
    task = PlotDataTask(
        str(result),
        file_format,
        "selected",
        columns,
        {c: selected.files[c] for c in columns},
        NO_SOURCE,
        "token",
        selected,
    )
    run_plot_data(task, out, lambda _: None)
    file = out / read_manifest(out)["file"]
    if file_format == "csv":
        saved = pl.read_csv(file)
    else:
        saved = pl.read_parquet(file)
    assert saved.columns == ["index", *columns]
    assert saved["index"].to_list() == table
    assert_frame_equal(
        saved, _indexed(frame).select("index", *columns)[table], check_dtypes=False
    )


def test_a_log_axis_draws_only_its_positive_rows(tmp_path: Path) -> None:
    """On a log x, a row whose x is 0 or negative is not drawn."""
    frame = pl.DataFrame({"x": [-1.0, 0.0, 1e-3, 1.0, 1e3], "y": [1.0] * 5})
    path = tmp_path / "log.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=300,
        height=200,
        hover=["x", "y"],
        log_x=["x"],
    )
    saved = _export(tmp_path, spec)
    assert saved["index"].to_list() == [2, 3, 4]


def test_a_row_on_several_panels_is_saved_once(tmp_path: Path) -> None:
    """With two x columns, a row drawn on either panel is one row of the file."""
    frame = pl.DataFrame(
        {
            "a": [1.0, None, None, 4.0],
            "b": [None, 2.0, None, 4.0],
            "y": [1.0, 2.0, 3.0, 4.0],
        }
    )
    path = tmp_path / "two.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["a", "b"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=300,
        height=200,
        hover=["a", "b", "y"],
    )
    assert _export(tmp_path, spec)["index"].to_list() == [0, 1, 3]


def test_the_columns_are_those_listed_after_the_row_index(
    tmp_path: Path, scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """The file has the row index, then the columns in their order; a column named index pushes it to index_2."""
    saved = _export(tmp_path, scatter_spec, columns=["y", "color"])
    assert saved.columns == ["index", "y", "color"]

    frame = scatter_frame.with_columns(
        pl.int_range(pl.len()).mul(10).alias("index"),
        pl.datetime(2026, 1, 2, 3, 4, 5).alias("at"),
    )
    path = tmp_path / "indexed.parquet"
    frame.write_parquet(path)
    spec = replace(
        scatter_spec,
        files={c: [str(path)] for c in frame.columns},
        hover=list(frame.columns),
    )
    for file_format in ("parquet", "csv"):
        saved = _export(
            tmp_path, spec, rows="filtered", columns=list(frame.columns),
            file_format=file_format,
        )
        assert saved.columns == ["index_2", *frame.columns]
        assert saved["index_2"].to_list() == list(range(frame.height))
        assert saved["index"].to_list() == frame["index"].to_list()
        # A temporal column keeps its values: a type in Parquet, text in CSV.
        assert saved.schema["at"] == pl.Datetime("us")
        assert saved["at"].unique().to_list() == [AT]
    assert index_name(["index", "index_2"]) == "index_3"


def test_all_columns_of_a_folder_are_cast_or_null(
    tmp_path: Path,
    scatter_spec: ScatterSpec,
    folder_path: Path,
    folder_frame: pl.DataFrame,
) -> None:
    """Columns read from the files of a folder take the input's type; a file lacking one gives nulls; a generated column its file's value."""
    single = tmp_path / "single.parquet"
    folder_frame.write_parquet(single)
    spec = replace(scatter_spec, files={c: [str(single)] for c in scatter_spec.files})
    files = parquet_files([folder_path])
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    run_schema([str(f) for f in files], schema_dir, lambda _: None)
    found = read_manifest(schema_dir)
    dtypes = {c["name"]: c["dtype"] for c in found["columns"]}
    source = SourceFiles(
        [str(f) for f in files],
        found["rows"],
        str(schema_dir / SCHEMA),
        {"n": dtypes["n"], "label": dtypes["label"], "file": "String"},
        {"file": "filename"},
    )
    saved = _export(
        tmp_path, spec, rows="filtered", columns=["x", "n", "label", "file"],
        source=source,
    )
    assert saved.columns == ["index", "x", "n", "label", "file"]
    assert saved.schema["n"] == pl.Int64
    assert saved["n"].to_list() == folder_frame["n"].to_list()
    assert saved["label"].to_list() == folder_frame["label"].to_list()
    assert saved["file"].unique(maintain_order=True).to_list() == [
        f.stem for f in files
    ]


@pytest.mark.parametrize("file_format", ["parquet", "csv"])
def test_chunks_write_the_same_file_and_report_progress(
    tmp_path: Path,
    scatter_spec: ScatterSpec,
    monkeypatch: pytest.MonkeyPatch,
    file_format: str,
) -> None:
    """Small chunks write the same rows and values as one; ``done`` adds up the rows of the chunks until ``total``.

    A Parquet file's chunks take half the rows, and ``done`` counts those
    the sink received: once for each chunk and at the end, as for a CSV.
    """
    whole = _export(tmp_path, scatter_spec, file_format=file_format)
    monkeypatch.setattr(plotdata, "MAX_CHUNK_ROWS", 14)
    messages: list[dict] = []
    chunked = _export(
        tmp_path, scatter_spec, file_format=file_format, messages=messages
    )
    assert chunked.equals(whole)
    assert all(m["export"] == "token" and m["stage"] == "export" for m in messages)
    assert "total" not in messages[0]
    done = [m["done"] for m in messages[1:]]
    rows = _halved(file_format, 14)
    assert whole.height > 2 * rows
    # One message when the rows are counted, then one for each chunk.
    assert done == [*range(0, whole.height, rows), whole.height]
    assert all(m["total"] == whole.height for m in messages[1:])


@pytest.mark.parametrize("file_format", ["parquet", "csv"])
@pytest.mark.parametrize("short", [0, 10])
def test_long_texts_make_chunks_of_fewer_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, short: int, file_format: str
) -> None:
    """A column of 1 KiB texts keeps every chunk within the bytes of a chunk (half for Parquet), also after `short` rows of short texts."""
    n = 2_000
    texts = [f"{i:04d}" + ("" if i < short else "w" * 1020) for i in range(n)]
    frame = pl.DataFrame(
        {"x": [float(i) for i in range(n)], "y": [1.0] * n, "s": texts}
    )
    path = tmp_path / "texts.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=300,
        height=200,
        hover=list(frame.columns),
    )
    monkeypatch.setattr(plotdata, "CHUNK_BYTES", 64 * 2**10)
    budget = _halved(file_format, 64 * 2**10)
    messages: list[dict] = []
    saved = _export(tmp_path, spec, file_format=file_format, messages=messages)
    assert saved.drop("index").equals(frame)
    done = [m["done"] for m in messages[1:]]
    row_bytes = [4 * plotdata.VALUE_BYTES + len(t) for t in texts]
    chunks = [row_bytes[a:b] for a, b in itertools.pairwise(done)]
    assert sum(len(c) for c in chunks) == n
    assert all(0 < sum(c) <= budget for c in chunks)
    # Each chunk ends where the next row would not fit.
    assert all(sum(c) + nxt[0] > budget for c, nxt in itertools.pairwise(chunks))


def test_a_row_group_of_many_columns_is_within_the_first_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Parquet file of many columns has row groups of at most the rows of the first chunk, and the same rows and values."""
    n = 500
    frame = pl.DataFrame(
        {"x": [float(i) for i in range(n)], "y": [1.0] * n}
        | {f"c{j}": [float(i * j) for i in range(n)] for j in range(100)}
    )
    path = tmp_path / "wide.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=300,
        height=200,
        hover=list(frame.columns),
    )
    monkeypatch.setattr(plotdata, "CHUNK_BYTES", 64 * 2**10)
    messages: list[dict] = []
    saved = _export(tmp_path, spec, rows="filtered", messages=messages)
    assert saved.drop("index").equals(frame)
    # Before the second chunk, the rows of the first.
    first = messages[2]["done"]
    assert 0 < first < n
    (file,) = tmp_path.glob("data-*/data.parquet")
    meta = pq.ParquetFile(file).metadata
    groups = [meta.row_group(i).num_rows for i in range(meta.num_row_groups)]
    assert sum(groups) == n
    assert max(groups) <= first


def _texts_spec(tmp_path: Path, texts: list[str]) -> tuple[pl.DataFrame, ScatterSpec]:
    """Return a frame of x, y and the texts `s`, written as a file, and a spec that draws it with every column."""
    n = len(texts)
    frame = pl.DataFrame({"x": [float(i) for i in range(n)], "y": [1.0] * n, "s": texts})
    path = tmp_path / "texts.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["x"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=300,
        height=200,
        hover=list(frame.columns),
    )
    return frame, spec


def _groups(tmp_path: Path) -> list[tuple[int, int]]:
    """Return the first row and the rows of each row group of the only Parquet file written."""
    (file,) = tmp_path.glob("data-*/data.parquet")
    meta = pq.ParquetFile(file).metadata
    rows = [meta.row_group(i).num_rows for i in range(meta.num_row_groups)]
    return list(zip(itertools.accumulate(rows[:-1], initial=0), rows, strict=True))


def test_a_row_group_of_long_texts_after_short_ones_is_within_a_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Texts of 1 KiB after short ones keep every row group of a Parquet file within half the bytes of a chunk, as the chunks after the first are."""
    texts = ["a"] * 992 + ["w" * 1024] * 1_984
    frame, spec = _texts_spec(tmp_path, texts)
    monkeypatch.setattr(plotdata, "CHUNK_BYTES", 64 * 2**10)
    saved = _export(tmp_path, spec, rows="filtered")
    assert saved.drop("index").equals(frame)
    groups = _groups(tmp_path)
    assert sum(rows for _, rows in groups) == len(texts)
    # The row index, x, y and the offset of s, besides the longest s.
    estimates = [
        rows * (4 * plotdata.VALUE_BYTES + max(map(len, texts[start : start + rows])))
        for start, rows in groups
    ]
    assert max(estimates) <= 32 * 2**10
    # The first chunk holds 992 rows, the others 31: row groups of 31 rows.
    assert {rows for _, rows in groups[:-1]} == {31}


def test_a_row_group_across_two_chunks_is_within_a_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Long texts at the end of a chunk and the start of the next keep a row group across the two within half the bytes of a chunk."""
    lengths = [1, 1, 1, 31_968, 15_968, 7_968, 7_968, 15_968, 7_968, 7_968]
    texts = [f"{i}" + "w" * (n - 1) for i, n in enumerate(lengths)]
    frame, spec = _texts_spec(tmp_path, texts)
    monkeypatch.setattr(plotdata, "CHUNK_BYTES", 64 * 2**10)
    messages: list[dict] = []
    saved = _export(tmp_path, spec, rows="filtered", messages=messages)
    assert saved.drop("index").equals(frame)
    done = [m["done"] for m in messages[1:]]
    # Chunks of 4, 3 and 3 rows: a row group of 3 rows would hold rows 3 to 5.
    assert [b - a for a, b in itertools.pairwise(done)] == [4, 3, 3]
    row_bytes = [4 * plotdata.VALUE_BYTES + n for n in lengths]
    groups = _groups(tmp_path)
    assert sum(rows for _, rows in groups) == len(texts)
    assert max(sum(row_bytes[a : a + rows]) for a, rows in groups) <= 32 * 2**10


def test_row_groups_of_their_most_rows_are_not_rows_far_larger() -> None:
    """Chunks of the same rows, more than `PARQUET_ROW_GROUP_ROWS`, take row groups of those rows, not a row group for each chunk."""
    rows = plotdata.PARQUET_ROW_GROUP_ROWS
    # 100 million rows of 7 numbers: 24 chunks, 96 row groups.
    sizes = [4 * rows] * 23 + [100_000_000 - 23 * 4 * rows]
    assert plotdata._row_group_rows(sizes, rows) == rows
    # One row far larger than the others: a row group for each chunk.
    assert plotdata._row_group_rows([1_000, 1, *[1_000] * 10], rows) is None


def test_runs_across_two_chunks_are_kept_within_the_budget() -> None:
    """`_across` gives the most rows of which every run across the end of a chunk is within the budget."""
    before = np.array([1, 1, 1, 10])
    after = np.array([10, 1, 1, 1])
    # Runs of 3 rows: 1 + 10 + 10 and 10 + 10 + 1; of 2 rows: 10 + 10.
    assert plotdata._across(before, after, 3, 21) == 3
    assert plotdata._across(before, after, 3, 20) == 2
    assert plotdata._across(before, after, 3, 19) == 1
    # Of the same bytes, every run of the rows of a chunk fits.
    assert plotdata._across(np.full(8, 4), np.full(8, 4), 8, 32) == 8


def test_a_row_far_larger_than_the_others_makes_a_row_group_for_each_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A text larger than a chunk among short ones writes a row group for each chunk, not one for each row."""
    texts = ["a"] * 3_000
    texts[1_500] = "w" * 40_000
    frame, spec = _texts_spec(tmp_path, texts)
    monkeypatch.setattr(plotdata, "CHUNK_BYTES", 64 * 2**10)
    messages: list[dict] = []
    saved = _export(tmp_path, spec, rows="filtered", messages=messages)
    assert saved.drop("index").equals(frame)
    done = [m["done"] for m in messages[1:]]
    chunks = [b - a for a, b in itertools.pairwise(done)]
    # The long text is a chunk of its own.
    assert 1 in chunks[:-1]
    assert [rows for _, rows in _groups(tmp_path)] == chunks


@pytest.mark.parametrize(
    "nested",
    [
        lambda text: [text],
        lambda text: {"s": text, "n": 1},
        lambda text: [{"s": text}],
    ],
    ids=["list", "struct", "list-of-struct"],
)
def test_texts_inside_nested_values_count_in_a_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nested: Callable
) -> None:
    """A column of all columns read from the source files, nesting 1 KiB texts in lists or structs, keeps every chunk of a Parquet file within half the bytes of a chunk."""
    n = 2_000
    frame = pl.DataFrame(
        {
            "x": [float(i) for i in range(n)],
            "y": [1.0] * n,
            "t": [nested(f"{i:04d}" + "w" * 1020) for i in range(n)],
        }
    )
    path = tmp_path / "nested.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in ("x", "y")},
        x=["x"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=300,
        height=200,
        hover=["x", "y"],
    )
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    run_schema([str(path)], schema_dir, lambda _: None)
    found = read_manifest(schema_dir)
    dtypes = {c["name"]: c["dtype"] for c in found["columns"]}
    source = SourceFiles(
        [str(path)], found["rows"], str(schema_dir / SCHEMA), {"t": dtypes["t"]}, {}
    )
    monkeypatch.setattr(plotdata, "CHUNK_BYTES", 64 * 2**10)
    messages: list[dict] = []
    saved = _export(
        tmp_path, spec, columns=["x", "y", "t"], source=source, messages=messages
    )
    assert saved.drop("index").equals(frame)
    done = [m["done"] for m in messages[1:]]
    sizes = [b - a for a, b in itertools.pairwise(done)]
    assert sum(sizes) == n
    # A row holds more than 1 KiB of text: half of 64 KiB holds fewer than
    # 32, and more than 1 KiB and 64 bytes at least 30.
    assert 30 <= max(sizes) < 32


def test_no_rows_give_the_columns_alone(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A filter that keeps no row gives a file of the columns and no row."""
    spec = replace(scatter_spec, filters=[Filter("facet", levels=["none"])])
    for file_format in ("parquet", "csv"):
        saved = _export(tmp_path, spec, rows="filtered", file_format=file_format)
        assert saved.height == 0
        assert saved.columns == ["index", *scatter_spec.files]


def test_an_error_reading_a_chunk_comes_out_as_it_is(
    tmp_path: Path, scatter_spec: ScatterSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error reading the second chunk of a Parquet file comes out of the task with its own type."""
    monkeypatch.setattr(plotdata, "MAX_CHUNK_ROWS", 14)
    cached = plotdata._cached
    calls: list[int] = []

    def failing(*args: object, measure: bool = False) -> pl.DataFrame:
        """Read the first chunk's values, then fail."""
        if not measure:
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("out of memory")
        return cached(*args, measure=measure)

    monkeypatch.setattr(plotdata, "_cached", failing)
    with pytest.raises(RuntimeError, match="out of memory"):
        _export(tmp_path, scatter_spec)
    assert len(calls) == 2


def _nested_spec(
    tmp_path: Path, frame: pl.DataFrame, read_from: str = "source"
) -> tuple[ScatterSpec, SourceFiles]:
    """Return a spec that draws the x and y of a frame, written as a file, and the source to read its other columns from.

    With `read_from` ``"cache"``, every column is in the spec's files, as
    the column cache holds them, and no source file is read.
    """
    path = tmp_path / "nested.parquet"
    frame.write_parquet(path)
    cache = list(frame.columns) if read_from == "cache" else ["x", "y"]
    spec = ScatterSpec(
        files={c: [str(path)] for c in cache},
        x=["x"],
        y=["y"],
        color=None,
        row=None,
        col=None,
        width=300,
        height=200,
        hover=["x", "y"],
    )
    if read_from == "cache":
        return spec, NO_SOURCE
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    run_schema([str(path)], schema_dir, lambda _: None)
    found = read_manifest(schema_dir)
    dtypes = {
        c["name"]: c["dtype"] for c in found["columns"] if c["name"] not in cache
    }
    source = SourceFiles(
        [str(path)], found["rows"], str(schema_dir / SCHEMA), dtypes, {}
    )
    return spec, source


def _export_csv(
    tmp_path: Path,
    frame: pl.DataFrame,
    read_from: str = "source",
    rows: str = "filtered",
    messages: list[dict] | None = None,
) -> bytes:
    """Write every column of a frame as a CSV (`_nested_spec`) and return its bytes after the BOM."""
    spec, source = _nested_spec(tmp_path, frame, read_from)
    _export(
        tmp_path,
        spec,
        rows=rows,
        columns=list(frame.columns),
        source=source,
        file_format="csv",
        messages=messages,
    )
    (file,) = tmp_path.glob("data-*/data.csv")
    return file.read_bytes().removeprefix("﻿".encode())


@pytest.mark.parametrize("read_from", ["source", "cache"])
@pytest.mark.parametrize("rows", ["drawn", "filtered"])
def test_nested_columns_are_written_as_json(
    tmp_path: Path, read_from: str, rows: str
) -> None:
    """Lists, structs, arrays and lists of structs are written to a CSV as their JSON, which reads back as the values; a null value is an empty cell."""
    frame = pl.DataFrame(
        {
            "x": [0.0, 1.0, 2.0, 3.0],
            "y": [1.0] * 4,
            "li": [[1, 2], [], None, [3]],
            "st": [
                {"a": 1, "b": 'x,"y'},
                {"a": None, "b": "z"},
                None,
                {"a": 2, "b": ""},
            ],
            "ar": [[3.0, None], [1.0, 2.0], None, [0.5, -1.0]],
            "ls": [[{"s": "a"}], [], None, [{"s": None}, None]],
        },
        schema_overrides={"ar": pl.Array(pl.Float64, 2)},
    )
    content = _export_csv(tmp_path, frame, read_from, rows)
    saved = pl.read_csv(io.BytesIO(content), infer_schema=False)
    assert saved.columns == ["index", *frame.columns]
    for c in ("li", "st", "ar", "ls"):
        dtype = frame.schema[c]
        if isinstance(dtype, pl.Array):
            dtype = pl.List(dtype.inner)
        assert saved[c].str.json_decode(dtype).equals(frame[c].cast(dtype)), c
    lines = content.decode().splitlines()
    # No whitespace in the JSON; the row of null values is empty cells.
    assert lines[1] == (
        '0,0.0,1.0,"[1,2]","{""a"":1,""b"":""x,\\""y""}","[3.0,null]","[{""s"":""a""}]"'
    )
    assert lines[2].startswith("1,1.0,1.0,[],")
    assert lines[3] == "2,2.0,1.0,,,,"


@pytest.mark.parametrize("read_from", ["source", "cache"])
def test_binary_values_are_written_as_hexadecimal(
    tmp_path: Path, read_from: str
) -> None:
    """A binary value, outside or inside a nested value, is its lowercase hexadecimal text; a null value is an empty cell, an empty binary and an empty list are not."""
    frame = pl.DataFrame(
        {
            "x": [0.0, 1.0, 2.0],
            "y": [1.0] * 3,
            "b": [b"\x00a\xff", None, b""],
            "lb": [[b"\x01", None], None, []],
            "sb": [{"k": b"\x02", "n": 1}, None, {"k": None, "n": 2}],
            "ab": [[b"\x03", b"\x04"], None, [None, b""]],
        },
        schema_overrides={"ab": pl.Array(pl.Binary, 2)},
    )
    content = _export_csv(tmp_path, frame, read_from)
    assert content.decode().splitlines() == [
        "index,x,y,b,lb,sb,ab",
        '0,0.0,1.0,0061ff,"[""01"",null]","{""k"":""02"",""n"":1}","[""03"",""04""]"',
        "1,1.0,1.0,,,,",
        '2,2.0,1.0,"",[],"{""k"":null,""n"":2}","[null,""""]"',
    ]


def test_nan_and_infinity_inside_a_nested_value_are_null(tmp_path: Path) -> None:
    """A NaN or an infinity inside a list is null in its JSON."""
    frame = pl.DataFrame(
        {"x": [0.0], "y": [1.0], "lf": [[float("nan"), float("inf"), 1.5]]}
    )
    content = _export_csv(tmp_path, frame)
    assert content.decode().splitlines()[1] == '0,0.0,1.0,"[null,null,1.5]"'


@pytest.mark.parametrize("nested", [True, False], ids=["nested", "flat"])
def test_a_chunk_with_nested_values_is_written_in_pieces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nested: bool
) -> None:
    """A chunk with a nested column is written in pieces of at most 1/16 of its rows, the BOM and header in the first alone, as a chunk at once writes it; ``done`` counts the chunks. Without one, a chunk is written at once."""
    n = 2_000
    frame = pl.DataFrame(
        {
            "x": [float(i) for i in range(n)],
            "y": [1.0] * n,
            "v": [list(range(i, i + 10)) for i in range(n)] if nested else [0.5] * n,
        }
    )
    (tmp_path / "whole").mkdir()
    whole = _export_csv(tmp_path / "whole", frame)
    monkeypatch.setattr(plotdata, "CHUNK_BYTES", 32 * 2**10)
    calls: list[tuple[int, bool, bool]] = []
    write_csv = pl.DataFrame.write_csv

    def recording(
        self: pl.DataFrame,
        file: object = None,
        *,
        include_bom: bool = False,
        include_header: bool = True,
        **kwargs: object,
    ) -> str | None:
        """Record the rows written, and whether with the BOM and the header."""
        calls.append((self.height, include_bom, include_header))
        return write_csv(
            self, file, include_bom=include_bom, include_header=include_header, **kwargs
        )

    monkeypatch.setattr(pl.DataFrame, "write_csv", recording)
    messages: list[dict] = []
    chunked = _export_csv(tmp_path, frame, messages=messages)
    assert chunked == whole
    done = [m["done"] for m in messages[1:]]
    sizes = [b - a for a, b in itertools.pairwise(done)]
    assert done[0] == 0
    assert sum(sizes) == n
    assert len(sizes) >= 2
    assert [(bom, header) for _, bom, header in calls] == [(True, True)] + [
        (False, False)
    ] * (len(calls) - 1)
    pieces = [rows for rows, _, _ in calls]
    if not nested:
        assert pieces == sizes
        return
    # The pieces of each chunk, in order.
    left = iter(pieces)
    for size in sizes:
        written = 0
        while written < size:
            rows = next(left)
            assert rows <= -(-size // plotdata.JSON_PIECES)
            written += rows
        assert written == size
    assert next(left, None) is None


def test_no_rows_with_nested_columns_give_the_header_alone(tmp_path: Path) -> None:
    """A filter that keeps no row writes the header of the nested and binary columns alone."""
    frame = pl.DataFrame({"x": [0.0], "y": [1.0], "li": [[1]], "b": [b"\x01"]})
    spec, source = _nested_spec(tmp_path, frame)
    saved = _export(
        tmp_path,
        replace(spec, filters=[Filter("x", range=[5.0, 6.0])]),
        rows="filtered",
        columns=list(frame.columns),
        source=source,
        file_format="csv",
    )
    assert saved.height == 0
    assert saved.columns == ["index", "x", "y", "li", "b"]
