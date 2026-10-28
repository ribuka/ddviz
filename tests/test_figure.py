"""Tests of the plotly figure built from a plot task's manifest."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ddviz.figure import build_figure
from ddviz.manifest import IMAGES, read_manifest
from ddviz.scatter import ScatterSpec, View
from ddviz.task import run_plot

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _figure(spec: ScatterSpec, out: Path) -> dict:
    """Run the plot task and build its figure."""
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    return build_figure(read_manifest(out))


def test_images_are_slices_of_one_file(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """The meta locates each series' PNG in the images file; plotly gets no image."""
    result = _figure(scatter_spec, tmp_path / "task")
    images = (tmp_path / "task" / IMAGES).read_bytes()
    spans = [s for s in result["meta"]["images"] if s is not None]
    assert len(spans) == len(result["meta"]["series"])
    pngs = [images[start : start + length] for start, length in spans]
    assert all(
        p.startswith(PNG_SIGNATURE) and p.endswith(b"IEND\xaeB`\x82") for p in pngs
    )
    assert sum(len(p) for p in pngs) == len(images)
    assert {t["type"] for t in result["figure"]["data"]} == {"scatter"}


def test_every_panel_and_series_has_an_empty_trace(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """One trace per series carries its legend item; one per panel keeps its axes."""
    result = _figure(scatter_spec, tmp_path / "task")
    data = result["figure"]["data"]
    legend = [t["legendgroup"] for t in data if "legendgroup" in t]
    assert legend == [f"s{s}" for s in range(len(result["meta"]["series"]))]
    empty = [t for t in data if "legendgroup" not in t]
    assert [(t["xaxis"], t["yaxis"]) for t in empty] == [
        (p["xaxis"], p["yaxis"]) for p in result["meta"]["panels"]
    ]


def test_a_panel_without_rows_keeps_its_axes(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A view where no row falls has no image, and every panel keeps its axes."""
    overview = read_manifest(_overview_dir(tmp_path, scatter_spec))
    view = replace(
        scatter_spec,
        view=View(
            x_range=[50.0, 60.0], y_range=[50.0, 60.0], levels=overview["levels"]
        ),
    )
    result = _figure(view, tmp_path / "view")
    data = result["figure"]["data"]
    assert all(s is None for s in result["meta"]["images"])
    empty = [t for t in data if t["type"] == "scatter" and "legendgroup" not in t]
    assert [(t["xaxis"], t["yaxis"]) for t in empty] == [
        (p["xaxis"], p["yaxis"]) for p in result["meta"]["panels"]
    ]
    assert result["meta"]["x_range"] == [50.0, 60.0]
    assert result["figure"]["layout"]["xaxis"]["range"] == [50.0, 60.0]


def _overview_dir(tmp_path: Path, spec: ScatterSpec) -> Path:
    """Run the overview plot task and return its directory."""
    out = tmp_path / "overview"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    return out


def test_a_scrolled_grid_labels_every_panel(
    tmp_path: Path, scatter_spec: ScatterSpec
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
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A grid that fits labels the y ticks of the first column only."""
    big = replace(scatter_spec, width=800, height=400)
    result = _figure(big, tmp_path / "task")
    layout = result["figure"]["layout"]
    assert not result["meta"]["scroll"]
    assert layout["yaxis"]["showticklabels"]
    assert not layout["yaxis2"]["showticklabels"]
