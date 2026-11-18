"""The intervals of a numeric symbol, row or col (wrap's) column are cut from the rows of the local filter (Issue #265)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute import foundcolor
from ddviz.compute.aggregate import Aggregation, aggregate
from ddviz.compute.cuts import cut_labels, find_cuts
from ddviz.server.plan import FACET_BINS
from ddviz.shared.scatter import Binning, Filter, ScatterSpec, Selection, View

# g is 0..99, one row each; h is 0..99 too, but missing (null) where g < 50.
FRAME = pl.DataFrame(
    {
        "x": [float(i % 10) for i in range(100)],
        "y": [float(i // 10) for i in range(100)],
        "g": list(range(100)),
        "h": [None if i < 50 else float(i) for i in range(100)],
    }
)
BINNING = Binning(FACET_BINS, "rows", values_up_to=FACET_BINS)
G_0_9 = [Filter("g", range=[0.0, 9.0])]
G_0_3 = [Filter("g", range=[0.0, 3.0])]
# The cuts of g 0..9 alone: five intervals of two rows.
CUTS_0_9 = find_cuts(FRAME.lazy().filter(pl.col("g") <= 9), "g", BINNING)


def _spec(tmp_path: Path, **fields: object) -> ScatterSpec:
    """Return a spec of x × y with g on the roles given, cut as the server cuts a numeric facet or symbol."""
    path = tmp_path / "cuts.parquet"
    FRAME.write_parquet(path)
    roles = {r: fields.pop(r, None) for r in ("symbol", "row", "col") if r in fields}
    return ScatterSpec(
        files={c: [str(path)] for c in FRAME.columns},
        **{
            "x": ["x"],
            "y": ["y"],
            "color": None,
            "row": None,
            "col": None,
            "width": 200,
            "height": 200,
            "hover": ["x"],
            "binned": {r: BINNING for r in roles},
            **roles,
            **fields,
        },
    )


def _view(agg: Aggregation, **fields: object) -> View:
    """Return the view of a result's levels and cuts over its ranges."""
    return View(
        **{
            "x_ranges": [list(r) for r in agg.x_ranges],
            "y_ranges": [list(r) for r in agg.y_ranges],
            "levels": agg.all_levels,
            "axis_levels": agg.axis_levels,
            "cuts": agg.cuts,
            **fields,
        }
    )


@pytest.mark.parametrize("role", ["col", "row", "symbol"])
def test_a_filter_cuts_its_own_rows(tmp_path: Path, role: str) -> None:
    """Narrowed to 0..9, g is cut into 5 intervals of those rows (one panel before); narrowed to 0..3, into its 4 values."""
    whole = aggregate(_spec(tmp_path, **{role: "g"}))
    assert len(whole.all_levels[role]) == FACET_BINS
    narrowed = aggregate(_spec(tmp_path, **{role: "g"}, filters=G_0_9))
    assert narrowed.cuts[role] == CUTS_0_9
    assert narrowed.all_levels[role] == cut_labels(narrowed.cuts[role])
    assert len(narrowed.levels[role]) == FACET_BINS
    values = aggregate(_spec(tmp_path, **{role: "g"}, filters=G_0_3))
    assert values.cuts[role] == {"breaks": [0.0, 1.0, 2.0, 3.0, 3.0], "values": True}
    assert values.levels[role] == ["0", "1", "2", "3"]


def test_wrap_cuts_the_rows_of_the_filter(tmp_path: Path) -> None:
    """Wrap's column, on the col role, is cut from the rows of the filter too."""
    spec = _spec(tmp_path, col="g", wrap=True, filters=G_0_9)
    agg = aggregate(spec)
    assert agg.cuts["col"] == CUTS_0_9
    assert len(agg.levels["col"]) == FACET_BINS


def test_without_a_filter_the_cuts_are_of_every_row(tmp_path: Path) -> None:
    """With the filter dropped, the overview's cuts are those of every row again."""
    whole = aggregate(_spec(tmp_path, col="g"))
    narrowed = aggregate(_spec(tmp_path, col="g", filters=G_0_9))
    assert narrowed.cuts["col"] != whole.cuts["col"]
    again = aggregate(_spec(tmp_path, col="g"))
    assert again.cuts == whole.cuts
    assert again.levels == whole.levels


