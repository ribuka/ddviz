"""JS: axisranges.js keeps the axes set by hand and, under the lock, every continuous axis through a new filter or graph."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# `meta(x, y, extra)` makes the meta of a result with one panel per pair of
# axis columns: x and y list the columns, `extra` overrides fields (`x_log`,
# `axis_levels`, `one_band`, the ranges). The whole range of every column
# is [0, 10] and its automatic range [0, 10].
PRELUDE = """
const m = await import("/static/js/axisranges.js");
const meta = (x, y, extra = {}) => {
  const panels = [];
  y.forEach((_, j) => x.forEach((_, i) => {
    const n = panels.length + 1;
    panels.push({ xaxis: n === 1 ? "x" : `x${n}`, yaxis: n === 1 ? "y" : `y${n}`, x: i, y: j });
  }));
  return {
    x_columns: x,
    y_columns: y,
    x_axes: x.map((_, i) => panels.find((p) => p.x === i).xaxis),
    y_axes: y.map((_, j) => panels.find((p) => p.y === j).yaxis),
    x_log: x.map(() => false),
    y_log: y.map(() => false),
    x_ranges: x.map(() => [0, 10]),
    y_ranges: y.map(() => [0, 10]),
    x_auto: x.map(() => [0, 10]),
    y_auto: y.map(() => [0, 10]),
    one_band: false,
    temporal: {},
    axis_levels: {},
    panels,
    ...extra,
  };
};
"""


def _call(page: Page, body: str) -> object:
    """Return what `body` returns, after `PRELUDE`."""
    return page.evaluate(f"async () => {{ {PRELUDE} {body} }}")


def test_continuous_axes_are_not_categorical_nor_the_one_band(js_page: Page) -> None:
    """A categorical axis and the one band are not continuous; a figure of those only has no continuous axis."""
    result = _call(
        js_page,
        """const mixed = meta(["g", "x"], ["y"], { axis_levels: { g: ["a", "b"] } });
        const bands = meta(["one"], ["g"], { one_band: true, axis_levels: { one: [""], g: ["a"] } });
        return [
          m.isContinuous(mixed, "x", 0), m.isContinuous(mixed, "x", 1), m.isContinuous(mixed, "y", 0),
          m.hasContinuous(mixed), m.hasContinuous(bands),
        ];""",
    )
    assert result == [False, True, True, True, False]


def test_off_a_new_filter_keeps_only_the_axes_set_by_hand(js_page: Page) -> None:
    """Unlocked, nothing is kept until an axis is set by hand; then that axis alone keeps its range."""
    result = _call(
        js_page,
        """const r = new m.AxisRanges();
        const a = meta(["x"], ["y"]);
        const shown = { x: [[2, 3]], y: [[4, 5]] };
        const before = r.filterRanges(a, shown);
        r.setByHand(a, "x", 0);
        return [before, r.filterRanges(a, shown)];""",
    )
    assert result == [
        {"x": [None], "y": [None]},
        {"x": [[2, 3]], "y": [None]},
    ]


def test_on_the_lock_keeps_every_continuous_axis_even_over_its_whole_range(
    js_page: Page,
) -> None:
    """Locked, every continuous axis keeps its shown range, whole or zoomed; a categorical axis is not locked."""
    result = _call(
        js_page,
        """const r = new m.AxisRanges();
        const a = meta(["g", "x"], ["y"], { axis_levels: { g: ["a", "b"] } });
        r.setFrozen(true);
        return r.filterRanges(a, { x: [[-0.5, 1.5], [0, 10]], y: [[1, 2]] });""",
    )
    assert result == {"x": [None, [0, 10]], "y": [[1, 2]]}


def test_turning_the_lock_off_drops_the_axes_set_by_hand(js_page: Page) -> None:
    """Off, every axis goes back to its automatic range, those set by hand too; on again keeps them all."""
    result = _call(
        js_page,
        """const r = new m.AxisRanges();
        const a = meta(["x"], ["y"]);
        const shown = { x: [[2, 3]], y: [[4, 5]] };
        r.setByHand(a, "x", 0);
        r.setFrozen(true);
        const on = r.filterRanges(a, shown);
        r.setFrozen(false);
        const off = r.filterRanges(a, shown);
        r.setFrozen(true);
        return [on, off, r.filterRanges(a, shown)];""",
    )
    assert result == [
        {"x": [[2, 3]], "y": [[4, 5]]},
        {"x": [None], "y": [None]},
        {"x": [[2, 3]], "y": [[4, 5]]},
    ]


def test_reset_drops_the_axes_set_by_hand_and_keeps_the_lock(js_page: Page) -> None:
    """Reset axes forgets every axis set by hand, or the one reset; the lock stays on and keeps the ranges gone back to."""
    result = _call(
        js_page,
        """const r = new m.AxisRanges();
        const a = meta(["x", "w"], ["y"]);
        r.setByHand(a, "x", 0);
        r.setByHand(a, "x", 1);
        r.reset(a, "x", 1);
        const one = [r.byHand(a, "x", 0), r.byHand(a, "x", 1)];
        r.reset();
        const all = [r.byHand(a, "x", 0), r.frozen];
        r.setFrozen(true);
        r.reset();
        return [one, all, r.frozen, r.filterRanges(a, { x: [[0, 10], [0, 10]], y: [[0, 10]] })];""",
    )
    assert result == [
        [True, False],
        [False, False],
        True,
        {"x": [[0, 10], [0, 10]], "y": [[0, 10]]},
    ]


def test_the_axes_set_by_hand_are_of_their_role_column_and_coordinates(
    js_page: Page,
) -> None:
    """The same column moved to y, put on a log axis, or taken off and back, is a new axis."""
    result = _call(
        js_page,
        """const r = new m.AxisRanges();
        const a = meta(["x"], ["y"]);
        r.setByHand(a, "x", 0);
        const moved = meta(["y"], ["x"]);
        const logged = meta(["x"], ["y"], { x_log: [true] });
        const kept = r.byHand(meta(["x", "w"], ["y"]), "x", 0);
        const out = [r.byHand(moved, "y", 0), r.byHand(logged, "x", 0), kept];
        // Taken off: the graph drawn without x forgets it.
        r.keepOf(meta(["w"], ["y"]));
        out.push(r.byHand(a, "x", 0));
        return out;""",
    )
    assert result == [False, False, True, False]


def test_an_edit_carries_the_kept_ranges_only(js_page: Page) -> None:
    """Off, an edit keeps the axes set by hand; locked, every continuous axis that stays on its coordinates; a new or log-switched axis takes its new whole range."""
    result = _call(
        js_page,
        """const old = meta(["x", "w"], ["y"]);
        const shown = { x: [[2, 3], [0, 10]], y: [[4, 5]] };
        const next = meta(["x", "w", "v"], ["y"], { x_ranges: [[0, 9], [0, 9], [0, 9]] });
        const r = new m.AxisRanges();
        const none = r.carried(old, shown, next);
        r.setByHand(old, "x", 0);
        const off = r.carried(old, shown, next);
        r.setFrozen(true);
        const on = r.carried(old, shown, next);
        const logged = r.carried(old, shown, meta(["x"], ["y"], { x_log: [true], x_ranges: [[0, 1]] }));
        return [none, off.ranges, on.ranges, logged.ranges];""",
    )
    assert result == [
        None,
        {"x": [[2, 3], [0, 9], [0, 9]], "y": [[0, 10]]},
        {"x": [[2, 3], [0, 10], [0, 9]], "y": [[4, 5]]},
        {"x": [[0, 1]], "y": [[4, 5]]},
    ]


def test_moved_axes_are_the_columns_of_the_relayout_keys(js_page: Page) -> None:
    """The range keys of a relayout name the axis columns moved, once each, whichever panel's axis moved."""
    result = _call(
        js_page,
        """const a = meta(["x", "w"], ["y", "z"]);
        return m.movedAxes(a, {
          "xaxis4.range[0]": 1, "xaxis4.range[1]": 2, "yaxis3.range": [0, 1], "width": 300, "xaxis.autorange": true,
        });""",
    )
    assert result == [{"role": "x", "index": 1}, {"role": "y", "index": 1}]


