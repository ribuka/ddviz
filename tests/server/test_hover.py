"""Tests of the hover lookup on the files a plot task writes."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from ddviz.compute.tasks.plot import run_plot
from ddviz.server.hover import HOVER_DISTANCE, HoverIndex
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import ScatterSpec


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
    occ = index._occupancy[panel]
    counts = np.vectorize(lambda v: int(v).bit_count())(occ)
    by, bx = np.argwhere(counts >= min_series)[0]
    return int(bx), int(by)


def test_lookup_on_a_point_follows_the_layer_order(index: HoverIndex) -> None:
    """On a shared pixel the first series of `order` wins, with the pixel's total count."""
    bx, by = _occupied(index, 0, 2)
    bits = int(index._occupancy[0, by, bx])
    present = [s for s in range(3) if bits >> s & 1]
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


def test_release_removes_the_hover_files(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A released result keeps its manifest and images but finds no row."""
    out = _run(tmp_path, scatter_spec, None)
    index = HoverIndex(out)
    bx, by = _occupied(index, 0, 1)
    index.release()
    assert index.hover_bytes == 0
    assert list(out.glob("*.npy")) == []
    assert (out / "manifest.json").exists()
    assert index.lookup(0, bx + 0.5, by + 0.5, 1.0, 1.0, [2, 1, 0]) is None
