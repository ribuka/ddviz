"""Tests of the expressions that read columns from one source file."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ddviz.compute.sourceread import file_values
from ddviz.shared.generated import generated_value
from ddviz.shared.tasks import SourceFiles


def test_file_values_give_each_column_in_the_input_type(tmp_path: Path) -> None:
    """An added column gives the file's value, a lacking column nulls, another type a cast, the same type the values."""
    path = tmp_path / "part.parquet"
    pl.DataFrame(
        {"n": pl.Series([1, 2, 3], dtype=pl.Int32), "label": ["a", "b", "c"]}
    ).write_parquet(path)
    source = SourceFiles(
        [str(path)],
        [3],
        "",
        {"n": "Int64", "label": "String", "x": "Float64"},
        {"source": "source", "filename": "filename"},
    )
    target = {"n": pl.Int64, "x": pl.Float64}
    columns = ["filename", "label", "x", "n", "source"]
    scan = pl.scan_parquet(path)

    values = file_values(source, str(path), columns, scan.collect_schema(), target)
    found = scan.select(*values.values()).collect()

    assert list(values) == columns
    assert found.schema == pl.Schema(
        {
            "filename": pl.String,
            "label": pl.String,
            "x": pl.Float64,
            "n": pl.Int64,
            "source": pl.String,
        }
    )
    assert found["source"].to_list() == [generated_value("source", str(path))] * 3
    assert found["filename"].to_list() == ["part"] * 3
    assert found["label"].to_list() == ["a", "b", "c"]
    assert found["x"].to_list() == [None] * 3
    assert found["n"].to_list() == [1, 2, 3]
