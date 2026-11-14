"""Tests of the task that writes the rows of a plot as a file to save."""

from __future__ import annotations

import io
import itertools
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute.tasks import plotdata
from ddviz.compute.tasks.columns import run_schema
from ddviz.compute.tasks.plot import run_plot
from ddviz.compute.tasks.plotdata import index_name, run_plot_data
from ddviz.shared.cache import SCHEMA
from ddviz.shared.inputs import parquet_files
from ddviz.shared.manifest import PlotManifest, read_manifest
from ddviz.shared.scatter import Filter, ScatterSpec
from ddviz.shared.tasks import PlotDataTask, SourceFiles

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
    """Small chunks write the same rows and values as one, each chunk adding to ``done`` until ``total``."""
    whole = _export(tmp_path, scatter_spec, file_format=file_format)
    monkeypatch.setattr(plotdata, "FIRST_CHUNK_ROWS", 7)
    monkeypatch.setattr(plotdata, "MAX_CHUNK_ROWS", 7)
    messages: list[dict] = []
    chunked = _export(
        tmp_path, scatter_spec, file_format=file_format, messages=messages
    )
    assert chunked.equals(whole)
    assert all(m["export"] == "token" and m["stage"] == "export" for m in messages)
    assert "total" not in messages[0]
    done = [m["done"] for m in messages[1:]]
    assert done[0] == 0
    assert done == sorted(done)
    assert len(done) == -(-whole.height // 7) + 1
    assert done[-1] == messages[-1]["total"] == whole.height


def test_long_texts_make_chunks_of_fewer_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A column of 1 KiB texts keeps each chunk after the first within the bytes of a chunk."""
    n = 2_000
    frame = pl.DataFrame(
        {
            "x": [float(i) for i in range(n)],
            "y": [1.0] * n,
            "s": [f"{i:04d}" + "w" * 1020 for i in range(n)],
        }
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
    monkeypatch.setattr(plotdata, "FIRST_CHUNK_ROWS", 10)
    messages: list[dict] = []
    saved = _export(tmp_path, spec, messages=messages)
    assert saved.drop("index").equals(frame)
    done = [m["done"] for m in messages[1:]]
    sizes = [b - a for a, b in itertools.pairwise(done)]
    assert sizes[0] == 10
    # 64 KiB holds fewer than 64 rows of more than 1 KiB each.
    assert 0 < max(sizes[1:]) < 64
    assert sum(sizes) == n


def test_no_rows_give_the_columns_alone(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A filter that keeps no row gives a file of the columns and no row."""
    spec = replace(scatter_spec, filters=[Filter("facet", levels=["none"])])
    for file_format in ("parquet", "csv"):
        saved = _export(tmp_path, spec, rows="filtered", file_format=file_format)
        assert saved.height == 0
        assert saved.columns == ["index", *scatter_spec.files]
