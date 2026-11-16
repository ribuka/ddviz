"""Tests of the lines joining the points (`ddviz.compute.lines`)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute.aggregate import Aggregation, aggregate
from ddviz.compute.lines import (
    GROUP,
    LAYER,
    VALUE,
    X,
    Y,
    line_frame,
    line_pixels,
    stroke,
)
from ddviz.compute.tasks.plot import run_plot
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import Filter, ScatterSpec, View

# A panel of this many pixels each way, so that the points lie far apart.
SIZE = 400


def _spec(tmp_path: Path, frame: pl.DataFrame, **kw: object) -> ScatterSpec:
    path = tmp_path / "lines.parquet"
    frame.write_parquet(path)
    spec = {
        "files": {c: [str(path)] for c in frame.columns},
        "x": ["x"],
        "y": ["y"],
        "color": None,
        "row": None,
        "col": None,
        # The margins of the figure come on top of the panel.
        "width": SIZE + 200,
        "height": SIZE + 200,
        "hover": ["x", "y"],
        "line_width": 1,
        "points": False,
        **kw,
    }
    return ScatterSpec(**spec)


def _at(agg: Aggregation, x: float, y: float, panel: int = 0) -> set[int]:
    """Return the pixels around a data point in a panel, as `ddviz.compute.raster.pixels` places them.

    A segment through the point may cover the pixel beside its own.
    """
    (x0, x1), (y0, y1) = agg.x_ranges[0], agg.y_ranges[0]
    w, h = agg.grid.width, agg.grid.height
    bx = min(int((x - x0) / (x1 - x0) * w), w - 1)
    by = min(int((y - y0) / (y1 - y0) * h), h - 1)
    return {
        (panel * h + by + dy) * w + bx + dx for dy in (-1, 0, 1) for dx in (-1, 0, 1)
    }


def _covered(agg: Aggregation, layer: int | None = None) -> set[int]:
    lines = agg.lines
    at = np.ones(len(lines.pixel), bool) if layer is None else lines.layer == layer
    return set(lines.pixel[at].tolist())


def test_rows_are_joined_in_the_order_of_x_then_of_the_row(tmp_path: Path) -> None:
    """Rows are joined in the order of x, rows of one x in their order, never in the file's order."""
    # In the file's order the rows would run (3, 0) -> (1, 10) -> (2, 0) ->
    # (2, 6) -> (1, 0): the lines follow x, and the rows of one x their order.
    frame = pl.DataFrame(
        {"x": [3.0, 1.0, 2.0, 2.0, 1.0], "y": [0.0, 10.0, 0.0, 6.0, 0.0]}
    )
    agg = aggregate(_spec(tmp_path, frame))
    covered = _covered(agg)
    # x = 1: row 1 (y 10), then row 4 (y 0); x = 2: row 2 (y 0), then row 3 (y 6).
    assert covered & _at(agg, 1, 5)  # the rows of x = 1, one above the other
    assert covered & _at(agg, 1.5, 0)  # (1, 0) to (2, 0)
    assert covered & _at(agg, 2, 3)  # the rows of x = 2
    assert covered & _at(agg, 2.5, 3)  # (2, 6) to (3, 0)
    # Not in the file's order: (3, 0) to (1, 10) passes (2, 5).
    assert not covered & _at(agg, 2.5, 2.5)
    # Nor from row 1 (1, 10) to row 2 (2, 0).
    assert not covered & _at(agg, 1.5, 5)


