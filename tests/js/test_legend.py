"""JS: legend.js starts every level active again for other series, and keeps their state for the same ones."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def test_other_series_start_active_and_the_same_keep_their_state(js_page: Page) -> None:
    """`Legend.set` with other color levels empties the inactive levels and series; the same levels keep them."""
    result = js_page.evaluate(
        """async () => {
          const { Legend } = await import("/static/js/legend.js");
          const element = document.createElement("div");
          document.body.append(element);
          const meta = (series) => ({
            series,
            symbol: null,
            colors: series.map(() => "#123456"),
            color: { column: "g", kind: "levels", shapes: 1 },
            images: series.map(() => ({})),
            line_images: [],
            panels: [],
            grid: { n_series: series.length },
          });
          const legend = new Legend(element, () => {}, () => {}, () => {});
          legend.set(meta(["a", "b", "c"]));
          legend.toggle("color", 1);
          const off = () => ({ levels: [...legend.off.color], series: [...legend.inactive] });
          const before = off();
          legend.set(meta(["a", "b", "c"]));
          const same = off();
          legend.set(meta(["b", "c"]));
          const other = off();
          element.remove();
          return { before, same, other };
        }"""
    )
    assert result["before"] == {"levels": [1], "series": [1]}
    assert result["same"] == result["before"]
    assert result["other"] == {"levels": [], "series": []}
