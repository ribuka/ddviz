"""JS: ranges.js compares axis ranges, reads those on screen and puts them into a layout and into plotly."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def _call(page: Page, body: str, args: object = None) -> object:
    """Return what `body` (the body of a function of `m`, the module, and `args`) returns."""
    return page.evaluate(
        f"""async (args) => {{
          const m = await import("/static/js/ranges.js");
          {body}
        }}""",
        args,
    )


def test_same_range_allows_a_tiny_part_of_the_span(js_page: Page) -> None:
    """Ranges equal up to 1e-9 of the span are the same; a bound off by 0.1 of 10 is another."""
    result = _call(
        js_page,
        "return [m.sameRange([0, 10], [1e-9, 10]), m.sameRange([0, 10], [0, 10.1])];",
    )
    assert result == [True, False]


def test_same_ranges_needs_the_same_length(js_page: Page) -> None:
    """Lists of ranges of different lengths differ, even when the shared ones are equal."""
    result = _call(
        js_page,
        "return [m.sameRanges([[0, 1]], [[0, 1], [2, 3]]), m.sameRanges([[0, 1], [2, 3]], [[0, 1], [2, 3]])];",
    )
    assert result == [False, True]


def test_same_order_tells_a_reversed_range(js_page: Page) -> None:
    """An ascending and a descending range run differently; two ascending ones the same way."""
    result = _call(js_page, "return [m.sameOrder([0, 1], [5, 2]), m.sameOrder([0, 1], [2, 5])];")
    assert result == [False, True]


def test_same_size_compares_the_four_fields(js_page: Page) -> None:
    """A null size is never the same; sizes with the same width, height and margins are."""
    result = _call(
        js_page,
        """const a = { width: 800, height: 600, margin_left: 60, margin_bottom: 50 };
        return [
          m.sameSize(null, a),
          m.sameSize(a, null),
          m.sameSize(null, null),
          m.sameSize(a, { ...a }),
          m.sameSize(a, { ...a, margin_bottom: 51 }),
        ];""",
    )
    assert result == [False, False, False, True, False]


def test_with_ranges_sets_each_panels_axes_and_keeps_the_rest(js_page: Page) -> None:
    """Each panel's x and y axis takes the range of its columns; the other keys of the layout and the axes stay."""
    result = _call(
        js_page,
        """const meta = {
          panels: [
            { xaxis: "x", yaxis: "y", x: 0, y: 0 },
            { xaxis: "x2", yaxis: "y2", x: 1, y: 0 },
          ],
        };
        const layout = {
          xaxis: { range: [0, 1], title: "a" },
          xaxis2: { range: [0, 1] },
          yaxis: { range: [0, 1], type: "log" },
          yaxis2: { range: [0, 1] },
          width: 800,
        };
        return m.withRanges(layout, meta, { x: [[1, 2], [3, 4]], y: [[5, 6]] });""",
    )
    assert result == {
        "xaxis": {"range": [1, 2], "title": "a"},
        "xaxis2": {"range": [3, 4]},
        "yaxis": {"range": [5, 6], "type": "log"},
        "yaxis2": {"range": [5, 6]},
        "width": 800,
    }


def test_figure_key_ignores_the_ranges_and_ticks(js_page: Page) -> None:
    """Layouts that differ only in the axes' range, tickvals and ticktext have one key; another title makes another."""
    result = _call(
        js_page,
        """const data = [{ type: "scatter" }];
        const a = { xaxis: { range: [0, 1], tickvals: [0], ticktext: ["a"], title: "x" }, yaxis2: { range: [0, 1] } };
        const b = { xaxis: { range: [5, 9], tickvals: [1, 2], ticktext: ["b", "c"], title: "x" }, yaxis2: { range: [3, 4] } };
        const c = { ...a, xaxis: { ...a.xaxis, title: "other" } };
        return [m.figureKey(data, a) === m.figureKey(data, b), m.figureKey(data, a) === m.figureKey(data, c)];""",
    )
    assert result == [True, False]


def test_axis_coordinates_differ_by_scale_kind_and_levels(js_page: Page) -> None:
    """Another log scale, temporal kind or set of levels of the column gives other coordinates; the same meta the same."""
    result = _call(
        js_page,
        """const base = {
          one_band: false,
          x_columns: ["a"],
          x_log: [false],
          temporal: {},
          axis_levels: {},
        };
        const key = (meta) => m.axisCoordinates(meta, "x", 0);
        return [
          key(base) === key({ ...base }),
          key(base) === key({ ...base, x_log: [true] }),
          key(base) === key({ ...base, temporal: { a: "date" } }),
          key(base) === key({ ...base, axis_levels: { a: ["p", "q"] } }),
        ];""",
    )
    assert result == [True, False, False, False]


def test_same_axes_needs_a_range_per_axis_column(js_page: Page) -> None:
    """A kept view fits a result only with as many x and y ranges as the result has axis columns."""
    result = _call(
        js_page,
        """const keep = { ranges: { x: [[0, 1]], y: [[0, 1], [2, 3]] } };
        return [
          m.sameAxes(keep, { x_axes: ["x"], y_axes: ["y", "y2"] }),
          m.sameAxes(keep, { x_axes: ["x", "x2"], y_axes: ["y", "y2"] }),
        ];""",
    )
    assert result == [True, False]


# A plain object for plotly's graph div: a linear axis, a date axis whose
# `r2l` reads date text as milliseconds, and a reversed axis.
FAKE_GD = """
const axis = (range, extra = {}) => ({ range, r2l: (v) => (typeof v === "string" ? Date.parse(v.replace(" ", "T") + "Z") : v), ...extra });
const gd = {
  _fullLayout: {
    xaxis: axis([0, 10]),
    xaxis2: axis(["2026-01-01 00:00:00", "2026-01-02 00:00:00"], { type: "date" }),
    yaxis: axis([5, 1]),
  },
  layout: { xaxis: { tickvals: [1, 2], ticktext: ["a", "b"] } },
};
"""


def test_shown_ranges_reads_the_axes_as_ascending_numbers(js_page: Page) -> None:
    """The ranges on screen are numbers (a date axis's milliseconds), ascending on a reversed axis."""
    result = _call(
        js_page,
        FAKE_GD + 'return m.shownRanges(gd, { x_axes: ["x", "x2"], y_axes: ["y"] });',
    )
    day = 86_400_000
    start = 1_767_225_600_000  # 2026-01-01 00:00 UTC
    assert result == {"x": [[0, 10], [start, start + day]], "y": [[1, 5]]}


def test_range_update_sets_only_what_differs(js_page: Page) -> None:
    """Only the ranges and ticks that differ from the drawn axes go to the relayout, a date axis's range as date text; none differing is null."""
    result = _call(
        js_page,
        FAKE_GD
        + """const start = Date.parse("2026-01-01T00:00:00Z");
        return [
          m.rangeUpdate(gd, {
            xaxis: { range: [0, 10], tickvals: [1, 2], ticktext: ["a", "b"] },
            xaxis2: { type: "date", range: [start, start + 3_600_000] },
            yaxis: { range: [5, 1], tickvals: [3] },
            width: 800,
          }),
          m.rangeUpdate(gd, { xaxis: { range: [0, 10], tickvals: [1, 2] } }),
        ];""",
    )
    assert result == [
        {
            "xaxis2.range": ["2026-01-01 00:00:00", "2026-01-01 01:00:00"],
            "yaxis.tickvals": [3],
        },
        None,
    ]