def test_a_filter_without_a_finite_value_takes_every_row(tmp_path: Path) -> None:
    """Column h has no value where g < 50: the overview and a view of that filter cut every row of h."""
    whole = aggregate(_spec(tmp_path, col="h"))
    spec = _spec(tmp_path, col="h", filters=[Filter("g", range=[0.0, 9.0])])
    assert aggregate(spec).cuts["col"] == whole.cuts["col"]
    view = replace(spec, view=_view(whole, find_cuts=["col"]))
    assert aggregate(view).cuts["col"] == whole.cuts["col"]


def test_a_column_on_two_roles_is_cut_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A column g on symbol and col is read once for both."""
    calls = []
    found = foundcolor.found_cuts

    def counted(*args: object, **kwargs: object) -> object:
        calls.append(args[1])
        return found(*args, **kwargs)

    monkeypatch.setattr(foundcolor, "found_cuts", counted)
    agg = aggregate(_spec(tmp_path, symbol="g", col="g", filters=G_0_9))
    assert calls == ["g"]
    assert agg.cuts["symbol"] == agg.cuts["col"]


def test_a_view_finds_the_cuts_of_its_filter_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A view of the same filter (a zoom, a size, a selection) keeps the cuts it is given; one of another filter finds them once; cuts kept by the page are drawn as they are."""
    calls = []
    found = foundcolor.found_cuts

    def counted(*args: object, **kwargs: object) -> object:
        calls.append(args[1])
        return found(*args, **kwargs)

    monkeypatch.setattr(foundcolor, "found_cuts", counted)
    spec = _spec(tmp_path, col="g", symbol="g")
    overview = aggregate(spec)
    # Without a filter, the overview's every row is the cuts: no pass more.
    assert calls == []
    zoomed = replace(spec, view=_view(overview, x_ranges=[[0.0, 5.0]]), width=300)
    assert aggregate(zoomed).cuts == overview.cuts
    assert calls == []
    filtered = replace(
        spec, filters=G_0_9, view=_view(overview, find_cuts=["symbol", "col"])
    )
    stages: list[str] = []
    agg = aggregate(filtered, stages.append)
    assert calls == ["g"]
    assert "cuts" in stages
    assert agg.cuts["col"] == CUTS_0_9
    assert agg.all_levels["col"] == cut_labels(agg.cuts["col"])
    assert agg.all_levels["symbol"] == agg.all_levels["col"]
    assert len(agg.levels["col"]) == FACET_BINS
    calls.clear()
    # The next view of that filter knows the cuts and the names of the levels.
    known = replace(filtered, view=_view(agg, facets=None))
    again = aggregate(known)
    assert calls == []
    assert again.cuts == agg.cuts
    assert again.all_levels == agg.all_levels
    # A selection of that view selects with its cuts, with no pass.
    selection = replace(
        known,
        view=_view(agg, facets={"row": agg.levels["row"], "col": agg.levels["col"]}),
        selection=Selection(
            x="x",
            y="y",
            x_range=[-1.0, 10.0],
            y_range=[-1.0, 10.0],
            col=agg.levels["col"][0],
        ),
    )
    picked = aggregate(selection, selection_only=True)
    assert calls == []
    # The first interval of 0..9 holds two rows.
    assert picked.selected_rows == 2
    # Cuts kept by the page are drawn as they are, with no pass.
    frozen = replace(filtered, kept_cuts={"col": overview.cuts["col"]})
    held = aggregate(frozen)
    assert calls == ["g"]  # The symbol's, not kept, is of the filter.
    assert held.cuts["col"] == overview.cuts["col"]
    assert held.all_levels["col"] == overview.all_levels["col"]
    # The filter leaves the first interval of every row only.
    assert held.levels["col"] == overview.levels["col"][:1]


def test_the_shapes_chosen_stay_with_their_level_names(tmp_path: Path) -> None:
    """A shape chosen for a symbol level stays while a level of its name does; a renamed level takes the default."""
    narrowed = aggregate(_spec(tmp_path, symbol="g", filters=G_0_3))
    names = narrowed.all_levels["symbol"]
    assert names == ["0", "1", "2", "3"]
    spec = _spec(
        tmp_path,
        symbol="g",
        filters=G_0_3,
        level_shapes={"1": "square", "x": "diamond"},
    )
    shapes = spec.marker_shapes(names)
    default = _spec(tmp_path, symbol="g").marker_shapes(names)
    assert shapes[1] == "square"
    assert [s for i, s in enumerate(shapes) if i != 1] == [
        s for i, s in enumerate(default) if i != 1
    ]
