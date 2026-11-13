"""Tests of the lines joining the points (`ddviz.compute.lines`)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute.aggregate import Aggregation, aggregate
from ddviz.compute.lines import stroke
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
