"""Tests of the hover lookup on the files a plot task writes."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute.raster import occupancy
from ddviz.compute.tasks.images import gradient_grays
from ddviz.compute.tasks.plot import run_plot
from ddviz.server.hover import HOVER_DISTANCE, HoverIndex
from ddviz.shared.keys import BinGrid
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import ScatterSpec
from ddviz.shared.shapes import kernel


@pytest.fixture
def index(tmp_path: Path, scatter_spec: ScatterSpec) -> Iterator[HoverIndex]:
    """Run the plot task on the small dataset and open its hover files."""
    out = tmp_path / "task"
    out.mkdir()
    run_plot(scatter_spec, out, lambda _: None)
    opened = HoverIndex(out)
    yield opened
    opened.close()


def _occupied(index: HoverIndex, panel: int, min_series: int) -> tuple[int, int]:
    """Return a pixel of a panel with at least `min_series` series."""
    for by, bx in np.argwhere(index._occupancy[panel]):
        if len(index._series_at(panel, int(by), int(bx))) >= min_series:
            return int(bx), int(by)
    raise AssertionError(f"no pixel with {min_series} series")


def test_lookup_on_a_point_follows_the_layer_order(index: HoverIndex) -> None:
    """On a shared pixel the first series of `order` wins, with the pixel's total count."""
    bx, by = _occupied(index, 0, 2)
    present = list(index._series_at(0, by, bx))
    for order in ([2, 1, 0], [0, 1, 2]):
        hit = index.lookup(0, bx + 0.5, by + 0.5, 1.0, 1.0, order)
        assert hit["series"] == next(s for s in order if s in present)
        assert (hit["bx"], hit["by"]) == (bx, by)
        assert hit["pixel_count"] >= hit["count"] >= 1
        assert hit["values"]["color"] == "abc"[hit["series"]]
        assert hit["values"]["facet"] == "p"


