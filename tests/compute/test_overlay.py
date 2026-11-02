"""Tests of the overlay: series of a color and an overlay level, drawn in marker shapes."""

from __future__ import annotations

import struct
import zlib
from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.aggregate import COUNT, KEY, aggregate
from ddviz.compute.raster import atlas, by_series, pixels, series_layer
from ddviz.compute.shapes import spread
from ddviz.compute.tasks.plot import run_plot
from ddviz.server.hover import HoverIndex
from ddviz.shared.manifest import IMAGES, PlotManifest
from ddviz.shared.palette import DEFAULT_COLORS
from ddviz.shared.scatter import ScatterSpec
from ddviz.shared.shapes import SHAPES, marker


def _overlay_spec(spec: ScatterSpec) -> ScatterSpec:
    """Return the small dataset colored by color, with shapes by facet."""
    return replace(spec, col=None, overlay="facet", shape_size=5)


def _decode_mask(png: bytes) -> tuple[np.ndarray, bytes]:
    """Return the pixels and the color of a 1-bit mask PNG."""
    chunks, pos = {}, 8
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        kind = png[pos + 4 : pos + 8]
        chunks[kind] = chunks.get(kind, b"") + png[pos + 8 : pos + 8 + length]
        pos += 12 + length
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    raw = np.frombuffer(zlib.decompress(chunks[b"IDAT"]), np.uint8).reshape(height, -1)
    bits = np.unpackbits(raw[:, 1:], axis=1)[:, :width].astype(bool)
    return bits, chunks[b"PLTE"][3:6]


def test_a_series_is_a_pair_of_a_color_and_an_overlay_level(
    scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """Series ``c * 2 + o`` counts the rows of color level c and overlay level o."""
    agg = aggregate(_overlay_spec(scatter_spec))
    assert agg.levels["color"] == ["a", "b", "c"]
    assert agg.levels["overlay"] == ["p", "q"]
    assert agg.grid.n_series == 6
    _, series, _, _ = agg.grid.unpack(agg.bins[KEY].to_numpy())
    counts = np.bincount(series, weights=agg.bins[COUNT].to_numpy(), minlength=6)
    valid = scatter_frame.filter(
        pl.col("x").is_finite(), pl.col("y").is_finite(), pl.col("color").is_not_null()
    )
    for c, color in enumerate("abc"):
        for o, facet in enumerate("pq"):
            expected = valid.filter(
                (pl.col("color") == color) & (pl.col("facet") == facet)
            ).height
            assert counts[c * 2 + o] == expected


def test_each_series_image_spreads_its_pixels_into_its_shape(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """Series s is drawn in its color level's color and its overlay level's shape."""
    spec = _overlay_spec(scatter_spec)
    run_plot(spec, tmp_path, lambda _: None)
    manifest = PlotManifest.read(tmp_path)
    data = (tmp_path / IMAGES).read_bytes()
    keys = np.load(tmp_path / "keys.npy")
    grid = manifest.grid
    layers = dict(by_series(keys, grid))
    assert sorted(layers) == list(range(6))
    for s, at in layers.items():
        offset, length = manifest.images[s]
        bits, color = _decode_mask(data[offset : offset + length])
        expected = spread(
            series_layer(pixels(keys, grid)[at], grid), marker(SHAPES[s % 2], 5)
        )
        assert np.array_equal(bits, atlas(expected, manifest.layout.ncol))
        assert color == bytes.fromhex(DEFAULT_COLORS[s // 2].removeprefix("#"))
        assert manifest.colors[s] == DEFAULT_COLORS[s // 2]


def test_more_than_64_series_are_drawn_and_hovered(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """Thousands of series (a level per row by two overlay levels) still hover."""
    spec = replace(
        _overlay_spec(scatter_spec),
        color="label",
        width=120,
        height=90,
        max_levels=3000,
    )
    run_plot(spec, tmp_path, lambda _: None)
    index = HoverIndex(tmp_path)
    try:
        assert index.grid.n_series > 64
        by, bx = np.argwhere(index._occupancy[0])[0]
        order = list(reversed(range(index.grid.n_series)))
        hit = index.lookup(0, bx + 0.5, by + 0.5, 1.0, 1.0, order)
        assert hit is not None
        labels = index.manifest.levels["color"]
        assert hit["values"]["label"] == labels[hit["series"] // 2]
        assert hit["values"]["facet"] == "pq"[hit["series"] % 2]
    finally:
        index.close()


def test_an_overlay_level_is_drawn_in_its_own_size(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """The shapes of a level in `shape_sizes` take that size; the other level's, `shape_size`."""
    spec = replace(_overlay_spec(scatter_spec), shape_sizes={"q": 11})
    run_plot(spec, tmp_path, lambda _: None)
    manifest = PlotManifest.read(tmp_path)
    data = (tmp_path / IMAGES).read_bytes()
    keys = np.load(tmp_path / "keys.npy")
    grid = manifest.grid
    for s, at in by_series(keys, grid):
        offset, length = manifest.images[s]
        bits, _ = _decode_mask(data[offset : offset + length])
        size = (5, 11)[s % 2]
        expected = spread(
            series_layer(pixels(keys, grid)[at], grid), marker(SHAPES[s % 2], size)
        )
        assert np.array_equal(bits, atlas(expected, manifest.layout.ncol))


def test_an_overlay_level_is_drawn_in_its_own_shape(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """The points of a level in `level_shapes` take that shape; the other level's, the shape of its place."""
    spec = replace(_overlay_spec(scatter_spec), level_shapes={"q": "triangle-down"})
    run_plot(spec, tmp_path, lambda _: None)
    manifest = PlotManifest.read(tmp_path)
    data = (tmp_path / IMAGES).read_bytes()
    keys = np.load(tmp_path / "keys.npy")
    grid = manifest.grid
    for s, at in by_series(keys, grid):
        offset, length = manifest.images[s]
        bits, _ = _decode_mask(data[offset : offset + length])
        shape = (SHAPES[0], "triangle-down")[s % 2]
        expected = spread(series_layer(pixels(keys, grid)[at], grid), marker(shape, 5))
        assert np.array_equal(bits, atlas(expected, manifest.layout.ncol))
