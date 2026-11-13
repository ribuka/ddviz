"""Tests of the missing level: the rows of a null or NaN color or symbol drawn with Show null rows."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute.aggregate import COUNT, KEY, aggregate
from ddviz.compute.tasks.plot import run_plot
from ddviz.compute.tasks.table import run_table
from ddviz.shared.manifest import PlotManifest, read_manifest
from ddviz.shared.missing import MISSING, MISSING_COLOR, MISSING_SHAPE
from ddviz.shared.palette import DEFAULT_COLORS
from ddviz.shared.scatter import Binning, ScatterSpec, Selection, Smoothing, View
from ddviz.shared.shapes import AUTO_SHAPES
from ddviz.shared.tasks import SourceFiles, TableTask

NAN, INF = float("nan"), float("inf")
COLUMNS = ["x", "y", "k", "g", "v", "b"]


@pytest.fixture
def frame() -> pl.DataFrame:
    """Return 12 rows: k a text with nulls and texts that look missing, g a text with nulls, v a float with null, NaN and infinities."""
    return pl.DataFrame(
        {
            "x": [float(i) for i in range(12)],
            "y": [float(i % 5) for i in range(12)],
            "k": [
                "a",
                None,
                "(null)",
                "None",
                "nan",
                "",
                "a",
                None,
                "b",
                "b",
                "a",
                "a",
            ],
            "g": ["p", "q", None, "p", "q", None, "p", "q", "p", None, "q", "p"],
            "v": [1.0, None, NAN, INF, -INF, 2.0, 3.0, 4.0, None, 5.0, 6.0, NAN],
            "b": ["u", "w"] * 6,
        },
        schema_overrides={"v": pl.Float64},
    )


@pytest.fixture
def path(tmp_path: Path, frame: pl.DataFrame) -> Path:
    """Write `frame` to a Parquet file."""
    out = tmp_path / "missing.parquet"
    frame.write_parquet(out)
    return out


def _spec(path: Path, **fields: object) -> ScatterSpec:
    """Return a spec of x by y over `path`, with `fields`."""
    defaults = {
        "x": ["x"],
        "y": ["y"],
        "color": None,
        "row": None,
        "col": None,
        "width": 200,
        "height": 100,
        "hover": ["x", "y"],
    }
    return ScatterSpec(
        files={c: [str(path)] for c in COLUMNS}, **{**defaults, **fields}
    )


def _series_counts(agg) -> dict[int, int]:  # noqa: ANN001
    """Return the rows drawn in each series."""
    _, series, _, _ = agg.grid.unpack(agg.bins[KEY].to_numpy())
    counts: dict[int, int] = {}
    for s, n in zip(series.tolist(), agg.bins[COUNT].to_list(), strict=True):
        counts[s] = counts.get(s, 0) + n
    return counts


def test_a_categorical_color_draws_its_nulls_last_apart_from_texts(path: Path) -> None:
    """The null rows are the last level; the texts "(null)", "None", "nan" and "" stay levels of their own."""
    agg = aggregate(_spec(path, color="k", null_roles=["color"]))
    assert agg.levels["color"] == ["", "(null)", "a", "b", "nan", "None", MISSING]
    counts = _series_counts(agg)
    assert counts[6] == 2
    assert counts[1] == 1
    assert sum(counts.values()) == 12


def test_without_show_null_rows_the_nulls_stay_out(path: Path) -> None:
    """A role not in null_roles keeps leaving out its null rows, and has no missing level."""
    agg = aggregate(_spec(path, color="k"))
    assert MISSING not in agg.levels["color"]
    assert sum(_series_counts(agg).values()) == 10


def test_a_column_without_nulls_has_no_missing_level(path: Path) -> None:
    """Show null rows adds the level only when the column has a null."""
    agg = aggregate(_spec(path, color="b", null_roles=["color"]))
    assert agg.levels["color"] == ["u", "w"]


def test_a_binned_color_puts_null_and_nan_in_one_level_and_leaves_infinities_out(
    path: Path,
) -> None:
    """Null and NaN are one level after the intervals, which cut the finite values only; infinities stay out."""
    spec = _spec(path, color="v", binned={"color": Binning(2)}, null_roles=["color"])
    agg = aggregate(spec)
    assert agg.levels["color"][-1] == MISSING
    assert len(agg.levels["color"]) == 3
    assert agg.cuts["color"]["breaks"][0] == 1.0
    assert agg.cuts["color"]["breaks"][-1] == 6.0
    counts = _series_counts(agg)
    # 4 missing (2 nulls, 2 NaN), 6 finite, 2 infinite left out.
    assert counts[2] == 4
    assert sum(counts.values()) == 10


def test_a_gradient_draws_its_missing_rows_as_a_series_in_gray(
    tmp_path: Path, path: Path
) -> None:
    """A gradient's missing rows are a second series, written as a mask in gray, not grays of the scale."""
    spec = _spec(
        path, color="v", gradient=True, null_roles=["color"], hover=["x", "y", "v"]
    )
    out = tmp_path / "plot"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    manifest = PlotManifest.read(out)
    assert manifest.levels["color"] == [None, MISSING]
    assert manifest.grid.n_series == 2
    assert manifest.colors[1] == MISSING_COLOR
    assert manifest.images[0] is not None and manifest.images[1] is not None
    assert manifest.color_range == (1.0, 6.0) or list(manifest.color_range) == [1, 6]
    agg = aggregate(spec)
    assert _series_counts(agg) == {0: 6, 1: 4}


