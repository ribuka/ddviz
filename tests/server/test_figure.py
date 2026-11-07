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
    """When the panels are too small for the size, plotly shows no tick or facet labels; the meta has the facet labels.

    plotly makes the tick labels of the outer panels, in no color: without
    them, it leaves the exponent out of the text the page's strips show.
    """
    small = replace(scatter_spec, width=300, height=200)
    result = _figure(small, tmp_path / "task")
    layout = result["figure"]["layout"]
    assert result["meta"]["scroll"]
    assert layout["width"] > 300
    assert [layout[a]["showticklabels"] for a in ("xaxis", "yaxis", "yaxis2")] == [
        True,
        True,
        False,
    ]
    hidden = {"color": "rgba(0,0,0,0)"}
    assert all(layout[a]["tickfont"] == hidden for a in ("xaxis", "yaxis", "xaxis2"))
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
    assert "tickfont" not in layout["yaxis"]


def test_the_left_margin_is_the_specs_for_the_whole_figure(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A wider left margin moves every panel right, narrows them, and is the figure's margin."""
    narrow = _figure(replace(scatter_spec, width=800, height=400), tmp_path / "a")
    wide = _figure(
        replace(scatter_spec, width=800, height=400, margin_left=90), tmp_path / "b"
    )
    a, b = narrow["figure"]["layout"], wide["figure"]["layout"]
    assert (a["margin"]["l"], b["margin"]["l"]) == (50, 90)
    assert (narrow["meta"]["margin_left"], wide["meta"]["margin_left"]) == (50, 90)
    assert b["width"] == a["width"] == 800
    for key in ("xaxis", "xaxis2"):
        lo, hi = b[key]["domain"]
        assert (
            round((hi - lo) * (800 - 90 - 30))
            == round((a[key]["domain"][1] - a[key]["domain"][0]) * (800 - 50 - 30)) - 20
        )
    assert b["yaxis"]["ticklabeloverflow"] == "allow"
    assert wide["meta"]["y_categorical"] == [False]


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


@pytest.mark.parametrize(
    ("wrap_cols", "width", "height", "ncol", "auto"),
    [
        (None, 800, 600, 2, 2),
        (1, 800, 600, 1, 2),
        (5, 800, 600, 3, 2),
        (2, 300, 900, 2, 1),
    ],
)
def test_a_wrapped_grid_tells_its_automatic_number_to_a_row(
    tmp_path: Path,
    scatter_spec: ScatterSpec,
    wrap_cols: int | None,
    width: int,
    height: int,
    ncol: int,
    auto: int,
) -> None:
    """The number to a row with none set follows the size, whatever number is set."""
    wrapped = replace(
        scatter_spec,
        col="color",
        wrap=True,
        wrap_cols=wrap_cols,
        width=width,
        height=height,
    )
    meta = _figure(wrapped, tmp_path / "task")["meta"]
    assert (meta["ncol"], meta["wrap_auto_cols"]) == (ncol, auto)


def test_a_grid_not_wrapped_has_no_automatic_number_to_a_row(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """Without wrapping, there is no number to a row to set."""
    gridded = replace(scatter_spec, col="color", width=800, height=600)
    assert _figure(gridded, tmp_path / "task")["meta"]["wrap_auto_cols"] is None


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


def test_a_categorical_axis_leaves_its_ticks_to_the_page(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """A categorical axis has array ticks the page fills from the meta's levels (``static/js/bandticks.js``)."""
    spec = replace(
        scatter_spec, x=["color"], color=None, categorical=["color"], hover=["color"]
    )
    result = _figure(spec, tmp_path / "task")
    layout = result["figure"]["layout"]
    for key in ("xaxis", "xaxis2"):
        axis = layout[key]
        assert axis["range"] == [-0.5, 2.5]
        assert axis["tickmode"] == "array"
        assert (axis["tickvals"], axis["ticktext"]) == ([], [])
    assert "tickvals" not in layout["yaxis"]
    assert result["meta"]["axis_levels"] == {"color": ["a", "b", "c"]}


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
            {"symbol": "facet"},
            ["a / p", "a / q", "b / p", "b / q", "c / p", "c / q"],
        ),
        ({"color": None}, []),
        ({"color": None, "symbol": "facet"}, ["p", "q"]),
        ({"box": False}, []),
    ],
)
def test_the_one_band_ticks_each_series_under_its_box(
    tmp_path: Path, scatter_spec: ScatterSpec, changes: dict, ticks: list[str]
) -> None:
    """The one band names each box by its series, a color and a symbol level by both, a symbol level alone by it; without boxes or series it has no ticks."""
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
    # A duration is a plain axis of seconds, but still a temporal column:
    # the page sets ranges and ticks on numeric axes only.
    assert result["meta"]["x_numeric"] == [False, False, False]
    assert result["meta"]["y_numeric"] == [True]