def test_a_failed_change_goes_back_to_the_snapshot(js_page: Page) -> None:
    """A snapshot restores the lock and the axes set by hand, however they changed since."""
    result = _call(
        js_page,
        """const r = new m.AxisRanges();
        const a = meta(["x"], ["y"]);
        r.setByHand(a, "y", 0);
        r.setFrozen(true);
        const saved = r.snapshot();
        r.setFrozen(false);
        r.restore(saved);
        return [r.frozen, r.byHand(a, "y", 0), m.autoRanges(a)];""",
    )
    assert result == [True, True, {"x": [[0, 10]], "y": [[0, 10]]}]


def test_turning_the_lock_off_keeps_a_categorical_axis_set_by_hand(
    js_page: Page,
) -> None:
    """The lock is of the continuous axes: off, a categorical axis set by hand keeps its range."""
    result = _call(
        js_page,
        """const r = new m.AxisRanges();
        const a = meta(["g"], ["y"], { axis_levels: { g: ["a", "b"] } });
        r.setByHand(a, "x", 0);
        r.setByHand(a, "y", 0);
        r.setFrozen(true);
        r.setFrozen(false, a);
        return [r.byHand(a, "x", 0), r.byHand(a, "y", 0), r.filterRanges(a, { x: [[-0.2, 0.2]], y: [[1, 2]] })];""",
    )
    assert result == [True, False, {"x": [[-0.2, 0.2]], "y": [None]}]


def test_the_lock_is_of_use_with_a_numeric_color(js_page: Page) -> None:
    """A figure without a continuous axis is lockable with a gradient or intervals, not with a categorical color only."""
    result = _call(
        js_page,
        """const bands = { one_band: true, axis_levels: { one: [""], g: ["a"] } };
        const of = (kind) => m.lockable(meta(["one"], ["g"], { ...bands, color: { kind } }));
        return [of("gradient"), of("bins"), of("levels"), m.lockable(meta(["x"], ["y"], { color: { kind: "levels" } }))];""",
    )
    assert result == [True, True, False, True]