def test_a_missing_y_breaks_the_line_and_a_filtered_row_does_not(
    tmp_path: Path,
) -> None:
    """A null y breaks the line; a row the filter leaves out joins its neighbors."""
    frame = pl.DataFrame(
        {"x": [1.0, 2.0, 3.0], "y": [10.0, None, 30.0], "keep": ["a", "b", "a"]}
    )
    agg = aggregate(_spec(tmp_path, frame))
    assert len(agg.lines.pixel) == 0
    # A row with one valid point is still in the bins: the hover finds it.
    assert agg.bins.height == 2

    filtered = _spec(tmp_path, frame, filters=[Filter("keep", levels=["a"])])
    agg = aggregate(filtered)
    assert _covered(agg) & _at(agg, 2, 20)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_y_not_finite_breaks_the_line_and_an_x_not_finite_leaves_its_row_out(
    tmp_path: Path, bad: float
) -> None:
    """A y not finite breaks the line; an x not finite leaves its row out, joining its neighbors."""
    frame = pl.DataFrame({"x": [1.0, 2.0, 3.0], "y": [10.0, bad, 30.0]})
    assert len(aggregate(_spec(tmp_path, frame)).lines.pixel) == 0
    frame = pl.DataFrame({"x": [1.0, bad, 3.0], "y": [10.0, 20.0, 30.0]})
    agg = aggregate(_spec(tmp_path, frame))
    assert _covered(agg) & _at(agg, 2, 20)


