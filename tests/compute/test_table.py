"""Tests of the selection table's page task."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl

from ddviz.compute.task import TABLE_GAP, _spans, run_table
from ddviz.shared.manifest import read_manifest
from ddviz.shared.scatter import ScatterSpec, Selection


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
    files = {c: spec.files[c] for c in ("label", "x", "facet")}
    run_table(spec, 5, 10, files, out, lambda _: None)
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
    run_table(spec, 0, 100, {"x": spec.files["x"]}, tmp_path, lambda _: None)
    page = read_manifest(tmp_path)
    assert page["index"] == []
    assert page["columns"] == [{"name": "x", "dtype": "Float64", "values": []}]