def test_a_gradient_of_missing_values_only_has_only_the_missing_level(
    tmp_path: Path,
) -> None:
    """Without a finite value, the gradient draws the missing level alone."""
    out = tmp_path / "nulls.parquet"
    pl.DataFrame(
        {"x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0], "v": [None, NAN, None]},
        schema_overrides={"v": pl.Float64},
    ).write_parquet(out)
    spec = ScatterSpec(
        files={c: [str(out)] for c in ["x", "y", "v"]},
        x=["x"],
        y=["y"],
        color="v",
        row=None,
        col=None,
        width=100,
        height=100,
        hover=["x", "y"],
        gradient=True,
        null_roles=["color"],
    )
    agg = aggregate(spec)
    assert agg.levels["color"] == [MISSING]
    assert _series_counts(agg) == {0: 3}
    assert aggregate(replace(spec, null_roles=[])).bins.height == 0


@pytest.mark.parametrize(
    ("roles", "rows"),
    [
        (["color", "symbol"], 12),
        (["color"], 9),
        (["symbol"], 10),
        ([], 7),
    ],
)
def test_color_and_symbol_each_keep_or_leave_out_their_nulls(
    path: Path, roles: list[str], rows: int
) -> None:
    """A row is drawn when each of its color and symbol is a level or a missing value its role draws."""
    agg = aggregate(_spec(path, color="k", symbol="g", null_roles=roles))
    assert sum(_series_counts(agg).values()) == rows
    assert (agg.levels["color"][-1] == MISSING) == ("color" in roles)
    assert (agg.levels["symbol"][-1] == MISSING) == ("symbol" in roles)


def test_one_column_on_color_and_symbol_meets_both_settings(path: Path) -> None:
    """The same column on both roles draws its nulls only when both roles do."""
    both = aggregate(
        _spec(path, color="g", symbol="g", null_roles=["color", "symbol"])
    )
    assert sum(_series_counts(both).values()) == 12
    one = aggregate(_spec(path, color="g", symbol="g", null_roles=["color"]))
    assert sum(_series_counts(one).values()) == 9
    assert one.levels["color"][-1] == MISSING
    assert MISSING not in one.levels["symbol"]


def test_a_facet_of_the_same_column_still_leaves_the_nulls_out(path: Path) -> None:
    """Row and col keep leaving out their nulls, whatever the color draws."""
    agg = aggregate(_spec(path, color="g", col="g", null_roles=["color"]))
    assert MISSING in agg.levels["color"]
    assert MISSING not in agg.levels["col"]
    assert sum(_series_counts(agg).values()) == 9


def test_the_missing_symbol_level_takes_the_x_and_no_other_level_does(
    path: Path,
) -> None:
    """The missing level's shape is the x unless picked; the other levels skip it."""
    spec = _spec(path, color="b", symbol="k", null_roles=["symbol"])
    levels = aggregate(spec).levels["symbol"]
    shapes = spec.marker_shapes(levels)
    assert shapes[-1] == MISSING_SHAPE
    assert shapes[:-1] == list(AUTO_SHAPES[: len(levels) - 1])
    picked = replace(spec, level_shapes={MISSING: "square", "(null)": "x"})
    shapes = picked.marker_shapes(levels)
    assert shapes[-1] == "square"
    assert shapes[levels.index("(null)")] == "x"
    sized = replace(spec, shape_sizes={MISSING: 11})
    assert sized.marker_sizes(levels)[-1] == 11
    assert sized.marker_sizes(levels)[levels.index("(null)")] == spec.shape_size


def test_the_missing_level_counts_against_max_levels(path: Path) -> None:
    """A categorical column at the limit fails once its drawn missing level is one more."""
    spec = _spec(path, color="g", max_levels=2)
    assert aggregate(spec).levels["color"] == ["p", "q"]
    with pytest.raises(ValueError, match="上限"):
        aggregate(replace(spec, null_roles=["color"]))
    assert aggregate(replace(spec, max_levels=3, null_roles=["color"])).levels[
        "color"
    ] == ["p", "q", MISSING]


def test_the_missing_level_keeps_the_others_colors(tmp_path: Path, path: Path) -> None:
    """The missing level is gray; the colors of the other levels do not move."""
    out = tmp_path / "plot"
    out.mkdir()
    run_plot(_spec(path, color="g", null_roles=["color"]), out, lambda _: None)
    manifest = PlotManifest.read(out)
    assert manifest.colors == [DEFAULT_COLORS[0], DEFAULT_COLORS[1], MISSING_COLOR]


def test_boxes_and_smoothing_lines_have_a_missing_series(path: Path) -> None:
    """The box plots and the smoothing lines take the missing level as a series of its own."""
    boxed = aggregate(
        _spec(
            path, x=["b"], color="g", categorical=["b"], box=True, null_roles=["color"]
        )
    )
    series = {int(stats[3]) for stats in boxed.boxes[0].stats}
    assert 2 in series
    smoothed = aggregate(
        _spec(path, color="g", smooth=Smoothing("lowess"), null_roles=["color"])
    )
    assert 2 in {int(line[2]) for line in smoothed.smooths[0].lines}


def test_selection_lists_missing_rows_with_their_null_values(
    tmp_path: Path, path: Path
) -> None:
    """A box selects the missing rows it covers; the table keeps their nulls and NaN as they are."""
    spec = _spec(path, color="v", gradient=True, null_roles=["color"])
    overview = aggregate(spec)
    view = replace(
        spec,
        selection=Selection("x", "y", [0.0, 3.0], [0.0, 4.0]),
        view=View(
            x_ranges=[list(r) for r in overview.x_ranges],
            y_ranges=[list(r) for r in overview.y_ranges],
            levels=overview.all_levels,
            cuts=overview.cuts,
            color_range=list(overview.color_range),
        ),
    )
    out = tmp_path / "page"
    out.mkdir()
    parts = {c: view.files[c] for c in ["x", "v"]}
    run_table(
        TableTask(view, 0, 10, ["x", "v"], parts, SourceFiles([], [], "", {}, {})),
        out,
        lambda _: None,
    )
    page = read_manifest(out)
    # Rows 0..3: 1.0, null, NaN drawn; inf left out.
    assert page["index"] == [0, 1, 2]
    values = {c["name"]: c["values"] for c in page["columns"]}["v"]
    assert values[0] == 1.0 and values[1] is None
    # The table sends a NaN as its text, apart from the null.
    assert values[2] == "nan"


def test_a_text_equal_to_the_missing_level_is_refused(tmp_path: Path) -> None:
    """A text of the data equal to the missing level's internal name cannot be confused with it: the plot is refused."""
    out = tmp_path / "taken.parquet"
    pl.DataFrame({"x": [1.0, 2.0], "y": [1.0, 2.0], "k": [MISSING, "a"]}).write_parquet(
        out
    )
    spec = ScatterSpec(
        files={c: [str(out)] for c in ["x", "y", "k"]},
        x=["x"],
        y=["y"],
        color="k",
        row=None,
        col=None,
        width=100,
        height=100,
        hover=["x", "y"],
    )
    with pytest.raises(ValueError, match="内部名"):
        aggregate(spec)