def test_lookup_snaps_to_the_nearest_point_within_the_hover_distance(
    index: HoverIndex,
) -> None:
    """Off any point, the nearest occupied pixel within 20px answers; farther, nothing."""
    occ = index._occupancy[0]
    empty = np.argwhere(occ == 0)
    by, bx = empty[len(empty) // 2]
    hit = index.lookup(0, bx + 0.5, by + 0.5, 1.0, 1.0, [2, 1, 0])
    ys, xs = np.nonzero(occ)
    d2 = (xs - bx) ** 2 + (ys - by) ** 2
    if d2.min() <= HOVER_DISTANCE**2:
        assert (hit["bx"] - bx) ** 2 + (hit["by"] - by) ** 2 == d2.min()
    else:
        assert hit is None
    # Far outside the panel, nothing is near.
    assert index.lookup(0, -1000.0, -1000.0, 1.0, 1.0, [2, 1, 0]) is None


def test_lookup_scales_the_hover_distance_by_pixels_per_bin(index: HoverIndex) -> None:
    """Zoomed in so that a bin spans 30px, a cursor one bin off a point finds nothing."""
    bx, by = _occupied(index, 0, 1)
    occ = index._occupancy[0]
    # A neighbor that is empty, so the cursor is off every point.
    for dx in (1, -1):
        if 0 <= bx + dx < occ.shape[1] and occ[by, bx + dx] == 0:
            fx = bx + dx + 0.5
            assert index.lookup(0, fx, by + 0.5, 30.0, 30.0, [2, 1, 0]) is None
            assert index.lookup(0, fx, by + 0.5, 1.0, 1.0, [2, 1, 0]) is not None
            return
    pytest.skip("no empty neighbor next to the chosen pixel")


def _run(tmp_path: Path, spec: ScatterSpec, hover_bytes: int | None) -> Path:
    """Run the plot task with a limit on its hover files; return its directory."""
    out = tmp_path / f"task-{hover_bytes}"
    out.mkdir()
    run_plot(replace(spec, hover_bytes=hover_bytes), out, lambda _: None)
    return out


def _hover_files(out: Path) -> int:
    """Return the bytes of the hover files in a task's directory."""
    return sum(f.stat().st_size for f in out.glob("*.npy"))


def test_hover_bytes_records_the_hover_files(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """Without a limit every column is written, and the manifest has their bytes."""
    out = _run(tmp_path, scatter_spec, None)
    manifest = PlotManifest.read(out)
    assert manifest.hover_files
    assert manifest.hover_dropped == []
    assert [c.name for c in manifest.columns] == scatter_spec.hover
    assert manifest.hover_bytes == _hover_files(out)


def test_a_limit_leaves_out_columns_off_the_axes(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A limit just under all the files drops the last column off the axes."""
    full = PlotManifest.read(_run(tmp_path, scatter_spec, None)).hover_bytes
    out = _run(tmp_path, scatter_spec, full - 1)
    manifest = PlotManifest.read(out)
    assert manifest.hover_dropped == ["facet"]
    assert [c.name for c in manifest.columns] == ["x", "y", "label", "color"]
    assert manifest.hover_bytes == _hover_files(out) <= full - 1
    index = HoverIndex(out)
    bx, by = _occupied(index, 0, 1)
    values = index.lookup(0, bx + 0.5, by + 0.5, 1.0, 1.0, [2, 1, 0])["values"]
    assert list(values) == ["x", "y", "label", "color"]
    index.close()


def test_without_room_for_the_axes_no_hover_files_are_written(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """When even x and y do not fit, the result has no hover files and no hover."""
    out = _run(tmp_path, scatter_spec, 1)
    manifest = PlotManifest.read(out)
    assert not manifest.hover_files
    assert manifest.hover_dropped == scatter_spec.hover
    assert manifest.hover_bytes == 0
    assert list(out.glob("*.npy")) == []
    assert any(manifest.images)
    index = HoverIndex(out)
    assert index.lookup(0, 1.5, 1.5, 1.0, 1.0, [2, 1, 0]) is None
    index.close()


def _overlay_index(
    points: list[tuple[int, int, int]], colors: list[float] | None = None
) -> HoverIndex:
    """Return an index of one panel of 30 x 20 bins, one color and two overlay levels (a circle and a square of 7px).

    Each point ``(series, bx, by)`` is a bin of one row, whose index is the
    point's position in `points`; with `colors`, a gradient over [0, 1]
    colors them.
    """
    index = HoverIndex.__new__(HoverIndex)
    index.grid = BinGrid(n_panels=1, n_series=2, width=30, height=20)
    packed = [index.grid.pack(0, s, by, bx) for s, bx, by in points]
    order = np.argsort(packed)
    index._keys = np.array(packed)[order]
    index._count = np.ones(len(points), dtype=np.uint32)
    index._index = order.astype(np.int64)
    index._occupancy = occupancy(index._keys, index.grid)
    index._columns = []
    index._shapes = [kernel(i, 7)[::-1] for i in range(2)]
    index._grays = None
    if colors is not None:
        index._grays = gradient_grays(pl.Series(colors), (0.0, 1.0))[order]
    return index


def test_lookup_finds_the_topmost_marker_shape_over_the_cursor() -> None:
    """A square drawn on top of a point's bin answers there; with the order reversed, the point does."""
    index = _overlay_index([(0, 10, 10), (1, 13, 10)])
    # The square of series 1 (the second shape) covers bin (10, 10) with its left side.
    hit = index.lookup(0, 10.5, 10.5, 1.0, 1.0, [1, 0])
    assert (hit["series"], hit["bx"], hit["by"]) == (1, 13, 10)
    assert hit["pixel_count"] == 1
    hit = index.lookup(0, 10.5, 10.5, 1.0, 1.0, [0, 1])
    assert (hit["series"], hit["bx"], hit["by"]) == (0, 10, 10)
    # Inside the square's outline, no shape covers the cursor: the nearest point answers.
    hit = index.lookup(0, 12.5, 10.5, 1.0, 1.0, [1, 0])
    assert (hit["bx"], hit["by"]) == (13, 10)


def test_lookup_of_overlapping_shapes_of_one_series_finds_the_one_drawn() -> None:
    """Of one series, a point's own bin shows over a neighbor's shape, and else a gradient's larger gray does."""
    index = _overlay_index([(1, 10, 10), (1, 13, 10)], colors=[0.8, 0.04])
    hit = index.lookup(0, 10.5, 10.5, 1.0, 1.0, [1, 0])
    assert (hit["row"], hit["bx"]) == (0, 10)
    # Two squares cover the empty bin (10, 10): the larger gray shows there.
    index = _overlay_index([(1, 7, 10), (1, 13, 10)], colors=[0.8, 0.04])
    hit = index.lookup(0, 10.5, 10.5, 1.0, 1.0, [1, 0])
    assert (hit["row"], hit["bx"]) == (0, 7)
    index = _overlay_index([(1, 7, 10), (1, 13, 10)], colors=[0.04, 0.8])
    assert index.lookup(0, 10.5, 10.5, 1.0, 1.0, [1, 0])["row"] == 1


def test_lookup_picks_the_drawn_gray_without_the_color_column(tmp_path: Path) -> None:
    """With the color column left out of the hover files, the larger gray still shows where two shapes of a series overlap."""

    def plot(x: list[float], name: str, hover_bytes: int | None = None) -> Path:
        """Plot two squares of a series (rows 0 and 1, the first grayer) at `x`, and two corner points."""
        path = tmp_path / f"{name}.parquet"
        pl.DataFrame(
            {
                "x": [*x, 0.0, 29.0],
                "y": [10.0, 10.0, 0.0, 19.0],
                "c": [0.8, 0.04, 0.5, 0.5],
                # Level q is the second shape, a square outline.
                "o": ["q", "q", "p", "p"],
            }
        ).write_parquet(path)
        # The last hover column goes first.
        columns = ["x", "y", "o", "c"]
        spec = ScatterSpec(
            files={c: [str(path)] for c in columns},
            x=["x"],
            y=["y"],
            color="c",
            row=None,
            col=None,
            width=400,
            height=300,
            hover=columns,
            gradient=True,
            overlay="o",
            hover_bytes=hover_bytes,
        )
        out = tmp_path / name
        out.mkdir()
        run_plot(spec, out, lambda _: None)
        return out

    first = PlotManifest.read(plot([7.0, 8.0], "first"))
    (lo, hi), width = first.x_ranges[0], first.grid.width
    # Squares 3 bins to a side, 6 bins apart: their sides share bin 103.
    x = [lo + (b + 0.5) * (hi - lo) / width for b in (100, 106)]
    full = PlotManifest.read(plot(x, "full"))
    # Too little room for every column: the color column is left out.
    index = HoverIndex(plot(x, "task", full.hover_bytes - 1))
    try:
        assert index.manifest.hover_dropped == ["c"]
        _, _, by, bx = index.grid.unpack(np.asarray(index._keys))
        assert sorted(bx.tolist())[1:3] == [100, 106]
        y0 = int(by[bx == 100][0])
        hit = index.lookup(0, 103.5, y0 + 0.5, 1.0, 1.0, [1, 0])
        assert (hit["row"], hit["bx"]) == (0, 100)
    finally:
        index.close()