def test_the_color_scale_is_kept_under_the_lock_only(js_page: Page) -> None:
    """A view or an overview asks for the color scale drawn with the lock on, and for none off or without a numeric color."""
    result = _call(
        js_page,
        """const ranges = new m.AxisRanges();
        const drawn = meta(["x"], ["y"], { color: { kind: "gradient", scale: { range: [1, 2] } } });
        const levels = meta(["x"], ["y"], { color: { kind: "levels", scale: null } });
        const off = ranges.colorScale(drawn);
        ranges.setFrozen(true);
        return [off, ranges.colorScale(drawn), ranges.colorScale(levels), ranges.colorScale(null)];""",
    )
    assert result == [None, {"range": [1, 2]}, None, None]


def test_an_edit_carries_the_color_scale_of_the_same_color_only(js_page: Page) -> None:
    """Under the lock, a new graph keeps the color scale while the color is the same column of the same kind, cut the same way."""
    result = _call(
        js_page,
        """const ranges = new m.AxisRanges();
        const cuts = { breaks: [0, 1, 2], values: false };
        const bins = meta(["x"], ["y"], { color: { column: "c", kind: "bins", bins: { n: 2, by: "rows" }, scale: cuts } });
        const gradient = meta(["x"], ["y"], { color: { column: "c", kind: "gradient", bins: null, scale: { range: [0, 2] } } });
        const off = ranges.carriedColorScale(bins, "c", { n: 2, by: "rows" });
        ranges.setFrozen(true);
        return [
          off,
          ranges.carriedColorScale(bins, "c", { n: 2, by: "rows" }),
          ranges.carriedColorScale(bins, "c", { n: 3, by: "rows" }),
          ranges.carriedColorScale(bins, "c", { n: 2, by: "values" }),
          ranges.carriedColorScale(bins, "c", null),
          ranges.carriedColorScale(bins, "d", { n: 2, by: "rows" }),
          ranges.carriedColorScale(gradient, "c", null),
          ranges.carriedColorScale(gradient, "c", { n: 2, by: "rows" }),
          ranges.carriedColorScale(null, "c", null),
        ];""",
    )
    cuts = {"breaks": [0, 1, 2], "values": False}
    assert result == [None, cuts, None, None, None, None, {"range": [0, 2]}, None, None]


def test_the_lock_is_of_use_with_a_role_cut_into_intervals(js_page: Page) -> None:
    """A figure without a continuous axis nor a numeric color is lockable with a numeric symbol, row or col cut into intervals."""
    result = _call(
        js_page,
        """const bands = { one_band: true, axis_levels: { one: [""], g: ["a"] }, color: { kind: "levels" } };
        const cut = { breaks: [0, 1], values: false };
        return [
          m.lockable(meta(["one"], ["g"], { ...bands, cuts: { col: cut } })),
          m.lockable(meta(["one"], ["g"], { ...bands, cuts: {} })),
          m.hasCuts(meta(["x"], ["y"], { cuts: { symbol: cut } })),
        ];""",
    )
    assert result == [True, False, True]


def test_the_cuts_are_kept_under_the_lock_only(js_page: Page) -> None:
    """A view or an overview asks for the cuts drawn with the lock on, and for none off or without a role cut."""
    result = _call(
        js_page,
        """const ranges = new m.AxisRanges();
        const cuts = { col: { breaks: [0, 1, 2], values: false } };
        const drawn = meta(["x"], ["y"], { cuts });
        const none = meta(["x"], ["y"], { cuts: {} });
        const off = ranges.cuts(drawn);
        ranges.setFrozen(true);
        return [off, ranges.cuts(drawn), ranges.cuts(none), ranges.cuts(null)];""",
    )
    assert result == [None, {"col": {"breaks": [0, 1, 2], "values": False}}, None, None]


def test_an_edit_carries_the_cuts_of_the_roles_whose_column_stays(js_page: Page) -> None:
    """Under the lock, a new graph keeps the cuts of each role whose column stays on it, wrap's on col; none of a column moved."""
    result = _call(
        js_page,
        """const ranges = new m.AxisRanges();
        const a = { breaks: [0, 1, 2], values: false };
        const b = { breaks: [5, 6], values: true };
        const old = meta(["x"], ["y"], { cuts: { col: a, symbol: b }, cut_columns: { col: "g", symbol: "h" } });
        const off = ranges.carriedCuts(old, { col: "g", symbol: "h" });
        ranges.setFrozen(true);
        return [
          off,
          ranges.carriedCuts(old, { col: "g", symbol: "h" }),
          ranges.carriedCuts(old, { wrap: "g", symbol: "x" }),
          ranges.carriedCuts(old, { row: "g", symbol: "h" }),
          ranges.carriedCuts(old, { row: "g" }),
          ranges.carriedCuts(null, { col: "g" }),
        ];""",
    )
    a = {"breaks": [0, 1, 2], "values": False}
    b = {"breaks": [5, 6], "values": True}
    assert result == [None, {"col": a, "symbol": b}, {"col": a}, {"symbol": b}, None, None]
