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
        files={c: str(scatter_path) for c in ["x", "y", "label", "color", "facet"]},
        x=["x"],
        y=["y"],
        color="color",
        row=None,
        col="facet",
        width=400,
        height=300,
        hover=["x", "y", "label", "color", "facet"],
    )
