"""Shared fixtures: a small scatter dataset as a Parquet file."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.shared.scatter import ScatterSpec


@pytest.fixture
def scatter_frame() -> pl.DataFrame:
    """Return 2000 rows with x, y, a label column and two categorical columns, plus a few invalid rows."""
    rng = np.random.default_rng(0)
    n = 2000
    frame = pl.DataFrame(
        {
            "x": rng.normal(0, 1, n),
            "y": rng.normal(0, 1, n),
            "label": [f"r{i}" for i in range(n)],
            "color": rng.choice(["a", "b", "c"], n),
            "facet": rng.choice(["p", "q"], n),
        }
    )
    invalid = pl.DataFrame(
        {
            "x": [None, float("inf"), 0.0],
            "y": [0.0, 0.0, 0.0],
            "label": ["null-x", "inf-x", "null-color"],
            "color": ["a", "a", None],
            "facet": ["p", "p", "p"],
        }
    )
    return pl.concat([frame, invalid])


@pytest.fixture
def scatter_path(tmp_path: Path, scatter_frame: pl.DataFrame) -> Path:
    """Write `scatter_frame` to a Parquet file with several row groups."""
    path = tmp_path / "scatter.parquet"
    scatter_frame.write_parquet(path, row_group_size=500)
    return path


@pytest.fixture
def scatter_spec(scatter_path: Path) -> ScatterSpec:
    """Return a spec plotting `scatter_path` colored by color and faceted by facet."""
    return ScatterSpec(
        files={c: [str(scatter_path)] for c in ["x", "y", "label", "color", "facet"]},
        x=["x"],
        y=["y"],
        color="color",
        row=None,
        col="facet",
        width=400,
        height=300,
        hover=["x", "y", "label", "color", "facet"],
    )


@pytest.fixture
def folder_parts(scatter_frame: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """Return `scatter_frame` split into three files whose columns differ.

    ``n`` is Int32 in the first file and Int64 in the second; the second
    lacks ``label``; the third lacks ``n``. Natural order puts part-10 last.
    """
    n = pl.int_range(pl.len()).alias("n")
    return {
        "part-1.parquet": scatter_frame[:700].with_columns(n.cast(pl.Int32)),
        "part-2.parquet": scatter_frame[700:1400]
        .drop("label")
        .with_columns(n.cast(pl.Int64)),
        "part-10.parquet": scatter_frame[1400:],
    }


@pytest.fixture
def folder_frame(folder_parts: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the rows of `folder_path` as one table, in reading order."""
    return pl.concat(folder_parts.values(), how="diagonal_relaxed")


@pytest.fixture
def folder_path(tmp_path: Path, folder_parts: dict[str, pl.DataFrame]) -> Path:
    """Write `folder_parts` into a folder with a file that is not Parquet."""
    path = tmp_path / "folder"
    path.mkdir()
    for name, part in folder_parts.items():
        part.write_parquet(path / name, row_group_size=300)
    (path / "_SUCCESS").write_bytes(b"")
    return path
