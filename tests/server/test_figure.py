"""Tests of the plotly figure built from a plot task's manifest."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ddviz.compute.tasks.plot import run_plot
from ddviz.server.figure import FRAME_COLOR, PAPER_COLOR, PLOT_COLOR, build_figure
from ddviz.shared.manifest import IMAGES, PlotManifest
from ddviz.shared.scatter import ScatterSpec, View

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _figure(spec: ScatterSpec, out: Path) -> dict:
    """Run the plot task and build its figure."""
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    return build_figure(PlotManifest.read(out))


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


def test_every_panel_has_an_empty_trace_and_no_legend(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """One empty trace per panel keeps its axes; the page shows the legend."""
    result = _figure(scatter_spec, tmp_path / "task")
    data = result["figure"]["data"]
    assert not result["figure"]["layout"]["showlegend"]
    assert result["meta"]["series"] == ["a", "b", "c"]
    assert [p["facet"] for p in result["meta"]["panels"]] == [[None, "p"], [None, "q"]]
    assert [(t["xaxis"], t["yaxis"]) for t in data] == [
        (p["xaxis"], p["yaxis"]) for p in result["meta"]["panels"]
    ]


def test_a_panel_without_rows_keeps_its_axes(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A view where no row falls has no image, and every panel keeps its axes."""
    overview = PlotManifest.read(_overview_dir(tmp_path, scatter_spec))
    view = replace(
        scatter_spec,
        view=View(
            x_ranges=[[50.0, 60.0]],
            y_ranges=[[50.0, 60.0]],
            levels=overview.all_levels,
        ),
    )
    result = _figure(view, tmp_path / "view")
    data = result["figure"]["data"]
    assert all(s is None for s in result["meta"]["images"])
    assert [(t["xaxis"], t["yaxis"]) for t in data] == [
        (p["xaxis"], p["yaxis"]) for p in result["meta"]["panels"]
    ]
    assert result["meta"]["x_ranges"] == [[50.0, 60.0]]
    assert result["figure"]["layout"]["xaxis"]["range"] == [50.0, 60.0]


def _overview_dir(tmp_path: Path, spec: ScatterSpec) -> Path:
    """Run the overview plot task and return its directory."""
    out = tmp_path / "overview"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    return out


def test_a_scrolled_grid_leaves_its_labels_to_the_page(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """When the panels are too small for the size, plotly draws no tick or facet labels; the meta has the facet labels."""
    small = replace(scatter_spec, width=300, height=200)
    result = _figure(small, tmp_path / "task")
    layout = result["figure"]["layout"]
    assert result["meta"]["scroll"]
    assert layout["width"] > 300
    assert not any(layout[a]["showticklabels"] for a in ("xaxis", "yaxis", "xaxis2"))
    assert layout["annotations"] == []
    titles = [a["text"] for a in result["meta"]["facet_labels"]]
    assert titles == ["facet = p", "facet = q"]


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
    assert layout["annotations"] == result["meta"]["facet_labels"]


def test_the_panels_of_one_axis_column_share_its_axis(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """With two x columns, each facet cell has a panel per column, matched to the column's first axis."""
    two = replace(scatter_spec, x=["x", "y"], width=900, height=400)
    result = _figure(two, tmp_path / "task")
    layout = result["figure"]["layout"]
    meta = result["meta"]
    assert meta["x_axes"] == ["x", "x2"]
    assert meta["y_axes"] == ["y"]
    assert [(p["x"], p["y"]) for p in meta["panels"]] == [
        (0, 0),
        (1, 0),
        (0, 0),
        (1, 0),
    ]
    assert "matches" not in layout["xaxis"]
    assert "matches" not in layout["xaxis2"]
    assert layout["xaxis3"]["matches"] == "x"
    assert layout["xaxis4"]["matches"] == "x2"
    assert layout["xaxis2"]["range"] == meta["x_ranges"][1]
    # The facet label spans the panels of its cell.
    label = next(a for a in layout["annotations"] if a["text"] == "facet = p")
    assert layout["xaxis"]["domain"][1] < label["x"] < layout["xaxis2"]["domain"][0]


def test_every_panel_is_framed_on_a_gray_figure(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """Each plot area is white and framed on all four sides; the figure around it is gray."""
    two = replace(scatter_spec, x=["x", "y"], width=900, height=400)
    layout = _figure(two, tmp_path / "task")["figure"]["layout"]
    assert layout["paper_bgcolor"] == PAPER_COLOR
    assert layout["plot_bgcolor"] == PLOT_COLOR != PAPER_COLOR
    axes = [k for k in layout if k.startswith(("xaxis", "yaxis"))]
    assert len(axes) == 8
    for axis in axes:
        assert layout[axis]["showline"]
        assert layout[axis]["mirror"] is True
        assert layout[axis]["linecolor"] == FRAME_COLOR


def test_facet_labels_center_on_their_panels(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """Each facet label is centered over its panels, wherever it lies."""
    big = replace(scatter_spec, width=800, height=400, row="color")
    labels = _figure(big, tmp_path / "task")["meta"]["facet_labels"]
    cols = [a for a in labels if a.get("textangle") != 90]
    rows = [a for a in labels if a.get("textangle") == 90]
    assert cols and all(a["xanchor"] == "center" for a in cols)
    assert rows and all(a["yanchor"] == "middle" for a in rows)
