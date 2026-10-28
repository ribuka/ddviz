"""Pixel layout of a facet grid of panels in a figure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

# Figure margins in pixels: room for tick labels and facet labels. The axis
# names and the legend are outside the figure.
MARGIN_LEFT = 50
MARGIN_RIGHT = 30
MARGIN_TOP = 30
MARGIN_BOTTOM = 30
# Gap between panels in pixels when the grid fits the given size.
GAP = 6
# Gap of a fitting grid along a direction with several axis columns: the
# tick labels of neighboring panels differ there and would run together.
AXIS_GAP = 24
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


@dataclass(frozen=True)
class AxisGrid:
    """Which panel of a figure draws which facet cell and pair of axis columns.

    The facets are outer and the axis columns
    inner: each facet cell holds a panel per pair of an x and a y column, the
    x columns side by side from the left and the y columns stacked from the
    top. Panels count row by row from the top left.

    Parameters
    ----------
    nrow, ncol : int
        Facet rows and columns.
    nx, ny : int
        Numbers of x and y columns.
    """

    nrow: int
    ncol: int
    nx: int = 1
    ny: int = 1

    @property
    def gaps(self) -> tuple[int, int]:
        """Gaps between the panels of a fitting grid along x and y."""
        return (
            AXIS_GAP if self.nx > 1 else GAP,
            AXIS_GAP if self.ny > 1 else GAP,
        )

    @property
    def rows(self) -> int:
        """Panel rows of the figure."""
        return self.nrow * self.ny

    @property
    def cols(self) -> int:
        """Panel columns of the figure."""
        return self.ncol * self.nx

    def panel(self, row: T, col: T, xi: T, yj: T) -> T:
        """Return the panel of a facet cell and axis pair; works on ints or polars expressions.

        Parameters
        ----------
        row, col : int or polars.Expr
            Facet row and column.
        xi, yj : int or polars.Expr
            Indices of the x and the y column.

        Returns
        -------
        int or polars.Expr
            The panel.
        """
        return (row * self.ny + yj) * self.cols + col * self.nx + xi

    def axes(self, panel: int) -> tuple[int, int]:
        """Return the indices of the x and the y column of a panel.

        Parameters
        ----------
        panel : int
            Panel.

        Returns
        -------
        tuple of int
            ``(xi, yj)``.
        """
        prow, pcol = divmod(panel, self.cols)
        return pcol % self.nx, prow % self.ny


def _split(size: int, margins: int, n: int, gap: int) -> int:
    """Return the panel size that fills `size` with `n` panels, at least one pixel."""
    return max((size - margins - gap * (n - 1)) // n, 1)


def grid_layout(
    width: int,
    height: int,
    nrow: int,
    ncol: int,
    gap_x: int = GAP,
    gap_y: int = GAP,
) -> GridLayout:
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
        Panel rows and columns.
    gap_x, gap_y : int
        Gaps between the panels when they fit (`AxisGrid.gaps`); a grid that
        scrolls has larger ones.

    Returns
    -------
    GridLayout
        The layout.
    """
    margins_x = MARGIN_LEFT + MARGIN_RIGHT
    margins_y = MARGIN_TOP + MARGIN_BOTTOM
    panel_width = _split(width, margins_x, ncol, gap_x)
    panel_height = _split(height, margins_y, nrow, gap_y)
    if panel_width >= MIN_PANEL_WIDTH and panel_height >= MIN_PANEL_HEIGHT:
        return GridLayout(
            width, height, nrow, ncol, panel_width, panel_height, gap_x, gap_y
        )
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