def test_facet_cells_and_color_levels_make_lines_of_their_own(
    tmp_path: Path,
) -> None:
    """Each facet cell and color level has its own line."""
    frame = pl.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 1.0, 4.0],
            "y": [0.0, 0.0, 10.0, 10.0, 10.0, 0.0],
            "c": ["a", "b", "a", "b", "a", "a"],
            "f": ["p", "p", "p", "p", "q", "q"],
        }
    )
    spec = _spec(tmp_path, frame, color="c", col="f", hover=["x", "y", "c", "f"])
    agg = aggregate(spec)
    assert agg.levels["color"] == ["a", "b"]
    a, b = _covered(agg, 0), _covered(agg, 1)
    # Facet p: a joins (1, 0) and (3, 10), b (2, 0) and (4, 10).
    assert a & _at(agg, 2, 5)
    assert b & _at(agg, 3, 5)
    assert not (a | b) & _at(agg, 1.5, 0)
    # Facet q (panel 1): a joins (1, 10) and (4, 0); nothing joins the facets.
    assert a & _at(agg, 2.5, 5, panel=1)
    per_panel = agg.grid.width * agg.grid.height
    assert {p // per_panel for p in b} == {0}
    assert not a & _at(agg, 2.5, 5)


def test_the_symbol_does_not_split_the_lines(tmp_path: Path) -> None:
    """The rows of every symbol level of a color level make one line."""
    frame = pl.DataFrame(
        {"x": [1.0, 2.0, 3.0], "y": [0.0, 10.0, 0.0], "s": ["u", "v", "u"]}
    )
    agg = aggregate(_spec(tmp_path, frame, symbol="s", hover=["x", "y", "s"]))
    covered = _covered(agg, 0)
    assert covered & _at(agg, 1.5, 5)
    assert covered & _at(agg, 2.5, 5)


def test_a_gradient_colors_each_segment_by_the_row_it_starts_from(
    tmp_path: Path,
) -> None:
    """A gradient's segment has the color of the row it starts from."""
    frame = pl.DataFrame(
        {"x": [1.0, 2.0, 3.0], "y": [0.0, 10.0, 0.0], "v": [0.0, 1.0, 0.5]}
    )
    spec = _spec(tmp_path, frame, color="v", gradient=True, hover=["x", "y", "v"])
    agg = aggregate(spec)
    lines = agg.lines
    values = agg.line_values.to_numpy()

    def color(x: float, y: float) -> set[float]:
        at = np.isin(lines.pixel, list(_at(agg, x, y)))
        return set(values[lines.rank[at] - 1].tolist())

    assert color(1.5, 5) == {0.0}
    assert color(2.5, 5) == {1.0}


def test_a_view_draws_the_segments_crossing_it(tmp_path: Path) -> None:
    """A view draws the segment crossing it, cut at its edges, though no row lies in it."""
    frame = pl.DataFrame({"x": [0.0, 10.0, 20.0], "y": [0.0, 10.0, 0.0]})
    spec = _spec(tmp_path, frame)
    overview = aggregate(spec)
    view = View(
        x_ranges=[[4.0, 6.0]],
        y_ranges=[[4.0, 6.0]],
        levels=overview.all_levels,
    )
    agg = aggregate(ScatterSpec(**{**spec.__dict__, "view": view}))
    # No row lies in the view, but the segment (0, 0) to (10, 10) crosses it
    # from corner to corner.
    assert agg.bins.height == 0
    covered = _covered(agg)
    assert covered & _at(agg, 5, 5)
    assert covered & _at(agg, 4.1, 4.1)
    assert covered & _at(agg, 5.9, 5.9)
    assert not covered & _at(agg, 4.1, 5.9)


def test_a_value_without_a_place_on_a_log_axis_breaks_the_line(
    tmp_path: Path,
) -> None:
    """A y not positive on a log axis breaks the line."""
    frame = pl.DataFrame({"x": [1.0, 2.0, 3.0], "y": [10.0, -1.0, 1000.0]})
    agg = aggregate(_spec(tmp_path, frame, log_y=["y"]))
    assert len(agg.lines.pixel) == 0


def test_the_pen_is_a_disk_of_the_width() -> None:
    """The pen of each width is a disk of that width."""
    assert stroke(1).sum() == 1
    assert stroke(2).sum() == 4
    assert stroke(3).sum() == 9
    assert stroke(4).sum() == 12
    assert stroke(5).sum() == 21


def test_lines_without_points_draw_no_point_but_keep_the_hover(
    tmp_path: Path,
) -> None:
    """Lines without points write no point image, but the bins of the hover."""
    frame = pl.DataFrame({"x": [1.0, 2.0, 3.0], "y": [0.0, 10.0, 0.0]})
    out = tmp_path / "out"
    out.mkdir()
    run_plot(_spec(tmp_path, frame, line_width=3), out, lambda _: None)
    manifest = PlotManifest.read(out)
    assert manifest.images == [None]
    assert manifest.line_images[0] is not None
    assert len(np.load(out / "keys.npy")) == 3

    with_points = tmp_path / "with"
    with_points.mkdir()
    run_plot(_spec(tmp_path, frame, points=True), with_points, lambda _: None)
    manifest = PlotManifest.read(with_points)
    assert manifest.images[0] is not None
    assert manifest.line_images[0] is not None


def test_no_lines_without_the_element(tmp_path: Path) -> None:
    """Without the line element, no line image is written."""
    frame = pl.DataFrame({"x": [1.0, 2.0, 3.0], "y": [0.0, 10.0, 0.0]})
    spec = _spec(tmp_path, frame, line_width=None, points=True)
    out = tmp_path / "out"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    assert PlotManifest.read(out).line_images == []


def test_chunks_of_rows_draw_the_same_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rows taken a few at a time cover the pixels of all of them at once, breaks and columns cut between chunks included."""
    rng = np.random.default_rng(1)
    n = 200
    y = rng.normal(size=n)
    y[rng.choice(n, 10, replace=False)] = np.nan
    frame = pl.DataFrame(
        {
            # Few x values: the rows of one pixel column fall in several chunks.
            "x": rng.integers(0, 20, n).astype(float),
            "y": y,
            "c": rng.choice(["a", "b"], n),
        }
    )
    spec = _spec(tmp_path, frame, color="c", hover=["x", "y", "c"])
    whole = aggregate(spec).lines
    monkeypatch.setattr("ddviz.compute.lines.CHUNK_ROWS", 3)
    chunked = aggregate(spec).lines
    for layer in (0, 1):
        assert set(chunked.pixel[chunked.layer == layer].tolist()) == set(
            whole.pixel[whole.layer == layer].tolist()
        )


def _top(agg: Aggregation, x: float, y: float) -> tuple[int, float | None]:
    """Return the layer and the color value of the last segment at the pixel of a data point."""
    (x0, x1), (y0, y1) = agg.x_ranges[0], agg.y_ranges[0]
    w, h = agg.grid.width, agg.grid.height
    bx = min(int((x - x0) / (x1 - x0) * w), w - 1)
    by = min(int((y - y0) / (y1 - y0) * h), h - 1)
    lines = agg.lines
    at = np.flatnonzero(lines.pixel == by * w + bx)
    top = at[np.argmax(lines.rank[at])]
    return int(lines.layer[top]), agg.line_values[int(lines.rank[top]) - 1]


def test_segments_of_one_x_keep_the_colors_of_the_rows_they_start_from(
    tmp_path: Path,
) -> None:
    """Rows of one x make segments one above another, each in the color (and the layer) of its first row, the later one on top."""
    frame = pl.DataFrame(
        {"x": [1.0, 1.0, 1.0], "y": [0.0, 10.0, 9.0], "v": [0.0, 1.0, 0.5]}
    )
    spec = _spec(tmp_path, frame, color="v", gradient=True, hover=["x", "y", "v"])
    agg = aggregate(spec)
    # (1, 0) to (1, 10) starts at v 0; (1, 10) to (1, 9) at v 1, over it.
    assert _top(agg, 1, 5) == (0, 0.0)
    assert _top(agg, 1, 9.5) == (0, 1.0)
    assert _top(agg, 1, 0.2)[1] == 0.0

    frame = frame.with_columns(pl.Series("v", [0.0, None, 0.5]))
    spec = _spec(
        tmp_path,
        frame,
        color="v",
        gradient=True,
        null_roles=["color"],
        hover=["x", "y", "v"],
    )
    agg = aggregate(spec)
    missing = len(agg.levels["color"]) - 1
    assert missing > 0
    # Only the segment from the null row lies in the missing level's layer.
    assert _top(agg, 1, 5)[0] == 0
    assert _top(agg, 1, 9.5)[0] == missing


def test_rows_of_one_pixel_column_cover_it_from_their_least_to_their_largest_y(
    tmp_path: Path,
) -> None:
    """However the segments of one column overlap, their shown parts cover its rows from the least y to the largest, once each."""
    rng = np.random.default_rng(2)
    frame = pl.DataFrame({"x": np.ones(50), "y": rng.uniform(0, 10, 50)})
    agg = aggregate(_spec(tmp_path, frame))
    lines = agg.lines
    (y0, y1), h = agg.y_ranges[0], agg.grid.height
    rows = lines.pixel // agg.grid.width
    lo, hi = (
        int((v - y0) / (y1 - y0) * h) for v in (frame["y"].min(), frame["y"].max())
    )
    assert sorted(rows.tolist()) == list(range(lo, hi + 1))


def test_box_plots_without_points_keep_the_image_of_their_outliers(
    tmp_path: Path,
) -> None:
    """The panels left without points' images are those of lines only: box plots still draw their outliers."""
    frame = pl.DataFrame({"g": ["a"] * 6, "y": [0.0, 0.0, 0.0, 0.0, 0.0, 100.0]})
    spec = _spec(
        tmp_path,
        frame,
        x=["g"],
        categorical=["g"],
        hover=["g", "y"],
        box=True,
        line_width=None,
    )
    out = tmp_path / "out"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    assert PlotManifest.read(out).images[0] is not None


@pytest.mark.parametrize("ys", [[20.0, 30.0], [-30.0, -20.0]])
def test_segments_of_one_column_outside_the_view_draw_nothing(
    tmp_path: Path, ys: list[float]
) -> None:
    """Rows of one pixel column wholly above (or below) the view leave no pixel at its edge."""
    frame = pl.DataFrame({"x": [0.5, 0.5, 0.2, 0.8], "y": [*ys, 5.0, 5.0]})
    spec = _spec(tmp_path, frame)
    overview = aggregate(spec)
    view = View(
        x_ranges=[[0.0, 1.0]], y_ranges=[[0.0, 10.0]], levels=overview.all_levels
    )
    agg = aggregate(ScatterSpec(**{**spec.__dict__, "view": view}))
    # The rows at y 5 make no segment of one column: (0.2, 5) to (0.5, ys[0])
    # and on cross the view; the segment between the rows at x 0.5 does not.
    (x0, x1), w = agg.x_ranges[0], agg.grid.width
    column = int((0.5 - x0) / (x1 - x0) * w)
    rows = agg.lines.pixel // w
    edge = 0 if ys[0] < 0 else agg.grid.height - 1
    at_edge = agg.lines.pixel[(rows == edge)] % w
    assert column not in set(at_edge.tolist())


@pytest.mark.parametrize("xs", [[0.51, 0.59], [0.41, 0.59]])
def test_a_segment_at_the_top_of_the_view_is_drawn_in_its_top_row(
    xs: list[float],
) -> None:
    """A level segment at the top of the y range lies in the top row, within one pixel column or across two."""
    frame = pl.DataFrame(
        {GROUP: [0, 0], X: xs, Y: [10.0, 10.0], LAYER: [0, 0]},
        schema={GROUP: pl.Int32, X: pl.Float64, Y: pl.Float64, LAYER: pl.Int16},
    )
    found = line_pixels(frame, False, False, (0.0, 1.0), (0.0, 10.0), 10, 10, 1)
    assert len(found.pixel) > 0
    assert set((found.pixel // 10).tolist()) == {9}


def _categorical(tmp_path: Path, frame: pl.DataFrame, **kw: object) -> ScatterSpec:
    """Return the spec of lines over a categorical x ``g``."""
    columns = [c for c in frame.columns if c != "keep"]
    return _spec(tmp_path, frame, x=["g"], categorical=["g"], hover=columns, **kw)


@pytest.mark.parametrize("order", [[0, 1, 2, 3], [3, 2, 1, 0], [2, 0, 3, 1]])
def test_a_categorical_x_joins_its_levels_in_their_order_and_the_rows_of_one_in_theirs(
    tmp_path: Path, order: list[int]
) -> None:
    """The bands are joined item_1, item_2, item_10 whatever the file's order; the rows of one level in the order of the rows."""
    rows = pl.DataFrame(
        {"g": ["item_1", "item_2", "item_2", "item_10"], "y": [0.0, 10.0, 0.0, 0.0]}
    )
    agg = aggregate(_categorical(tmp_path, rows[order]))
    assert agg.axis_levels["g"] == ["item_1", "item_2", "item_10"]
    covered = _covered(agg)
    # The rows of item_2, in the order they come in the file.
    first, second = [rows["y"][i] for i in order if i in (1, 2)]
    # item_1 (0) to item_2's first row, item_2's rows, its last to item_10 (2).
    assert covered & _at(agg, 0.5, first / 2)
    assert covered & _at(agg, 1, 5)
    assert covered & _at(agg, 1.5, second / 2)
    assert not covered & _at(agg, 0.5, second / 2)
    # Lines only: no point, and no pile, but the bins of the hover at the
    # centers of the bands.
    assert agg.piles == []
    assert agg.bins.height == 4
    out = tmp_path / "out"
    out.mkdir()
    run_plot(_categorical(tmp_path, rows[order]), out, lambda _: None)
    manifest = PlotManifest.read(out)
    assert manifest.images == [None]
    assert manifest.line_images[0] is not None


def test_a_categorical_x_joins_over_a_level_a_series_has_no_row_of(
    tmp_path: Path,
) -> None:
    """A series without rows at a level joins the levels before and after it."""
    frame = pl.DataFrame(
        {"g": ["a", "b", "c"], "y": [0.0, 10.0, 0.0], "c": ["p", "q", "p"]}
    )
    agg = aggregate(_categorical(tmp_path, frame, color="c"))
    assert _covered(agg, 0) & _at(agg, 1, 0)
    assert not _covered(agg, 1)


def _frame(x: list, y: list, aggregation: str, *, y_log: bool = False) -> pl.DataFrame:
    """Return `line_frame` of rows of one panel and series."""
    rows = pl.LazyFrame({"x": x, "y": y, "i": range(len(x))})
    return line_frame(
        rows,
        "x",
        "y",
        pl.lit(0),
        pl.lit(0),
        1,
        pl.lit(0),
        "i",
        aggregation=aggregation,
        y_log=y_log,
    ).collect()


def test_mean_and_median_make_one_point_of_each_x() -> None:
    """The rows of one x make one point of the mean or the median of their y, the median of an even number the mean of the middle two."""
    x = [2.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0]
    y = [10.0, 3.0, 8.0, 5.0, 1.0, 2.0, 3.0]
    mean = _frame(x, y, "mean")
    assert mean[X].to_list() == [1.0, 2.0]
    assert mean[Y].to_list() == pytest.approx([16 / 3, 4.0])
    assert _frame(x, y, "median")[Y].to_list() == [5.0, 2.5]
    assert _frame(x, y, "raw")[Y].to_list() == [3.0, 8.0, 5.0, 10.0, 1.0, 2.0, 3.0]


@pytest.mark.parametrize("aggregation", ["mean", "median"])
def test_an_aggregation_counts_the_valid_y_and_breaks_at_an_x_without_one(
    aggregation: str,
) -> None:
    """Only finite y count; an x without one keeps a NaN y; an x not finite is left out."""
    x = [1.0, 1.0, 2.0, 2.0, 2.0, 3.0, None, float("nan")]
    y = [None, 4.0, float("nan"), float("inf"), None, 6.0, 1.0, 1.0]
    found = _frame(x, y, aggregation)
    assert found[X].to_list() == [1.0, 2.0, 3.0]
    assert found[Y][0] == 4.0
    assert np.isnan(found[Y][1])
    assert found[Y][2] == 6.0


def test_an_aggregation_on_a_log_axis_counts_the_positive_y_by_their_values() -> None:
    """On a log y, only positive rows count, aggregated as values, not as their logs."""
    x = [1.0, 1.0, 1.0, 2.0]
    y = [-1.0, 10.0, 1000.0, 0.0]
    found = _frame(x, y, "mean", y_log=True)
    assert found[Y][0] == 505.0
    assert np.isnan(found[Y][1])
    assert _frame(x, y, "mean")[Y][0] == pytest.approx(1009 / 3)


@pytest.mark.parametrize("aggregation", ["mean", "median"])
def test_an_aggregated_line_breaks_at_an_x_without_a_valid_y(
    tmp_path: Path, aggregation: str
) -> None:
    """The point of an x without a valid y breaks the line on both sides."""
    frame = pl.DataFrame(
        {"x": [1.0, 2.0, 2.0, 3.0], "y": [0.0, None, float("nan"), 10.0]}
    )
    spec = _spec(tmp_path, frame, line_aggregation=aggregation)
    assert len(aggregate(spec).lines.pixel) == 0
    frame = pl.DataFrame({"x": [1.0, 2.0, 2.0, 3.0], "y": [0.0, None, 4.0, 10.0]})
    agg = aggregate(_spec(tmp_path, frame, line_aggregation=aggregation))
    assert _covered(agg) & _at(agg, 1.5, 2)


def test_an_aggregation_follows_the_filter(tmp_path: Path) -> None:
    """The rows the filter leaves out do not count."""
    frame = pl.DataFrame(
        {"x": [1.0, 1.0, 2.0], "y": [0.0, 10.0, 0.0], "keep": ["a", "b", "a"]}
    )
    agg = aggregate(_spec(tmp_path, frame, line_aggregation="mean"))
    assert _covered(agg) & _at(agg, 1.5, 2.5)
    filtered = _spec(
        tmp_path,
        frame,
        line_aggregation="mean",
        filters=[Filter("keep", levels=["a"])],
    )
    agg = aggregate(filtered)
    covered = _covered(agg)
    assert covered & _at(agg, 1.5, 0)
    assert not covered & _at(agg, 1.5, 2.5)


def test_an_aggregation_keeps_the_facet_cells_and_the_color_levels_apart(
    tmp_path: Path,
) -> None:
    """Each facet cell and color level aggregates its own rows of an x."""
    frame = pl.DataFrame(
        {
            "g": ["a", "a", "b", "b", "a", "b"],
            "y": [0.0, 10.0, 0.0, 10.0, 6.0, 6.0],
            "c": ["p", "q", "p", "q", "p", "p"],
            "f": ["u", "u", "u", "u", "v", "v"],
        }
    )
    spec = _categorical(tmp_path, frame, color="c", row="f", line_aggregation="mean")
    agg = aggregate(spec)
    # Facet u: p at 0, q at 10, never their mean 5; facet v: p at 6.
    assert _covered(agg, 0) & _at(agg, 0.5, 0)
    assert _covered(agg, 1) & _at(agg, 0.5, 10)
    assert not _covered(agg) & _at(agg, 0.5, 5)
    assert _covered(agg, 0) & _at(agg, 0.5, 6, panel=1)
    assert not _covered(agg, 0) & _at(agg, 0.5, 3, panel=0)


def test_a_gradient_colors_an_aggregated_point_by_the_mean_of_its_counted_rows(
    tmp_path: Path,
) -> None:
    """A gradient's point has the mean of the finite colors of the rows its y counts, or the missing color without one."""
    frame = pl.DataFrame(
        {
            "x": [1.0, 1.0, 1.0, 2.0],
            "y": [0.0, 10.0, None, 0.0],
            "v": [0.0, 1.0, 0.9, 0.4],
        }
    )
    spec = _spec(
        tmp_path,
        frame,
        color="v",
        gradient=True,
        hover=["x", "y", "v"],
        line_aggregation="mean",
    )
    agg = aggregate(spec)
    # (1, 5) to (2, 0), in the mean of 0 and 1.
    assert _top(agg, 1.5, 2.5) == (0, 0.5)

    frame = frame.with_columns(pl.Series("v", [None, None, 0.9, 0.4]))
    spec = _spec(
        tmp_path,
        frame,
        color="v",
        gradient=True,
        null_roles=["color"],
        hover=["x", "y", "v"],
        line_aggregation="median",
    )
    agg = aggregate(spec)
    missing = len(agg.levels["color"]) - 1
    assert missing > 0
    assert _top(agg, 1.5, 2.5) == (missing, None)


def test_a_point_without_a_finite_color_of_its_counted_rows_keeps_a_null_value() -> (
    None
):
    """The value of a point is the mean of its counted rows' finite colors only, null without one."""
    rows = pl.LazyFrame(
        {
            "x": [1.0, 1.0, 2.0],
            "y": [1.0, float("nan"), 2.0],
            "v": [float("nan"), 3.0, None],
            "i": [0, 1, 2],
        }
    )
    found = line_frame(
        rows,
        "x",
        "y",
        pl.lit(0),
        pl.lit(0),
        1,
        pl.lit(0),
        "i",
        pl.col("v"),
        aggregation="mean",
    ).collect()
    assert found[VALUE].to_list() == [None, None]


@pytest.mark.parametrize("aggregation", ["mean", "median"])
def test_a_view_aggregates_every_row_before_its_ranges(
    tmp_path: Path, aggregation: str
) -> None:
    """A view joins the points of every row, so that a line from outside it crosses it as in the overview."""
    frame = pl.DataFrame({"x": [0.0, 0.0, 10.0], "y": [-10.0, 10.0, 10.0]})
    spec = _spec(tmp_path, frame, line_aggregation=aggregation)
    overview = aggregate(spec)
    view = View(
        x_ranges=[[4.0, 6.0]],
        y_ranges=[[4.0, 6.0]],
        levels=overview.all_levels,
    )
    agg = aggregate(ScatterSpec(**{**spec.__dict__, "view": view}))
    # (0, 0) to (10, 10) crosses the view; the rows at x 0 lie outside it.
    assert agg.bins.height == 0
    covered = _covered(agg)
    assert covered & _at(agg, 5, 5)
    assert covered & _at(agg, 4.1, 4.1)
