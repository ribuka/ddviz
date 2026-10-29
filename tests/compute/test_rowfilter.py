"""Tests of the local filter: aggregation, selection and table follow it; the series and ranges do not."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute.aggregate import COUNT, INDEX, KEY, aggregate
from ddviz.compute.summary import MAX_FILTER_LEVELS, summarize_column
from ddviz.compute.task import run_table
from ddviz.shared.manifest import read_manifest
from ddviz.shared.scatter import Filter, ScatterSpec, Selection, View

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


def test_filter_keeps_the_series_and_ranges_and_bins_only_its_rows(
    scatter_spec: ScatterSpec, filtered: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """The series and axes stay those of every row; the panel of facet p, left without rows, goes."""
    whole = aggregate(scatter_spec)
    agg = aggregate(filtered)
    assert agg.levels == {**whole.levels, "col": ["q"]}
    assert agg.all_levels == whole.levels
    assert agg.x_ranges == whole.x_ranges
    assert agg.y_ranges == whole.y_ranges
    assert agg.grid.n_panels == 1
    assert agg.grid.n_series == whole.grid.n_series
    kept = _kept(scatter_frame)
    assert agg.bins[COUNT].sum() == kept.height
    assert set(agg.bins[INDEX].to_list()) <= set(kept[INDEX].to_list())
    panels, *_ = agg.grid.unpack(agg.bins[KEY].to_numpy())
    assert set(panels.tolist()) == {0}


def test_filter_on_another_column_drops_the_facets_it_leaves_empty(
    scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A filter on a column other than the facet's drops the facet levels none of its rows has."""
    labels = scatter_frame.filter(pl.col("facet") == "p")["label"].head(5).to_list()
    agg = aggregate(replace(scatter_spec, filters=[Filter("label", levels=labels)]))
    assert agg.levels["col"] == ["p"]
    assert agg.levels["color"] == ["a", "b", "c"]


def test_filter_without_rows_keeps_every_panel(scatter_spec: ScatterSpec) -> None:
    """A filter that keeps no row leaves the panels of every row, all empty."""
    agg = aggregate(replace(scatter_spec, filters=[Filter("x", range=[50.0, 60.0])]))
    assert agg.levels["col"] == ["p", "q"]
    assert agg.bins.height == 0


def test_view_takes_the_facets_it_is_given(
    filtered: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A view with the facets of its filter draws those panels without finding them again."""
    overview = aggregate(filtered)
    view = View(
        x_ranges=[list(r) for r in overview.x_ranges],
        y_ranges=[list(r) for r in overview.y_ranges],
        levels=overview.all_levels,
    )
    found = aggregate(replace(filtered, view=view))
    assert found.levels == overview.levels
    stages = []
    given = aggregate(
        replace(filtered, view=replace(view, facets={"row": [None], "col": ["q"]})),
        stages.append,
    )
    assert "facets" not in stages
    assert given.levels == overview.levels
    assert given.bins[COUNT].sum() == _kept(scatter_frame).height


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
            levels=overview.all_levels,
            facets={"row": overview.levels["row"], "col": overview.levels["col"]},
        ),
        selection=Selection(
            x="x", y="y", x_range=[-3.0, 3.0], y_range=[0.0, 3.0], col="q"
        ),
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
