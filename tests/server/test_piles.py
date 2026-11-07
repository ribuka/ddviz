"""Tests of the piles of a plot task's result: their files, their hover, the plot's data and the selection layer."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ddviz.compute.tasks.plot import run_plot, run_selection
from ddviz.compute.tasks.plotdata import bins_table
from ddviz.server.derive import selection_spec
from ddviz.server.hover import HoverIndex
from ddviz.shared.manifest import SelectionManifest
from ddviz.shared.scatter import ScatterSpec, Selection


@pytest.fixture
def pile_frame() -> pl.DataFrame:
    """Return piles of 100 and 10,000 rows at one level, over three colors and two shapes, beside rows alone."""
    rng = np.random.default_rng(3)
    n = 100 + 10_000 + 50
    return pl.DataFrame(
        {
            "g": ["a"] * n,
            "y": [1.0] * 100 + [2.0] * 10_000 + list(np.linspace(3, 9, 50)),
            "c": rng.choice(["p", "q", "r"], n),
            "s": rng.choice(["u", "v"], n),
            "v": rng.normal(0, 1, n),
        }
    )


@pytest.fixture
def pile_spec(tmp_path: Path, pile_frame: pl.DataFrame) -> ScatterSpec:
    """Return a spec of `pile_frame` with g on x as a categorical axis, colored by c and shaped by s."""
    path = tmp_path / "piles.parquet"
    pile_frame.write_parquet(path, row_group_size=1000)
    return ScatterSpec(
        files={c: [str(path)] for c in pile_frame.columns},
        x=["g"],
        y=["y"],
        color="c",
        symbol="s",
        row=None,
        col=None,
        width=400,
        height=300,
        hover=["g", "y", "c", "s"],
        categorical=["g"],
    )


def _open(tmp_path: Path, spec: ScatterSpec, name: str = "task") -> HoverIndex:
    """Run the plot task of a spec and open its result."""
    out = tmp_path / name
    out.mkdir()
    run_plot(spec, out, lambda _: None)
    return HoverIndex(out)


@pytest.fixture
def index(tmp_path: Path, pile_spec: ScatterSpec) -> Iterator[HoverIndex]:
    """Open the result of `pile_spec`."""
    opened = _open(tmp_path, pile_spec)
    yield opened
    opened.close()


def test_the_piles_have_their_exact_rows_and_rows_by_series(
    index: HoverIndex, pile_frame: pl.DataFrame
) -> None:
    """Two piles of 100 and 10,000 rows; their rows by color and shape add up to them, and the hover shows their values."""
    piles = index.piles()
    assert piles["n"] == [100, 10_000]
    assert piles["panel"] == [0, 0] and piles["bx"][0] == piles["bx"][1]
    assert index.manifest.piles == 2
    assert index.manifest.rows == pile_frame.height
    for i, (lo, hi) in enumerate([(0, 100), (100, 10_100)]):
        pile = index.pile(i)
        assert pile["values"] == {"g": "a", "y": float(i + 1)}
        assert pile["color_range"] is None
        rows = pile_frame[lo:hi]
        expected = rows.group_by("c", "s").len()
        found = {
            (["p", "q", "r"][s // 2], ["u", "v"][s % 2]): n for s, n in pile["series"]
        }
        assert found == {(c, s): n for c, s, n in expected.iter_rows()}
        assert sum(found.values()) == pile["n"]
        assert sorted({s for s, _ in pile["series"]}) == piles["series"][i]
    assert index.pile(2) is None


def test_a_gradient_pile_has_its_least_and_largest_color_by_shape(
    tmp_path: Path, pile_spec: ScatterSpec, pile_frame: pl.DataFrame
) -> None:
    """A numeric color is no series: a pile has its rows by shape and the range of its color values."""
    gradient = replace(pile_spec, color="v", gradient=True, hover=["g", "y", "v", "s"])
    index = _open(tmp_path, gradient)
    try:
        pile = index.pile(1)
        rows = pile_frame[100:10_100]
        assert pile["color_range"] == [rows["v"].min(), rows["v"].max()]
        assert sorted(pile["series"]) == sorted(
            [i, n] for i, n in enumerate(rows.group_by("s").len().sort("s")["len"])
        )
    finally:
        index.close()


def test_the_plot_data_counts_the_rows_of_the_piles_once_in_their_series(
    index: HoverIndex, pile_frame: pl.DataFrame
) -> None:
    """The saved bins hold every drawn row once, by its color and shape, the piles' rows at their centers."""
    table = bins_table(index.out)
    assert table["count"].sum() == pile_frame.height
    found = table.group_by("color", "symbol").agg(pl.col("count").sum())
    expected = pile_frame.group_by("c", "s").len()
    assert dict(
        zip(
            zip(found["color"], found["symbol"], strict=True),
            found["count"],
            strict=True,
        )
    ) == {(c, s): n for c, s, n in expected.iter_rows()}


