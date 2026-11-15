"""JS: resulttext.js writes the rows of a result and the size of its markers."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def test_rows_text_tells_the_filter_and_what_is_drawn(js_page: Page) -> None:
    """The rows take separators, the place given, and notes for the filter, outliers only and no points."""
    result = js_page.evaluate(
        """async () => {
          const { rowsText } = await import("/static/js/resulttext.js");
          const points = { points: true, boxes: [] };
          const outliers = { points: false, boxes: [{}] };
          const lines = { points: false, boxes: [] };
          const meta = (panels, filters = []) => ({ rows: 1234, filters, panels });
          return [
            rowsText(meta([points])),
            rowsText(meta([points], [{ column: "a" }]), "表示範囲に "),
            rowsText(meta([outliers])),
            rowsText(meta([lines])),
          ];
        }"""
    )
    assert result == [
        "1,234 行",
        "表示範囲に 1,234 行（フィルタ後）",
        "1,234 行（外れ値）",
        "1,234 行（点は描いていない）",
    ]


def test_marker_size_text_is_a_size_or_a_range(js_page: Page) -> None:
    """One size is written alone; symbol levels of their own sizes give the range from the smallest to the largest."""
    result = js_page.evaluate(
        """async () => {
          const { markerSizeText } = await import("/static/js/resulttext.js");
          return [
            markerSizeText({ marker_size: 5 }),
            markerSizeText({ marker_size: 5, symbol: { sizes: [] } }),
            markerSizeText({ marker_size: 5, symbol: { sizes: [7, 3, 11] } }),
          ];
        }"""
    )
    assert result == ["5 px", "5 px", "3〜11 px"]
