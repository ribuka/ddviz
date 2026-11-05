"""Tests of numeric columns on the color, row and col roles: intervals and gradients."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute.aggregate import COUNT, INDEX, aggregate
from ddviz.compute.cuts import cut_labels, find_cuts
from ddviz.compute.tasks.plot import run_plot, run_selection
from ddviz.server.encoding import Encoding
from ddviz.server.plan import FACET_BINS, parse_color_bins, scatter_spec
from ddviz.shared.manifest import IMAGES, read_manifest
from ddviz.shared.scatter import Binning, Filter, ScatterSpec, Selection, View


@pytest.fixture
def frame() -> pl.DataFrame:
    """Return 1000 rows with x, y, a continuous v (one null, one NaN), and k with three values."""
    rng = np.random.default_rng(1)
    n = 1000
    v = rng.normal(0, 1, n)
    v[0] = np.nan
    return pl.DataFrame(
        {
            "x": rng.normal(0, 1, n),
            "y": rng.normal(0, 1, n),
            "v": v,
            "k": rng.integers(0, 3, n) * 10,
        }
    ).with_columns(
        pl.when(pl.int_range(pl.len()) == 1).then(None).otherwise("v").alias("v")
    )


@pytest.fixture
def path(tmp_path: Path, frame: pl.DataFrame) -> Path:
    """Write `frame` to a Parquet file with several row groups."""
    path = tmp_path / "numeric.parquet"
    frame.write_parquet(path, row_group_size=300)
    return path


def _spec(path: Path, **roles: str) -> ScatterSpec:
    """Return the spec `ddviz.server.plan.scatter_spec` makes for x by y with `roles`, every column numeric."""
    encoding = Encoding(x=["x"], y=["y"], **roles)
    columns = ["x", "y", "v", "k"]
    return scatter_spec(
        encoding,
        {c: [str(path)] for c in columns},
        400,
        300,
        [],
        numeric=dict.fromkeys(columns, True),
    )


def _finite_v(frame: pl.DataFrame) -> pl.Series:
    """Return the finite values of v."""
    return frame["v"].drop_nulls().filter(frame["v"].drop_nulls().is_finite())


def _interval_counts(v: pl.Series, breaks: list[float]) -> list[int]:
    """Return the values of `v` in each interval of `breaks`, the last one closed."""
    last = len(breaks) - 2
    return [
        v.filter((v >= lo) & ((v <= hi) if i == last else (v < hi))).len()
        for i, (lo, hi) in enumerate(pairwise(breaks))
    ]


def test_cuts_by_rows_split_the_rows_evenly(path: Path, frame: pl.DataFrame) -> None:
    """Quantile cuts give intervals of about the same number of rows, the last one closed."""
    cuts = find_cuts(pl.scan_parquet(path), "v", Binning(5, "rows"))
    v = _finite_v(frame)
    breaks = cuts["breaks"]
    assert not cuts["values"]
    assert breaks[0] == v.min()
    assert breaks[-1] == v.max()
    counts = _interval_counts(v, breaks)
    assert sum(counts) == v.len()
    assert max(counts) - min(counts) <= 2


def test_cuts_by_values_are_of_equal_width(path: Path, frame: pl.DataFrame) -> None:
    """Value cuts split the finite range into intervals of the same width."""
    cuts = find_cuts(pl.scan_parquet(path), "v", Binning(4, "values"))
    v = _finite_v(frame)
    assert cuts["breaks"] == pytest.approx(np.linspace(v.min(), v.max(), 5).tolist())


def test_a_column_of_few_values_gets_a_level_per_value(path: Path) -> None:
    """At most `values_up_to` values are levels of their own."""
    cuts = find_cuts(pl.scan_parquet(path), "k", Binning(5, "rows", values_up_to=5))
    assert cuts == {"breaks": [0, 10, 20, 20], "values": True}
    assert cut_labels(cuts) == ["0", "10", "20"]
    many = find_cuts(pl.scan_parquet(path), "k", Binning(2, "rows", values_up_to=2))
    assert not many["values"]


def test_ties_merge_quantile_breaks() -> None:
    """Breaks that fall on the same value merge, leaving fewer intervals."""
    scan = pl.LazyFrame({"a": [1.0] * 90 + [2.0] * 10})
    cuts = find_cuts(scan, "a", Binning(5, "rows"))
    assert cuts == {"breaks": [1.0, 2.0], "values": False}
    assert cut_labels(cuts) == ["[1, 2]"]


def test_labels_of_intervals() -> None:
    """Intervals read as half-open ranges, the last one closed."""
    assert cut_labels({"breaks": [0.0, 1.5, 3.0], "values": False}) == [
        "[0, 1.5)",
        "[1.5, 3]",
    ]


def test_plan_cuts_numeric_facets_and_makes_numeric_color_a_gradient(
    path: Path,
) -> None:
    """A numeric row or col column is binned; a numeric color is a gradient unless binned."""
    spec = _spec(path, color="v", row="k", col="v")
    assert spec.binned == {
        "row": Binning(FACET_BINS, "rows", FACET_BINS),
        "col": Binning(FACET_BINS, "rows", FACET_BINS),
    }
    assert spec.gradient
    binned = scatter_spec(
        Encoding(x=["x"], y=["y"], color="v"),
        spec.files,
        400,
        300,
        [],
        numeric=dict.fromkeys(spec.files, True),
        color_bins=Binning(3, "values"),
    )
    assert binned.binned == {"color": Binning(3, "values")}
    assert not binned.gradient


def test_parse_color_bins_takes_known_counts_only() -> None:
    """The page may cut a color column into 2, 3, 5 or 10 intervals, by rows or by values."""
    assert parse_color_bins({"n": 5, "by": "rows"}) == Binning(5, "rows")
    assert parse_color_bins(None) is None
    for raw in ({"n": 4, "by": "rows"}, {"n": 5, "by": "other"}, {"n": 5}):
        with pytest.raises(ValueError, match="color bins"):
            parse_color_bins(raw)


def test_numeric_facet_panels_hold_their_intervals(
    path: Path, frame: pl.DataFrame
) -> None:
    """Each panel of a binned col holds the rows of its interval; rows with a non-finite value are left out."""
    agg = aggregate(_spec(path, col="v"))
    assert agg.levels["col"] == cut_labels(agg.cuts["col"])
    assert len(agg.levels["col"]) == FACET_BINS
    panels, *_ = agg.grid.unpack(agg.bins["__key"].to_numpy())
    counts = (
        pl.DataFrame({"panel": panels, "n": agg.bins[COUNT]})
        .group_by("panel")
        .agg(pl.col("n").sum())
        .sort("panel")["n"]
        .to_list()
    )
    v = _finite_v(frame)
    breaks = agg.cuts["col"]["breaks"]
    assert counts == _interval_counts(v, breaks)


def test_numeric_facet_of_few_values_and_its_selection(
    path: Path, frame: pl.DataFrame
) -> None:
    """A few-valued row column has a panel per value; a box selects the rows of its value."""
    overview = aggregate(_spec(path, row="k"))
    assert overview.levels["row"] == ["0", "10", "20"]
    spec = replace(
        _spec(path, row="k"),
        view=View(
            x_ranges=[list(r) for r in overview.x_ranges],
            y_ranges=[list(r) for r in overview.y_ranges],
            levels=overview.all_levels,
            facets={"row": overview.levels["row"], "col": overview.levels["col"]},
            cuts=overview.cuts,
        ),
        selection=Selection(
            x="x", y="y", x_range=[-1.0, 1.0], y_range=[-1.0, 1.0], row="10"
        ),
    )
    agg = aggregate(spec, selection_only=True)
    expected = frame.filter(
        pl.col("k") == 10,
        pl.col("x").is_between(-1.0, 1.0),
        pl.col("y").is_between(-1.0, 1.0),
    ).height
    assert agg.selected_rows == expected


def test_filter_drops_numeric_facet_intervals(path: Path, frame: pl.DataFrame) -> None:
    """A filter keeping only low values drops the intervals left without rows; the bins land in the kept panels."""
    whole = aggregate(_spec(path, col="v"))
    breaks = whole.cuts["col"]["breaks"]
    spec = replace(
        _spec(path, col="v"), filters=[Filter("v", range=[breaks[0], breaks[1]])]
    )
    agg = aggregate(spec)
    assert agg.levels["col"] == whole.levels["col"][:2]
    assert agg.all_levels == whole.all_levels
    panels, *_ = agg.grid.unpack(agg.bins["__key"].to_numpy())
    assert set(panels.tolist()) <= {0, 1}
    v = _finite_v(frame)
    assert agg.bins[COUNT].sum() == v.filter(v.is_between(breaks[0], breaks[1])).len()


def test_gradient_writes_one_image_of_grays(tmp_path: Path, path: Path) -> None:
    """A gradient has one series; its image holds the grays of the representative rows' values."""
    spec = replace(_spec(path, color="v"), null_roles=[])
    out = tmp_path / "plot"
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    manifest = read_manifest(out)
    assert manifest["levels"]["color"] == [None]
    assert manifest["grid"]["n_series"] == 1
    assert len(manifest["images"]) == 1
    lo, hi = manifest["color_range"]
    v = _finite_v(pl.read_parquet(path))
    assert (lo, hi) == (v.min(), v.max())
    offset, length = manifest["images"][0]
    png = (out / IMAGES).read_bytes()[offset : offset + length]
    # An 8-bit palette PNG: bit depth 8, color type 3.
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert png[24:26] == b"\x08\x03"

    sel = replace(
        spec,
        view=View(
            x_ranges=manifest["x_ranges"],
            y_ranges=manifest["y_ranges"],
            levels=manifest["all_levels"],
            facets={r: manifest["levels"][r] for r in ("row", "col")},
            color_range=manifest["color_range"],
        ),
        selection=Selection(x="x", y="y", x_range=[-1.0, 1.0], y_range=[-1.0, 1.0]),
    )
    agg = aggregate(sel, selection_only=True)
    assert agg.selected.columns == ["__key", COUNT, INDEX, "v"]
    layer = tmp_path / "layer"
    layer.mkdir()
    run_selection(sel, layer, lambda _: None)
    assert len(read_manifest(layer)["images"]) == 1


def test_labels_use_the_fewest_digits_that_tell_breaks_apart() -> None:
    """Breaks show 3 significant digits, more only where needed to differ."""
    assert cut_labels({"breaks": [-5.35011, -0.84085, 0.253871], "values": False}) == [
        "[-5.35, -0.841)",
        "[-0.841, 0.254]",
    ]
    assert cut_labels({"breaks": [1.0001, 1.0002], "values": False}) == [
        "[1.0001, 1.0002]"
    ]
