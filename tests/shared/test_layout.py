"""Tests of the facet grid layout."""

from __future__ import annotations

from ddviz.shared.layout import (
    GAP,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    MIN_PANEL_HEIGHT,
    MIN_PANEL_WIDTH,
    SCROLLBAR,
    WRAP_GAP,
    AxisGrid,
    facet_grid,
    grid_layout,
    wrap_columns,
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


def test_grid_layout_scrolls_panels_kept_at_their_smallest() -> None:
    """Panels too small for the size keep the smallest size, and the figure grows past it."""
    layout = grid_layout(1200, 900, nrow=10, ncol=10)
    assert layout.scroll
    assert (layout.panel_width, layout.panel_height) == (
        MIN_PANEL_WIDTH,
        MIN_PANEL_HEIGHT,
    )
    assert layout.width == (MARGIN_LEFT + MARGIN_RIGHT + 10 * MIN_PANEL_WIDTH + 9 * GAP)
    assert layout.height == (
        MARGIN_TOP + MARGIN_BOTTOM + 10 * MIN_PANEL_HEIGHT + 9 * GAP
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
    """Axis columns and facets are one pixel apart, whether the grid fits or scrolls."""
    axes = AxisGrid(nrow=2, ncol=3, nx=2, ny=3)
    assert GAP == 1
    for size in ((1600, 1200), (600, 400)):
        layout = grid_layout(*size, axes.rows, axes.cols)
        area = layout.width - MARGIN_LEFT - MARGIN_RIGHT
        gap = (layout.x_domain(1)[0] - layout.x_domain(0)[1]) * area
        assert round(gap) == GAP


def test_wrap_columns_makes_the_panels_closest_to_square() -> None:
    """A wide area puts more wrapped panels in a row than a tall one."""
    assert wrap_columns(1, 1000, 500) == 1
    assert wrap_columns(6, 2000, 400) == 6
    assert wrap_columns(6, 680, 960) == 2
    assert wrap_columns(4, 1000, 1000) == 2


def test_a_wrapped_grid_lays_out_the_col_levels_in_rows() -> None:
    """Five levels three to a row make two rows; the sixth cell is empty."""
    axes = facet_grid(1, 5, 1, 1, True, 3, 900, 600)
    assert axes == AxisGrid(nrow=2, ncol=3, wrap=5)
    assert axes.panels == 5
    assert [axes.facet(p) for p in range(5)] == [(0, i) for i in range(5)]
    assert axes.panel(1, 1, 0, 0) == 4
    # More to a row than levels puts them all in one row.
    assert facet_grid(1, 2, 1, 1, True, 5, 900, 600) == AxisGrid(1, 2, wrap=2)
    # Without wrap, the levels make the grid as they are.
    assert facet_grid(2, 3, 1, 2, False, 3, 900, 600) == AxisGrid(2, 3, 1, 2)
    assert AxisGrid(2, 3, 1, 2).facet(4) == (0, 1)


def test_a_wrapped_grid_leaves_room_between_its_rows() -> None:
    """Panel rows are WRAP_GAP apart, for the labels above the panels."""
    layout = grid_layout(1000, 700, nrow=2, ncol=3, row_gap=WRAP_GAP)
    area_h = 700 - MARGIN_TOP - MARGIN_BOTTOM
    assert layout.panel_height == (area_h - WRAP_GAP) // 2
    gap = layout.y_domain(0)[0] - layout.y_domain(1)[1]
    assert round(gap * area_h) == WRAP_GAP
    scrolled = grid_layout(400, 300, nrow=3, ncol=1, row_gap=WRAP_GAP)
    assert scrolled.scroll
    assert scrolled.height == (
        MARGIN_TOP + MARGIN_BOTTOM + 3 * scrolled.panel_height + 2 * WRAP_GAP
    )
