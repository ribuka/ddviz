"""Tests of the facet grid layout."""

from __future__ import annotations

from ddviz.layout import (
    GAP,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    MIN_PANEL_HEIGHT,
    MIN_PANEL_WIDTH,
    SCROLL_GAP_X,
    SCROLL_GAP_Y,
    SCROLLBAR,
    AxisGrid,
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


def test_grid_layout_fills_the_area_while_panels_are_large_enough() -> None:
    """A grid whose panels reach the smallest size fills the given size and does not scroll."""
    layout = grid_layout(1200, 900, nrow=2, ncol=2)
    assert (layout.width, layout.height) == (1200, 900)
    assert not layout.scroll
    assert (layout.gap_x, layout.gap_y) == (GAP, GAP)


def test_grid_layout_scrolls_panels_kept_at_their_smallest() -> None:
    """Panels too small for the size keep the smallest size, and the figure grows past it."""
    layout = grid_layout(1200, 900, nrow=10, ncol=10)
    assert layout.scroll
    assert (layout.panel_width, layout.panel_height) == (
        MIN_PANEL_WIDTH,
        MIN_PANEL_HEIGHT,
    )
    assert layout.width == (
        MARGIN_LEFT + MARGIN_RIGHT + 10 * MIN_PANEL_WIDTH + 9 * SCROLL_GAP_X
    )
    assert layout.height == (
        MARGIN_TOP + MARGIN_BOTTOM + 10 * MIN_PANEL_HEIGHT + 9 * SCROLL_GAP_Y
    )
    lo, hi = layout.x_domain(9)
    assert hi == 1
    assert round((hi - lo) * (layout.width - MARGIN_LEFT - MARGIN_RIGHT)) == (
        MIN_PANEL_WIDTH
    )
    assert layout.y_domain(9)[0] == 0


def test_grid_layout_scrolled_side_that_fits_fills_the_area() -> None:
    """In a scrolled grid, a side with room fills the size left by the scroll bars."""
    layout = grid_layout(3000, 900, nrow=10, ncol=4)
    assert layout.scroll
    assert layout.panel_height == MIN_PANEL_HEIGHT
    assert layout.panel_width > MIN_PANEL_WIDTH
    assert layout.width <= 3000 - SCROLLBAR


def test_axis_grid_nests_axis_columns_in_facet_cells() -> None:
    """Each facet cell holds the x columns side by side and the y columns stacked from the top."""
    axes = AxisGrid(nrow=2, ncol=3, nx=2, ny=3)
    assert (axes.rows, axes.cols) == (6, 6)
    seen = set()
    for row in range(2):
        for col in range(3):
            for yj in range(3):
                for xi in range(2):
                    panel = axes.panel(row, col, xi, yj)
                    assert divmod(panel, 6) == (row * 3 + yj, col * 2 + xi)
                    assert axes.axes(panel) == (xi, yj)
                    seen.add(panel)
    assert seen == set(range(36))


def test_axis_columns_and_facets_share_one_gap() -> None:
    """A fitting grid keeps the same one-pixel gap between axis columns as between facets."""
    axes = AxisGrid(nrow=2, ncol=3, nx=2, ny=3)
    layout = grid_layout(1600, 1200, axes.rows, axes.cols)
    assert not layout.scroll
    assert (layout.gap_x, layout.gap_y) == (GAP, GAP) == (1, 1)
