"""JS: panelarea.js gives the plot area of a panel and whether a point is in it."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

IMPORT = 'const m = await import("/static/js/panelarea.js");'


def test_area_of_spans_the_offsets_and_lengths(js_page: Page) -> None:
    """The area runs from each axis's offset to its offset plus its length."""
    area = js_page.evaluate(
        f"""async () => {{ {IMPORT}
          return m.areaOf({{ _offset: 10, _length: 100 }}, {{ _offset: 20, _length: 50 }});
        }}"""
    )
    assert area == {"left": 10, "top": 20, "right": 110, "bottom": 70}


def test_in_area_includes_the_edges(js_page: Page) -> None:
    """Both corners are in the area; a pixel left of it or below it is not."""
    found = js_page.evaluate(
        f"""async () => {{ {IMPORT}
          const area = {{ left: 10, top: 20, right: 110, bottom: 70 }};
          return [[10, 20], [110, 70], [9, 20], [110, 71]].map(([x, y]) => m.inArea(area, x, y));
        }}"""
    )
    assert found == [True, True, False, False]


def test_panel_area_needs_both_axes(js_page: Page) -> None:
    """A panel whose y axis is not laid out has no area; one with both axes has its axes' area."""
    areas = js_page.evaluate(
        f"""async () => {{ {IMPORT}
          const full = {{ xaxis: {{ _offset: 10, _length: 100 }}, yaxis: {{ _offset: 20, _length: 50 }} }};
          return [
            m.panelArea(full, {{ xaxis: "x", yaxis: "y2" }}),
            m.panelArea(full, {{ xaxis: "x", yaxis: "y" }}),
          ];
        }}"""
    )
    assert areas == [None, {"left": 10, "top": 20, "right": 110, "bottom": 70}]
