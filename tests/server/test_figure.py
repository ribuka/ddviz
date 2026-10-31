"""Tests of the plotly figure built from a plot task's manifest."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute.tasks.plot import run_plot
from ddviz.server.figure import FRAME_COLOR, PAPER_COLOR, PLOT_COLOR, build_figure
from ddviz.shared.manifest import IMAGES, PlotManifest
from ddviz.shared.scatter import ONE_BAND, ScatterSpec, View

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


def test_a_wrapped_grid_labels_each_panel_with_its_level(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """Three wrapped levels two to a row: three panels, each labeled above by its level alone."""
    wrapped = replace(
        scatter_spec, col="color", wrap=True, wrap_cols=2, width=800, height=600
    )
    result = _figure(wrapped, tmp_path / "task")
    layout, meta = result["figure"]["layout"], result["meta"]
    assert [p["facet"] for p in meta["panels"]] == [
        [None, "a"],
        [None, "b"],
        [None, "c"],
    ]
    assert meta["ncol"] == 2
    assert len(result["figure"]["data"]) == 3
    assert "xaxis4" not in layout
    # The panel above the empty cell shows the x ticks, as the bottom row does.
    assert [layout[a]["showticklabels"] for a in ("xaxis", "xaxis2", "xaxis3")] == [
        False,
        True,
        True,
    ]
    labels = layout["annotations"]
    assert [a["text"] for a in labels] == ["a", "b", "c"]
    assert labels[2]["y"] == layout["yaxis3"]["domain"][1]
    assert layout["yaxis3"]["domain"][1] < layout["yaxis"]["domain"][0]
    assert meta["facet_labels"] == []


def test_a_scrolled_wrapped_grid_keeps_its_labels_in_the_figure(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """The labels between wrapped panels scroll with them: plotly draws them."""
    wrapped = replace(
        scatter_spec, col="color", wrap=True, wrap_cols=1, width=300, height=200
    )
    result = _figure(wrapped, tmp_path / "task")
    assert result["meta"]["scroll"]
    assert [a["text"] for a in result["figure"]["layout"]["annotations"]] == [
        "a",
        "b",
        "c",
    ]
    assert result["meta"]["facet_labels"] == []


def test_a_categorical_axis_ticks_the_middle_of_each_band(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A categorical axis has its levels as tick text at 0, 1, ..., escaped as plotly markup."""
    spec = replace(
        scatter_spec, x=["color"], color=None, categorical=["color"], hover=["color"]
    )
    layout = _figure(spec, tmp_path / "task")["figure"]["layout"]
    for key in ("xaxis", "xaxis2"):
        axis = layout[key]
        assert axis["range"] == [-0.5, 2.5]
        assert axis["tickmode"] == "array"
        assert axis["tickvals"] == [0, 1, 2]
        assert axis["ticktext"] == ["a", "b", "c"]
    assert "tickvals" not in layout["yaxis"]


