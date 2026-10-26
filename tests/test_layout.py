"""Tests of the facet grid layout."""

from __future__ import annotations

from ddviz.layout import (
    GAP,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    grid_layout,
)


def test_grid_layout_panels_fit_with_gaps() -> None:
    """Panels are equal, separated by GAP, and fit inside the margins."""
    layout = grid_layout(1000, 700, nrow=3, ncol=4)
    area_w = 1000 - MARGIN_LEFT - MARGIN_RIGHT
    area_h = 700 - MARGIN_TOP - MARGIN_BOTTOM
    assert layout.panel_width == (area_w - 3 * GAP) // 4
    lo, hi = layout.x_domain(3)
    assert round((hi - lo) * area_w) == layout.panel_width
    assert hi <= 1
    top_lo, top_hi = layout.y_domain(0)
    assert top_hi == 1
    assert round((top_hi - top_lo) * area_h) == layout.panel_height
    assert layout.y_domain(2)[0] >= 0
