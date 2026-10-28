"""Tests of the plotly figure built from a plot task's manifest."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ddviz.figure import build_figure
from ddviz.manifest import IMAGES, read_manifest
from ddviz.spec import PlotSpec
from ddviz.task import run_plot

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _figure(spec: PlotSpec, out: Path) -> dict:
    """Run the plot task and build its figure, with each image's PNG as its source."""
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    images = (out / IMAGES).read_bytes()
    return build_figure(
        read_manifest(out), lambda span: images[span[0] : span[0] + span[1]]
    )


def test_images_are_slices_of_one_file(tmp_path: Path, scatter_spec: PlotSpec) -> None:
    """Every image trace's source is a whole PNG cut from the images file."""
    figure = _figure(scatter_spec, tmp_path / "task")["figure"]
    sources = [t["source"] for t in figure["data"] if t["type"] == "image"]
    assert len(sources) == 2 * 3
    assert all(
        s.startswith(PNG_SIGNATURE) and s.endswith(b"IEND\xaeB`\x82") for s in sources
    )


def test_a_panel_without_rows_keeps_its_axes(
    tmp_path: Path, scatter_spec: PlotSpec
) -> None:
    """A view where no row falls gets one empty trace per panel, so plotly draws the axes."""
    overview = read_manifest(_overview_dir(tmp_path, scatter_spec))
    view = replace(
        scatter_spec,
        x_range=[50.0, 60.0],
        y_range=[50.0, 60.0],
        levels=overview["levels"],
    )
    result = _figure(view, tmp_path / "view")
    data = result["figure"]["data"]
    assert not [t for t in data if t["type"] == "image"]
    empty = [t for t in data if t["type"] == "scatter" and "legendgroup" not in t]
    assert [(t["xaxis"], t["yaxis"]) for t in empty] == [
        (p["xaxis"], p["yaxis"]) for p in result["meta"]["panels"]
    ]
    assert result["meta"]["x_range"] == [50.0, 60.0]
    assert result["figure"]["layout"]["xaxis"]["range"] == [50.0, 60.0]


def _overview_dir(tmp_path: Path, spec: PlotSpec) -> Path:
    """Run the overview plot task and return its directory."""
    out = tmp_path / "overview"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    return out


def test_a_scrolled_grid_labels_every_panel(
    tmp_path: Path, scatter_spec: PlotSpec
) -> None:
    """When the panels are too small for the size, each carries tick labels and a facet title."""
    small = replace(scatter_spec, width=300, height=200)
    result = _figure(small, tmp_path / "task")
    layout = result["figure"]["layout"]
    assert result["meta"]["scroll"]
    assert layout["width"] > 300
    assert all(layout[a]["showticklabels"] for a in ("xaxis", "yaxis2"))
    titles = [a["text"] for a in layout["annotations"]]
    assert "facet = p" in titles
    assert "facet = q" in titles


def test_a_fitting_grid_labels_the_outer_panels(
    tmp_path: Path, scatter_spec: PlotSpec
) -> None:
    """A grid that fits labels the y ticks of the first column only."""
    big = replace(scatter_spec, width=800, height=400)
    result = _figure(big, tmp_path / "task")
    layout = result["figure"]["layout"]
    assert not result["meta"]["scroll"]
    assert layout["yaxis"]["showticklabels"]
    assert not layout["yaxis2"]["showticklabels"]
