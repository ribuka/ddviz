"""Pixel layout of a facet grid of panels in a figure."""

from __future__ import annotations

from dataclasses import dataclass

# Figure margins in pixels: room for tick labels, facet labels and the legend.
MARGIN_LEFT = 60
MARGIN_RIGHT = 140
MARGIN_TOP = 40
MARGIN_BOTTOM = 50
# Gap between panels in pixels when the grid fits the given size.
GAP = 6
# Smallest plot area of a panel in pixels. A grid whose panels would be
# smaller grows past the given size, and the page scrolls it.
MIN_PANEL_WIDTH = 160
MIN_PANEL_HEIGHT = 120
# Gaps of a scrolled grid, where every panel has its own tick labels (left
# of it) and its own tick labels and facet title (below and above it), so a
# panel scrolled away from the outer ones can still be read.
SCROLL_GAP_X = 50
SCROLL_GAP_Y = 44
# Room left for the page's scroll bars when the grid scrolls.
SCROLLBAR = 17


@dataclass(frozen=True)
class GridLayout:
    """Where each panel's plot area lies in a figure.

    Parameters
    ----------
    width, height : int
        Figure size in pixels.
    nrow, ncol : int
        Facet rows and columns.
    panel_width, panel_height : int
        Size of one panel's plot area in pixels.
    gap_x, gap_y : int
        Gaps between panels in pixels.
    scroll : bool
        Whether the panels did not fit the given size at their smallest, so
        the figure is larger and every panel carries its own tick labels and
        facet title.
    """

    width: int
    height: int
    nrow: int
    ncol: int
    panel_width: int
    panel_height: int
    gap_x: int = GAP
    gap_y: int = GAP
    scroll: bool = False

    def x_domain(self, col: int) -> tuple[float, float]:
        """Return the plotly x domain of a facet column.

        Parameters
        ----------
        col : int
            Facet column.

        Returns
        -------
        tuple of float
            Start and end as fractions of the plot area width.
        """
        area = self.width - MARGIN_LEFT - MARGIN_RIGHT
        left = col * (self.panel_width + self.gap_x)
        return (left / area, (left + self.panel_width) / area)

    def y_domain(self, row: int) -> tuple[float, float]:
        """Return the plotly y domain of a facet row; row 0 is the top.

        Parameters
        ----------
        row : int
            Facet row.

        Returns
        -------
        tuple of float
            Start and end as fractions of the plot area height, from the bottom.
        """
        area = self.height - MARGIN_TOP - MARGIN_BOTTOM
        top = row * (self.panel_height + self.gap_y)
        return (1 - (top + self.panel_height) / area, 1 - top / area)


def _split(size: int, margins: int, n: int, gap: int) -> int:
    """Return the panel size that fills `size` with `n` panels, at least one pixel."""
    return max((size - margins - gap * (n - 1)) // n, 1)


def grid_layout(width: int, height: int, nrow: int, ncol: int) -> GridLayout:
    """Split a figure into a facet grid of equal panels.

    The panels fill the given size. When they would be smaller than
    `MIN_PANEL_WIDTH` by `MIN_PANEL_HEIGHT`, the grid scrolls instead: each
    side is the smallest size or larger to fill the size left by the scroll
    bars, and the figure grows to hold them.

    Parameters
    ----------
    width, height : int
        Size of the area that shows the figure, in pixels.
    nrow, ncol : int
        Facet rows and columns.

    Returns
    -------
    GridLayout
        The layout.
    """
    margins_x = MARGIN_LEFT + MARGIN_RIGHT
    margins_y = MARGIN_TOP + MARGIN_BOTTOM
    panel_width = _split(width, margins_x, ncol, GAP)
    panel_height = _split(height, margins_y, nrow, GAP)
    if panel_width >= MIN_PANEL_WIDTH and panel_height >= MIN_PANEL_HEIGHT:
        return GridLayout(width, height, nrow, ncol, panel_width, panel_height)
    panel_width = max(
        _split(width - SCROLLBAR, margins_x, ncol, SCROLL_GAP_X), MIN_PANEL_WIDTH
    )
    panel_height = max(
        _split(height - SCROLLBAR, margins_y, nrow, SCROLL_GAP_Y), MIN_PANEL_HEIGHT
    )
    return GridLayout(
        width=margins_x + ncol * panel_width + (ncol - 1) * SCROLL_GAP_X,
        height=margins_y + nrow * panel_height + (nrow - 1) * SCROLL_GAP_Y,
        nrow=nrow,
        ncol=ncol,
        panel_width=panel_width,
        panel_height=panel_height,
        gap_x=SCROLL_GAP_X,
        gap_y=SCROLL_GAP_Y,
        scroll=True,
    )