def test_box_plots_lie_in_the_meta_of_their_panels(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """Each panel holds the boxes of its facet cell, and whether it draws every row's point."""
    spec = replace(
        scatter_spec,
        x=["color"],
        y=["y", "x"],
        color=None,
        categorical=["color"],
        hover=["color", "y"],
        points=False,
        box=True,
    )
    meta = _figure(spec, tmp_path / "task")["meta"]
    assert meta["axis_levels"] == {"color": ["a", "b", "c"]}
    assert len(meta["panels"]) == 4
    for panel in meta["panels"]:
        assert panel["points"] is False
        assert [b[:2] for b in panel["boxes"]] == [[0, 0], [1, 0], [2, 0]]
        for _, _, n, low, q1, median, q3, high in panel["boxes"]:
            assert n > 0
            assert low <= q1 <= median <= q3 <= high
    # The two facet cells differ in their rows, so in their boxes.
    first, second = meta["panels"][0], meta["panels"][1]
    assert first["facet"] != second["facet"]
    assert first["boxes"] != second["boxes"]


def _one_band(spec: ScatterSpec, **changes: object) -> ScatterSpec:
    """Return `spec` without an x column: y over the one band, with box plots and no facets."""
    return replace(
        spec,
        files={**spec.files, ONE_BAND: []},
        x=[ONE_BAND],
        col=None,
        categorical=[ONE_BAND],
        hover=["y", "color", "facet"],
        **{"box": True, **changes},
    )


@pytest.mark.parametrize(
    ("changes", "ticks"),
    [
        ({}, ["a", "b", "c"]),
        (
            {"overlay": "facet"},
            ["a / p", "a / q", "b / p", "b / q", "c / p", "c / q"],
        ),
        ({"color": None}, []),
        ({"box": False}, []),
    ],
)
def test_the_one_band_ticks_each_series_under_its_box(
    tmp_path: Path, scatter_spec: ScatterSpec, changes: dict, ticks: list[str]
) -> None:
    """The one band names each box by its series, a color and an overlay level by both; without boxes or series it has no ticks."""
    result = _figure(_one_band(scatter_spec, **changes), tmp_path / "task")
    axis = result["figure"]["layout"]["xaxis"]
    assert axis["range"] == [-0.5, 0.5]
    assert axis["ticktext"] == ticks
    slot = 0.8 / max(len(ticks), 1)
    assert axis["tickvals"] == pytest.approx(
        [-0.4 + slot * (s + 0.5) for s in range(len(ticks))]
    )
    meta = result["meta"]
    assert meta["one_band"] is True
    if changes.get("box", True):
        assert {b[0] for b in meta["panels"][0]["boxes"]} == {0}


def test_the_one_band_without_series_has_no_ticks(
    tmp_path: Path, scatter_spec: ScatterSpec, scatter_frame: pl.DataFrame
) -> None:
    """A color column with no values makes no series: the one band has no ticks, and no error."""
    path = tmp_path / "nulls.parquet"
    scatter_frame.with_columns(pl.lit(None, pl.String).alias("color")).write_parquet(
        path
    )
    spec = _one_band(scatter_spec)
    spec = replace(spec, files={**spec.files, "color": [str(path)]})
    axis = _figure(spec, tmp_path / "task")["figure"]["layout"]["xaxis"]
    assert (axis["tickvals"], axis["ticktext"]) == ([], [])


def test_a_categorical_x_is_not_the_one_band(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A graph with an x column says so in its meta."""
    assert _figure(scatter_spec, tmp_path / "task")["meta"]["one_band"] is False


def test_a_datetime_or_time_axis_is_a_date_axis(tmp_path: Path) -> None:
    """A datetime or time column has plotly's date axis; a duration a plain one. The meta names the kinds."""
    start = dt.datetime(2026, 10, 31)  # noqa: DTZ001 (naive, as in Parquet)
    path = tmp_path / "temporal.parquet"
    pl.DataFrame(
        {
            "at": [start + dt.timedelta(minutes=i) for i in range(10)],
            "clock": [dt.time(i, 0) for i in range(10)],
            "took": [dt.timedelta(seconds=i) for i in range(10)],
            "y": [float(i) for i in range(10)],
        }
    ).write_parquet(path)
    temporal = {"at": "datetime", "clock": "time", "took": "duration"}
    spec = ScatterSpec(
        files={c: [str(path)] for c in ["at", "clock", "took", "y"]},
        x=["at", "clock", "took"],
        y=["y"],
        color="at",
        row=None,
        col=None,
        width=600,
        height=300,
        hover=["at", "clock", "took", "y"],
        gradient=True,
        temporal=temporal,
    )
    result = _figure(spec, tmp_path / "task")
    layout = result["figure"]["layout"]
    assert layout["xaxis"]["type"] == "date"
    assert "tickformatstops" not in layout["xaxis"]
    assert layout["xaxis2"]["type"] == "date"
    assert layout["xaxis2"]["tickformatstops"][0]["value"] == "%H:%M:%S.%L"
    assert "type" not in layout["xaxis3"]
    lo, hi = layout["xaxis"]["range"]
    first = dt.datetime(2026, 10, 31, tzinfo=dt.UTC).timestamp() * 1000
    assert lo < first < hi
    assert result["meta"]["temporal"] == temporal
    assert result["meta"]["color"]["temporal"] == "datetime"