def test_the_pile_files_past_the_limit_fail_the_plot(
    tmp_path: Path, pile_spec: ScatterSpec
) -> None:
    """Without room for the piles' files the plot cannot be drawn: the task fails rather than drawing it short."""
    out = tmp_path / "small"
    out.mkdir()
    with pytest.raises(ValueError, match="max_temp_gb"):
        run_plot(replace(pile_spec, hover_bytes=100), out, lambda _: None)
    assert not list(out.glob("pile_*.npy"))


def test_the_hover_files_past_the_limit_keep_the_piles(
    tmp_path: Path, pile_spec: ScatterSpec
) -> None:
    """With room for the piles' files only, the plot draws its piles without the hover files."""
    first = _open(tmp_path, pile_spec, "first")
    room = first.manifest.pile_bytes
    first.close()
    index = _open(tmp_path, replace(pile_spec, hover_bytes=room), "second")
    try:
        assert not index.manifest.hover_files
        assert index.piles()["n"] == [100, 10_000]
        assert index.pile(1)["n"] == 10_000
    finally:
        index.close()


def test_the_selection_layer_marks_the_piles_with_selected_rows(
    tmp_path: Path, index: HoverIndex
) -> None:
    """A box around a pile's center marks its pixel; the selected rows are all of its rows."""
    selection = Selection(x="g", y="y", x_range=[-0.05, 0.05], y_range=[1.5, 2.5])
    out = tmp_path / "layer"
    out.mkdir()
    run_selection(selection_spec(index.manifest, selection), out, lambda _: None)
    layer = SelectionManifest.read(out)
    piles = index.piles()
    grid = index.grid
    pixel = (piles["panel"][1] * grid.height + piles["by"][1]) * grid.width + piles[
        "bx"
    ][1]
    assert layer.piles == [pixel]
    assert layer.rows == 10_000


@pytest.mark.parametrize(
    "name",
    ["min", "max", "__color_min", "__color_max", "__rows", "__values", "__value0"],
)
def test_an_axis_column_named_like_the_color_extremes_keeps_its_value(
    tmp_path: Path, name: str
) -> None:
    """A y column named like an internal column draws a pile of a gradient and shows its value."""
    frame = pl.DataFrame({"g": ["a"] * 100, name: [1.0] * 100, "c": [2.0] * 100})
    path = tmp_path / "named.parquet"
    frame.write_parquet(path)
    spec = ScatterSpec(
        files={c: [str(path)] for c in frame.columns},
        x=["g"],
        y=[name],
        color="c",
        gradient=True,
        row=None,
        col=None,
        width=400,
        height=300,
        hover=["g", name, "c"],
        categorical=["g"],
    )
    index = _open(tmp_path, spec)
    try:
        pile = index.pile(0)
        assert pile["values"] == {"g": "a", name: 1.0}
        assert pile["color_range"] == [2.0, 2.0]
    finally:
        index.close()
