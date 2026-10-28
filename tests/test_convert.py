"""Tests of converting source columns into per-column files and reading them back."""

from __future__ import annotations

from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from ddviz.aggregate import aggregate
from ddviz.convert import convert_columns
from ddviz.scan import scan_columns
from ddviz.scatter import ScatterSpec


def _convert(source: Path, out: Path, columns: list[str]) -> dict[str, str]:
    """Convert `columns` of `source` into `out` and return the file of each."""
    out.mkdir()
    files = {c: str(out / f"{c}.parquet") for c in columns}
    messages = []
    convert_columns(str(source), files, messages.append)
    assert [(m["column"], m["done"], m["total"]) for m in messages] == [
        (c, i, len(columns)) for i, c in enumerate(columns)
    ]
    return files


def test_converted_columns_read_back_side_by_side(
    scatter_path: Path, scatter_frame: pl.DataFrame, tmp_path: Path
) -> None:
    """Columns from separate files come back in order, with the source's row index."""
    files = _convert(scatter_path, tmp_path / "cache", ["label", "x"])
    assert [p.name for p in (tmp_path / "cache").iterdir()] == [
        "label.parquet",
        "x.parquet",
    ]
    frame = scan_columns(files, row_index="i").collect()
    assert_frame_equal(
        frame, scatter_frame.with_row_index("i").select("i", "label", "x")
    )


def test_aggregate_from_the_cache_matches_the_source(
    scatter_spec: ScatterSpec, tmp_path: Path, scatter_path: Path
) -> None:
    """Aggregating from per-column files gives the same bins as from the source."""
    files = _convert(scatter_path, tmp_path / "cache", list(scatter_spec.files))
    cached = ScatterSpec.from_dict({**scatter_spec.to_dict(), "files": files})
    assert_frame_equal(aggregate(cached).bins, aggregate(scatter_spec).bins)
