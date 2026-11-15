"""JS: selectionbox.js finds the panel of plotly's box and its bounds, and names panels across results."""

from __future__ import annotations

import math

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def _call(page: Page, body: str) -> object:
    """Return what `body` (the body of a function of `m`, the module) returns."""
    return page.evaluate(
        f"""async () => {{
          const m = await import("/static/js/selectionbox.js");
          {body}
        }}"""
    )


def test_panel_key_is_the_facet_and_columns(js_page: Page) -> None:
    """Panels with the same facet, x and y have one key, whatever their axis ids; another facet gives another."""
    result = _call(
        js_page,
        """const a = { facet: ["p"], x: 0, y: 1, xaxis: "x", yaxis: "y" };
        const b = { facet: ["p"], x: 0, y: 1, xaxis: "x3", yaxis: "y3" };
        const c = { ...a, facet: ["q"] };
        return [m.panelKey(a) === m.panelKey(b), m.panelKey(a) === m.panelKey(c)];""",
    )
    assert result == [True, False]


def test_same_panels_needs_the_same_order(js_page: Page) -> None:
    """The same panels in another order are not the same; in the same order they are."""
    result = _call(
        js_page,
        """const p = { facet: ["p"], x: 0, y: 0 };
        const q = { facet: ["q"], x: 0, y: 0 };
        return [
          m.samePanels({ panels: [p, q] }, { panels: [q, p] }),
          m.samePanels({ panels: [p, q] }, { panels: [{ ...p }, { ...q }] }),
        ];""",
    )
    assert result == [False, True]


def test_box_range_takes_log10_on_a_log_axis(js_page: Page) -> None:
    """On a log axis the values become their log10; on a linear axis the range is linear and ascending."""
    result = _call(
        js_page,
        """const linear = { type: "linear", range: [0, 1], r2l: (v) => v };
        const log = { type: "log", range: [0, 3], r2l: (v) => v };
        return [m.boxRange(log, [1000, 10]), m.boxRange(linear, [8, 2])];""",
    )
    assert result[0] == pytest.approx([1, math.log10(1000)])
    assert result[1] == [2, 8]


def test_box_of_finds_the_panel_of_its_axes(js_page: Page) -> None:
    """A box on axes no panel has is null; a box on a panel's axes gives that panel, its key and its bounds."""
    result = _call(
        js_page,
        """const axis = { type: "linear", range: [0, 1], r2l: (v) => v };
        const gd = { _fullLayout: { xaxis2: axis, yaxis2: axis } };
        const meta = {
          panels: [
            { facet: ["p"], x: 0, y: 0, xaxis: "x", yaxis: "y" },
            { facet: ["q"], x: 0, y: 0, xaxis: "x2", yaxis: "y2" },
          ],
        };
        return [
          m.boxOf(gd, meta, { x3: [0, 1], y3: [0, 1] }),
          m.boxOf(gd, meta, { x2: [4, 1], y2: [2, 3] }),
        ];""",
    )
    assert result == [
        None,
        {"panel": 1, "at": '[["q"],0,0]', "x_range": [1, 4], "y_range": [2, 3]},
    ]