@pytest.mark.parametrize(
    ("changes", "x_numeric", "y_numeric"),
    [
        pytest.param({}, [True], [True], id="numeric"),
        pytest.param(
            {"x": ["color", "x"], "color": None, "categorical": ["color"]},
            [False, True],
            [True],
            id="categorical",
        ),
    ],
)
def test_the_meta_tells_which_axis_columns_are_numeric(
    tmp_path: Path,
    scatter_spec: ScatterSpec,
    changes: dict,
    x_numeric: list[bool],
    y_numeric: list[bool],
) -> None:
    """Each x and y column says whether its axis is numeric, which the page's axis dialog needs."""
    meta = _figure(replace(scatter_spec, **changes), tmp_path / "task")["meta"]
    assert meta["x_numeric"] == x_numeric
    assert meta["y_numeric"] == y_numeric


def test_the_one_band_is_not_a_numeric_axis(
    tmp_path: Path, scatter_spec: ScatterSpec
) -> None:
    """The one band's x has no numeric values; its numeric y does."""
    meta = _figure(_one_band(scatter_spec), tmp_path / "task")["meta"]
    assert meta["x_numeric"] == [False]
    assert meta["y_numeric"] == [True]


def _worst_spec(tmp_path: Path, **roles: object) -> ScatterSpec:
    """Return a spec over a file whose level names are long, empty or markup."""
    path = tmp_path / "worst.parquet"
    long = "level_" + "x" * 100
    pl.DataFrame(
        {
            "x": [float(i) for i in range(9)],
            "y": [float(i) for i in range(9)],
            "g": [long, "", "<b>bold</b>"] * 3,
        }
    ).write_parquet(path)
    defaults: dict = {"row": None, "col": None, "color": None}
    return ScatterSpec(
        files={c: [str(path)] for c in ["x", "y", "g"]},
        x=["x"],
        y=["y"],
        width=900,
        height=500,
        hover=["x", "y", "g"],
        **{**defaults, **roles},
    )


def test_long_facet_labels_are_cut_to_their_panels(tmp_path: Path) -> None:
    """A facet label wider than its panel ends in "…" and keeps its whole text as its hover text."""
    result = _figure(_worst_spec(tmp_path, col="g", row="g"), tmp_path / "task")
    labels = result["figure"]["layout"]["annotations"]
    cut = [a for a in labels if a["text"].endswith("…")]
    assert {a.get("textangle") for a in cut} == {None, 90}
    assert all(a["hovertext"] == "g = level_" + "x" * 100 for a in cut)
    # The level is kept; the short ones are whole.
    texts = [a["text"] for a in labels]
    assert "g = （空文字列）" in texts
    assert "g = &lt;b&gt;bold&lt;/b&gt;" in texts


def test_the_page_gets_facet_labels_as_text(tmp_path: Path) -> None:
    """A scrolled grid's labels, which the page sets as text, are not escaped."""
    spec = replace(_worst_spec(tmp_path, col="g"), width=300, height=200)
    result = _figure(spec, tmp_path / "task")
    assert result["meta"]["scroll"]
    texts = [a["text"] for a in result["meta"]["facet_labels"]]
    assert "g = <b>bold</b>" in texts


def test_categorical_levels_go_as_they_are_and_numbers_write_e(tmp_path: Path) -> None:
    """The page gets a categorical axis's levels unescaped and uncut (it fits and escapes its ticks); numeric ticks write "1e+300"."""
    spec = replace(_worst_spec(tmp_path), x=["g"], categorical=["g"])
    result = _figure(spec, tmp_path / "task")
    levels = result["meta"]["axis_levels"]["g"]
    assert "" in levels
    assert "<b>bold</b>" in levels
    assert any(v.startswith("level_") and not v.endswith("…") for v in levels)
    assert result["figure"]["layout"]["yaxis"]["exponentformat"] == "e"
