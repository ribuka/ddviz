"""A view's range of a categorical axis given among other levels than those it draws takes the automatic range (`ddviz.shared.scatter.View.range_levels`)."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ddviz.compute.aggregate import aggregate
from ddviz.shared.scatter import Filter, ScatterSpec, View

N = 120
# cat cycles a, b, c; the rows of a (i % 3 == 0) have cx x0 and x3 only, and
# every cy.
FRAME = pl.DataFrame(
    {
        "cat": [["a", "b", "c"][i % 3] for i in range(N)],
        "cx": [f"x{i % 6}" for i in range(N)],
        "cy": [f"y{i % 4}" for i in range(N)],
        "v": [float(i) for i in range(N)],
    }
)
CAT_A = [Filter("cat", levels=["a"])]
# Keeps every level of cx and cy.
SOME_V = [Filter("v", range=[0.0, 100.0])]
EVERY_CX = [f"x{i}" for i in range(6)]
EVERY_CY = [f"y{i}" for i in range(4)]


def _spec(tmp_path: Path, **fields: object) -> ScatterSpec:
    """Return a spec of cx × cy, both categorical, over `FRAME`, with the fields given."""
    path = tmp_path / "range_levels.parquet"
    if not path.exists():
        FRAME.write_parquet(path)
    return ScatterSpec(
        **{
            "files": {c: [str(path)] for c in FRAME.columns},
            "x": ["cx"],
            "y": ["cy"],
            "color": None,
            "row": None,
            "col": None,
            "width": 200,
            "height": 200,
            "hover": ["v"],
            "categorical": ["cx", "cy"],
            **fields,
        }
    )


def _zoomed(tmp_path: Path, filters: list[Filter], range_levels: dict) -> object:
    """Return the view of `filters` zoomed to x2, x3 and y1, y2 of every row, with `range_levels`."""
    whole = aggregate(_spec(tmp_path))
    view = View(
        x_ranges=[[1.5, 3.5]],
        y_ranges=[[0.5, 2.5]],
        levels=whole.all_levels,
        cuts=whole.cuts,
        axis_levels={},
        find_axis_levels=["cx", "cy"],
        range_levels=range_levels,
    )
    return aggregate(_spec(tmp_path, filters=filters, view=view))


def test_a_range_of_other_levels_takes_the_automatic_range(tmp_path: Path) -> None:
    """The axis whose levels the filter changed spans its new bands; the other keeps its range."""
    agg = _zoomed(tmp_path, CAT_A, {"cx": EVERY_CX, "cy": EVERY_CY})
    assert agg.axis_levels == {"cx": ["x0", "x3"], "cy": EVERY_CY}
    assert agg.x_ranges[0] == (-0.5, 1.5)
    assert agg.y_ranges[0] == (0.5, 2.5)


def test_a_range_of_the_same_levels_is_kept(tmp_path: Path) -> None:
    """A filter that keeps the levels of the axis keeps its range."""
    agg = _zoomed(tmp_path, SOME_V, {"cx": EVERY_CX, "cy": EVERY_CY})
    assert agg.axis_levels == {"cx": EVERY_CX, "cy": EVERY_CY}
    assert agg.x_ranges[0] == (1.5, 3.5)
    assert agg.y_ranges[0] == (0.5, 2.5)


def test_a_column_without_range_levels_keeps_its_range(tmp_path: Path) -> None:
    """A column left out of the range levels keeps the range given, though its levels changed."""
    agg = _zoomed(tmp_path, CAT_A, {"cy": EVERY_CY})
    assert agg.axis_levels["cx"] == ["x0", "x3"]
    assert agg.x_ranges[0] == (1.5, 3.5)
    assert agg.y_ranges[0] == (0.5, 2.5)
