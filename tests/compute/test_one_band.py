"""Tests of the one band: the x axis of a graph whose X is empty (`ddviz.shared.scatter.ONE_BAND`)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import polars as pl
import pytest

from ddviz.compute.aggregate import COUNT, INDEX, aggregate
from ddviz.compute.scan import scan_columns
from ddviz.compute.selection import selection_columns, selection_filter
from ddviz.shared.scatter import ONE_BAND, ScatterSpec, Selection, View


@pytest.fixture
def band_spec(scatter_spec: ScatterSpec) -> ScatterSpec:
    """Return `scatter_spec` with box plots of y in one band, a series per color, and no points."""
    return replace(
        scatter_spec,
        files={**scatter_spec.files, ONE_BAND: []},
        x=[ONE_BAND],
        col=None,
        categorical=[ONE_BAND],
        hover=["y", "label", "color"],
        points=False,
        box=True,
    )


def _drawn(frame: pl.DataFrame) -> pl.DataFrame:
    """Return the rows of `frame` a box plot of y by color draws, with their row index."""
    return frame.with_row_index(INDEX).filter(
        pl.col("color").is_not_null(), pl.col("y").is_finite()
    )


def test_the_scan_makes_the_one_band_without_files(scatter_spec: ScatterSpec) -> None:
    """The one band is an empty text on every row, in the order asked for."""
    files = {
        "y": scatter_spec.files["y"],
        ONE_BAND: [],
        "color": scatter_spec.files["color"],
    }
    frame = scan_columns(files, INDEX).collect()
    assert frame.columns == [INDEX, "y", ONE_BAND, "color"]
    assert frame[ONE_BAND].unique().to_list() == [""]


def test_one_band_holds_a_box_per_series(
    band_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """The band has one level, and a box per series matching numpy's quartiles."""
    agg = aggregate(band_spec)
    assert agg.axis_levels == {ONE_BAND: [""]}
    assert agg.x_ranges == [(-0.5, 0.5)]
    (pair,) = agg.boxes
    assert (pair.x, pair.y) == (ONE_BAND, "y")
    rows = _drawn(scatter_frame)
    assert [b[:4] for b in pair.stats] == [[0, 0, 0, s] for s in range(3)]
    for *_, series, n, low, q1, median, q3, high in pair.stats:
        values = rows.filter(pl.col("color") == ["a", "b", "c"][series])["y"]
        q = np.quantile(values.to_numpy(), [0.25, 0.5, 0.75])
        assert n == len(values)
        assert [q1, median, q3] == pytest.approx(q, rel=1e-12)
        assert low <= q1 and high >= q3
    assert agg.bins[COUNT].sum() > 0


def test_one_band_with_points_draws_every_row(
    band_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """With the points, every row is drawn in the band, under the boxes."""
    agg = aggregate(replace(band_spec, points=True))
    assert len(agg.piles) == 1
    assert agg.bins[COUNT].sum() == _drawn(scatter_frame).height


def test_a_selection_in_one_band_takes_the_rows_in_its_y_range(
    band_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """Without points, a box over part of the band selects every row whose y is in it."""
    overview = aggregate(band_spec)
    view = View(
        x_ranges=[list(r) for r in overview.x_ranges],
        y_ranges=[list(r) for r in overview.y_ranges],
        levels=overview.all_levels,
        axis_levels=overview.axis_levels,
        boxes=overview.boxes,
    )
    box = Selection(x=ONE_BAND, y="y", x_range=[-0.1, 0.1], y_range=[-0.5, 0.5])
    spec = replace(band_spec, view=view, selection=box)
    found = (
        scan_columns({c: spec.files[c] for c in selection_columns(spec)}, INDEX)
        .filter(*selection_filter(spec, INDEX))
        .collect()
    )
    expected = _drawn(scatter_frame).filter(pl.col("y").is_between(-0.5, 0.5))
    assert 0 < found.height
    assert found[INDEX].to_list() == expected[INDEX].to_list()
