"""Tests of the local filter: aggregation, selection and table follow it; the levels and ranges do not."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.aggregate import COUNT, INDEX, KEY, aggregate
from ddviz.manifest import read_manifest
from ddviz.scatter import Filter, ScatterSpec, Selection, View
from ddviz.summary import MAX_FILTER_LEVELS, summarize_column
from ddviz.task import run_table

FILTERS = [Filter("facet", levels=["q"]), Filter("x", range=[-1.0, 0.5])]


@pytest.fixture
def filtered(scatter_spec: ScatterSpec) -> ScatterSpec:
    """Return `scatter_spec` with facet q and x in [-1, 0.5] kept."""
    return replace(scatter_spec, filters=FILTERS)


def _kept(frame: pl.DataFrame) -> pl.DataFrame:
    """Return the drawn rows of `frame` that pass `FILTERS`, with their indices."""
    return frame.with_row_index(INDEX).filter(
        pl.col("x").is_finite(),
        pl.col("y").is_finite(),
        pl.col("color").is_not_null(),
        pl.col("facet") == "q",
        pl.col("x").is_between(-1.0, 0.5),
    )


def test_filter_keeps_the_levels_and_ranges_and_bins_only_its_rows(
    scatter_spec: ScatterSpec, filtered: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """The panels, series and axes stay those of every row; the bins hold the kept rows."""
    whole = aggregate(scatter_spec)
    agg = aggregate(filtered)
    assert agg.levels == whole.levels
    assert agg.x_ranges == whole.x_ranges
    assert agg.y_ranges == whole.y_ranges
    assert agg.grid == whole.grid
    kept = _kept(scatter_frame)
    assert agg.bins[COUNT].sum() == kept.height
    assert set(agg.bins[INDEX].to_list()) <= set(kept[INDEX].to_list())
    # The panel of facet p has no rows left.
    panels, *_ = agg.grid.unpack(agg.bins[KEY].to_numpy())
    assert set(panels.tolist()) == {1}


def test_selection_and_table_follow_the_filter(
    tmp_path: Path, filtered: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A box selects only the rows the filter keeps; the table lists them."""
    overview = aggregate(filtered)
    spec = replace(
        filtered,
        view=View(
            x_ranges=[list(r) for r in overview.x_ranges],
            y_ranges=[list(r) for r in overview.y_ranges],
            levels=overview.levels,
        ),
        selection=Selection(x="x", y="y", x_range=[-3.0, 3.0], y_range=[0.0, 3.0]),
    )
    agg = aggregate(spec, selection_only=True)
    rows = _kept(scatter_frame).filter(pl.col("y").is_between(0.0, 3.0))
    assert agg.selected_rows == rows.height
    assert agg.selected[COUNT].sum() == rows.height

    out = tmp_path / "page"
    out.mkdir()
    run_table(spec, 0, 1000, {"label": spec.files["label"]}, out, lambda _: None)
    assert read_manifest(out)["index"] == rows[INDEX].to_list()


def test_summary_of_a_numeric_column(
    scatter_path: Path, scatter_frame: pl.DataFrame
) -> None:
    """A numeric column's summary is its finite minimum and maximum and its null count."""
    summary = summarize_column(str(scatter_path), "x")
    finite = scatter_frame["x"].filter(scatter_frame["x"].is_finite())
    assert summary == {
        "rows": scatter_frame.height,
        "nulls": 1,
        "min": finite.min(),
        "max": finite.max(),
        "numeric": True,
        "integer": False,
    }


def test_summary_of_a_categorical_column(
    scatter_path: Path, scatter_frame: pl.DataFrame
) -> None:
    """A categorical column's summary is its levels with their counts, nulls apart."""
    summary = summarize_column(str(scatter_path), "color")
    counts = scatter_frame["color"].drop_nulls().value_counts().sort("color")
    assert summary["numeric"] is False
    assert summary["nulls"] == 1
    assert summary["n_levels"] == 3
    assert summary["levels"] == [list(r) for r in counts.iter_rows()]


def test_summary_leaves_out_the_levels_of_a_column_with_too_many(
    tmp_path: Path,
) -> None:
    """A column with about one level per row lists no levels."""
    path = tmp_path / "ids.parquet"
    n = MAX_FILTER_LEVELS * 3
    pl.DataFrame({"id": [f"id{i}" for i in range(n)]}).write_parquet(path)
    summary = summarize_column(str(path), "id")
    assert summary["levels"] is None
    assert summary["n_levels"] > MAX_FILTER_LEVELS
