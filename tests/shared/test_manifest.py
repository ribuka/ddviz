"""Tests of the typed manifests of plot and selection tasks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ddviz.shared.keys import BinGrid
from ddviz.shared.layout import AxisGrid, grid_layout
from ddviz.shared.manifest import (
    HoverColumn,
    PlotManifest,
    SelectionManifest,
    read_manifest,
)
from ddviz.shared.scatter import Binning, ScatterSpec, Selection, View


def test_plot_manifest_reads_back_what_it_wrote(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A plot manifest with a view, bins and a gradient range reads back equal."""
    levels = {"row": [None], "col": ["p", "q"], "color": [None]}
    spec = replace(
        scatter_spec,
        view=View([[0.0, 1.0]], [[0.0, 2.0]], levels),
        binned={"col": Binning(n=2)},
        gradient=True,
    )
    manifest = PlotManifest(
        spec=spec,
        grid=BinGrid(n_panels=2, n_series=1, width=150, height=200),
        layout=grid_layout(400, 300, 1, 2),
        axes=AxisGrid(1, 2),
        x_ranges=[[0.0, 1.0]],
        y_ranges=[[0.0, 2.0]],
        levels=levels,
        all_levels=levels,
        cuts={"col": {"breaks": [0.0, 0.5, 1.0]}},
        color_range=[-1.0, 1.0],
        colors=["#1f77b4"],
        columns=[HoverColumn("label", "col0.npy", ["r0", "r1"])],
        images=[[0, 10]],
        rows=2000,
    )
    manifest.write(tmp_path)
    assert read_manifest(tmp_path)["kind"] == "plot"
    assert PlotManifest.read(tmp_path) == manifest


def test_selection_manifest_reads_back_what_it_wrote(tmp_path: Path) -> None:
    """A selection manifest reads back equal."""
    manifest = SelectionManifest(
        selection=Selection("x", "y", [0.0, 1.0], [0.0, 1.0], col="p"),
        grid=BinGrid(n_panels=2, n_series=3, width=150, height=200),
        images=[None, [0, 5], [5, 7]],
        rows=12,
    )
    manifest.write(tmp_path)
    assert read_manifest(tmp_path)["kind"] == "selection"
    assert SelectionManifest.read(tmp_path) == manifest
