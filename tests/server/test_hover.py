"""Tests of the hover lookup on the files a plot task writes."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute.raster import occupancy
from ddviz.compute.tasks.plot import run_plot
from ddviz.server.hover import HOVER_DISTANCE, HoverIndex
from ddviz.shared.keys import BinGrid
from ddviz.shared.manifest import IMAGES, PlotManifest
from ddviz.shared.scatter import ScatterSpec
from ddviz.shared.shapes import marker


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
    """Zoomed in so that a bin spans 30px, a cursor 3 bins off a lone point (off its circle) finds nothing."""
    occ = index._occupancy[0]
    height, width = occ.shape
    for by, bx in np.argwhere(occ):
        if not (3 <= by < height - 3 and 3 <= bx < width - 3):
            continue
        if occ[by - 3 : by + 4, bx - 3 : bx + 4].sum() == 1:
            fx = bx + 3.5
            assert index.lookup(0, fx, by + 0.5, 30.0, 30.0, [2, 1, 0]) is None
            hit = index.lookup(0, fx, by + 0.5, 1.0, 1.0, [2, 1, 0])
            assert (hit["bx"], hit["by"]) == (bx, by)
            return
    pytest.skip("no lone point")


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


def _overlay_index(points: list[tuple[int, int, int]]) -> HoverIndex:
    """Return an index of one panel of 30 x 20 bins, one color and two overlay levels (a circle and a square of 7px).

    Each point ``(series, bx, by)`` is a bin of one row, whose index is the
    point's position in `points`.
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
    index._shapes = [marker(i, 2, 7)[::-1] for i in range(2)]
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


def test_lookup_of_overlapping_shapes_of_one_series_finds_the_largest_row() -> None:
    """Of one series, the point of the largest row is drawn on top, even over another point's own bin."""
    index = _overlay_index([(1, 10, 10), (1, 13, 10)])
    hit = index.lookup(0, 10.5, 10.5, 1.0, 1.0, [1, 0])
    assert (hit["row"], hit["bx"]) == (1, 13)
    index = _overlay_index([(1, 13, 10), (1, 10, 10)])
    hit = index.lookup(0, 10.5, 10.5, 1.0, 1.0, [1, 0])
    assert (hit["row"], hit["bx"]) == (1, 10)
    # Two squares cover the empty bin (10, 10): the larger row shows there.
    index = _overlay_index([(1, 7, 10), (1, 13, 10)])
    assert index.lookup(0, 10.5, 10.5, 1.0, 1.0, [1, 0])["row"] == 1


def test_a_gradient_shows_and_hovers_the_largest_row_where_circles_overlap(
    tmp_path: Path,
) -> None:
    """Without an overlay, points are 5px circles; where two overlap, the later row's gray is drawn and hovered."""
    path = tmp_path / "g.parquet"
    pl.DataFrame(
        {
            "x": [5.0, 5.06, 0.0, 10.0],
            "y": [5.0, 5.0, 0.0, 10.0],
            "c": [0.8, 0.04, 0.5, 0.5],
        }
    ).write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in ("x", "y", "c")},
        x=["x"],
        y=["y"],
        color="c",
        row=None,
        col=None,
        width=400,
        height=300,
        hover=["x", "y", "c"],
        gradient=True,
    )
    out = tmp_path / "task"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    index = HoverIndex(out)
    try:
        _, _, by, bx = index.grid.unpack(np.asarray(index._keys))
        rows = np.asarray(index._index)
        x0, x1 = int(bx[rows == 0][0]), int(bx[rows == 1][0])
        y0 = int(by[rows == 0][0])
        assert 0 < x1 - x0 <= 4
        # Row 1 covers row 0's own bin, as plotly draws it later.
        hit = index.lookup(0, x0 + 0.5, y0 + 0.5, 1.0, 1.0, [0])
        assert (hit["row"], hit["bx"]) == (1, x1)
        layer = _gradient_layer(out, index)
        assert layer[y0, x0] == layer[y0, x1] < 128
    finally:
        index.close()


def _gradient_layer(out: Path, index: HoverIndex) -> np.ndarray:
    """Return the grays of a one-panel gradient's image, row 0 at the bottom."""
    offset, length = index.manifest.images[0]
    png = (out / IMAGES).read_bytes()[offset : offset + length]
    width, height = struct.unpack(">II", png[16:24])
    data = b""
    at = 8
    while at < len(png):
        size, kind = struct.unpack(">I4s", png[at : at + 8])
        if kind == b"IDAT":
            data += png[at + 8 : at + 8 + size]
        at += 12 + size
    raw = np.frombuffer(zlib.decompress(data), dtype=np.uint8).reshape(height, -1)
    # Filter type 0 on every line (`ddviz.compute.png`).
    assert (raw[:, 0] == 0).all()
    return raw[:, 1 : width + 1]
