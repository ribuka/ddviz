"""Pixel layout of a facet grid of panels in a figure."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

# Figure margins in pixels: room for tick labels and facet labels. The axis
# names and the legend are outside the figure. The top margin also holds
# plotly's mode bar (22px high, 2px from the top), which always shows, above
# the facet labels. A grid that scrolls draws its
# labels in strips of the page of the same sizes, along the edges of the
# area it scrolls in (``static/js/sticky.js``).
MARGIN_LEFT = 50
MARGIN_RIGHT = 30
MARGIN_TOP = 54
MARGIN_BOTTOM = 30
# Gap between panels in pixels, between facet cells and between axis columns
# alike, whether the grid fits the given size or scrolls. The figure draws a frame line
# around each plot area (`ddviz.server.figure`) just outside it, so with one pixel
# neighboring panels share one line.
GAP = 1
# Gap between the panel rows of a wrapped grid, in pixels: room for the label
# above each panel. The first row's label is in the top margin.
WRAP_GAP = 18
# Smallest plot area of a panel in pixels. A grid whose panels would be
# smaller grows past the given size, and the page scrolls it.
MIN_PANEL_WIDTH = 160
MIN_PANEL_HEIGHT = 120
# Room left for the page's scroll bars when the grid scrolls.
SCROLLBAR = 17


def left_margin(wanted: int, width: int) -> int:
    """Return the left margin of a figure: the room its y tick labels need, within the area.

    The page measures the room the y tick labels of the figure drawn need
    (``static/js/leftmargin.js``) and asks for it. The margin is never
    below `MARGIN_LEFT`, and grows at most to leave one pixel of the area
    between it and the right margin and the scroll bar: a narrower area
    does not show the labels whole.

    Parameters
    ----------
    wanted : int
        Left margin the page asks for, in pixels.
    width : int
        Width of the area that shows the figure, in pixels.

    Returns
    -------
    int
        The left margin in pixels.
    """
    most = width - MARGIN_RIGHT - SCROLLBAR - 1
    return max(MARGIN_LEFT, min(wanted, most))


def bottom_margin(wanted: int, height: int) -> int:
    """Return the bottom margin of a figure: the room its x tick labels need, within the area.

    The page measures the room the x tick labels of the figure drawn need
    when an angle is set for them (``static/js/leftmargin.js``) and asks for
    it. The margin is never below `MARGIN_BOTTOM`, and grows at most to
    leave one pixel of the area between it and the top margin and the
    scroll bar: a lower area does not show the labels whole.

    Parameters
    ----------
    wanted : int
        Bottom margin the page asks for, in pixels.
    height : int
        Height of the area that shows the figure, in pixels.

    Returns
    -------
    int
        The bottom margin in pixels.
    """
    most = height - MARGIN_TOP - SCROLLBAR - 1
    return max(MARGIN_BOTTOM, min(wanted, most))


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
    scroll : bool
        Whether the panels did not fit the given size at their smallest, so
        the figure is larger than the area and scrolls in it.
    row_gap : int
        Gap between panel rows in pixels: `GAP`, or `WRAP_GAP` for a
        wrapped grid.
    margin_left : int
        Left margin in pixels (`left_margin`): every panel row's y tick
        labels share it.
    margin_bottom : int
        Bottom margin in pixels (`bottom_margin`): every panel column's x
        tick labels share it.
    """

    width: int
    height: int
    nrow: int
    ncol: int
    panel_width: int
    panel_height: int
    scroll: bool = False
    row_gap: int = GAP
    margin_left: int = MARGIN_LEFT
    margin_bottom: int = MARGIN_BOTTOM

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
        area = self.width - self.margin_left - MARGIN_RIGHT
        left = col * (self.panel_width + GAP)
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
        area = self.height - MARGIN_TOP - self.margin_bottom
        top = row * (self.panel_height + self.row_gap)
        return (1 - (top + self.panel_height) / area, 1 - top / area)


@dataclass(frozen=True)
class AxisGrid:
    """Which panel of a figure draws which facet cell and pair of axis columns.

    The facets are outer and the axis columns
    inner: each facet cell holds a panel per pair of an x and a y column, the
    x columns side by side from the left and the y columns stacked from the
    top. Panels count row by row from the top left.

    A wrapped grid (``facet_col_wrap`` of plotly express) lays out the col
    levels alone, `ncol` to a row from the top left, with one pair of axis
    columns: the panel of a level is its index, and the cells after the
    last level are empty.

    Parameters
    ----------
    nrow, ncol : int
        Facet rows and columns.
    nx, ny : int
        Numbers of x and y columns.
    wrap : int
        Number of wrapped col levels, or 0 for a grid of row and col levels.
    """

    nrow: int
    ncol: int
    nx: int = 1
    ny: int = 1
    wrap: int = 0

    @property
    def rows(self) -> int:
        """Panel rows of the figure."""
        return self.nrow * self.ny

    @property
    def cols(self) -> int:
        """Panel columns of the figure."""
        return self.ncol * self.nx

    @property
    def panels(self) -> int:
        """Panels drawn: the cells before the empty ones of a wrapped grid."""
        return self.wrap or self.rows * self.cols

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

    def facet(self, panel: int) -> tuple[int, int]:
        """Return the indices of the row and the col level of a panel.

        Parameters
        ----------
        panel : int
            Panel.

        Returns
        -------
        tuple of int
            ``(row, col)``; in a wrapped grid, the row is 0 and the col is
            the panel's facet cell.
        """
        prow, pcol = divmod(panel, self.cols)
        row, col = prow // self.ny, pcol // self.nx
        if self.wrap:
            return 0, row * self.ncol + col
        return row, col


def wrap_columns(
    n: int,
    width: int,
    height: int,
    margin_left: int = MARGIN_LEFT,
    margin_bottom: int = MARGIN_BOTTOM,
) -> int:
    """Return how many of `n` wrapped panels go to a row so that they are closest to square.

    Parameters
    ----------
    n : int
        Number of panels, at least 1.
    width, height : int
        Size of the area that shows the figure, in pixels.
    margin_left : int, optional
        Left margin in pixels (`left_margin`).
    margin_bottom : int, optional
        Bottom margin in pixels (`bottom_margin`).

    Returns
    -------
    int
        Panels to a row, from 1 to `n`.
    """

    def skew(ncol: int) -> float:
        nrow = math.ceil(n / ncol)
        w = _split(width, margin_left + MARGIN_RIGHT, ncol, GAP)
        h = _split(height, MARGIN_TOP + margin_bottom, nrow, WRAP_GAP)
        return abs(math.log(w / h))

    return min(range(1, n + 1), key=skew)


def facet_grid(
    nrow: int,
    ncol: int,
    nx: int,
    ny: int,
    wrap: bool,
    wrap_cols: int | None,
    width: int,
    height: int,
    margin_left: int = MARGIN_LEFT,
    margin_bottom: int = MARGIN_BOTTOM,
) -> AxisGrid:
    """Return the panels of a figure for its facet levels and axis columns.

    Parameters
    ----------
    nrow, ncol : int
        Numbers of row and col levels.
    nx, ny : int
        Numbers of x and y columns.
    wrap : bool
        Whether the col levels wrap into rows (`AxisGrid`); `nrow`, `nx`
        and `ny` are then 1.
    wrap_cols : int or None
        Wrapped panels to a row, at most `ncol` of them; None for
        `wrap_columns`.
    width, height : int
        Size of the area that shows the figure, in pixels.
    margin_left : int, optional
        Left margin in pixels (`left_margin`).
    margin_bottom : int, optional
        Bottom margin in pixels (`bottom_margin`).

    Returns
    -------
    AxisGrid
        The panels.
    """
    if not wrap:
        return AxisGrid(nrow=nrow, ncol=ncol, nx=nx, ny=ny)
    per_row = min(
        wrap_cols or wrap_columns(ncol, width, height, margin_left, margin_bottom),
        ncol,
    )
    return AxisGrid(nrow=math.ceil(ncol / per_row), ncol=per_row, wrap=ncol)


def _split(size: int, margins: int, n: int, gap: int) -> int:
    """Return the panel size that fills `size` with `n` panels, at least one pixel."""
    return max((size - margins - gap * (n - 1)) // n, 1)


def grid_layout(
    width: int,
    height: int,
    nrow: int,
    ncol: int,
    row_gap: int = GAP,
    margin_left: int = MARGIN_LEFT,
    margin_bottom: int = MARGIN_BOTTOM,
) -> GridLayout:
    """Split a figure into a facet grid of equal panels.

    The panels fill the given size, `GAP` apart. When they would be smaller than
    `MIN_PANEL_WIDTH` by `MIN_PANEL_HEIGHT`, the grid scrolls instead: each
    side is the smallest size or larger to fill the size left by the scroll
    bars, and the figure grows to hold them.

    Parameters
    ----------
    width, height : int
        Size of the area that shows the figure, in pixels.
    nrow, ncol : int
        Panel rows and columns.
    row_gap : int, optional
        Gap between panel rows: `WRAP_GAP` for a wrapped grid.
    margin_left : int, optional
        Left margin in pixels (`left_margin`); a larger one leaves the
        panels less room, and may make the grid scroll.
    margin_bottom : int, optional
        Bottom margin in pixels (`bottom_margin`); a larger one leaves the
        panels less room, and may make the grid scroll.

    Returns
    -------
    GridLayout
        The layout.
    """
    margins_x = margin_left + MARGIN_RIGHT
    margins_y = MARGIN_TOP + margin_bottom
    panel_width = _split(width, margins_x, ncol, GAP)
    panel_height = _split(height, margins_y, nrow, row_gap)
    if panel_width >= MIN_PANEL_WIDTH and panel_height >= MIN_PANEL_HEIGHT:
        return GridLayout(
            width,
            height,
            nrow,
            ncol,
            panel_width,
            panel_height,
            row_gap=row_gap,
            margin_left=margin_left,
            margin_bottom=margin_bottom,
        )
    panel_width = max(_split(width - SCROLLBAR, margins_x, ncol, GAP), MIN_PANEL_WIDTH)
    panel_height = max(
        _split(height - SCROLLBAR, margins_y, nrow, row_gap), MIN_PANEL_HEIGHT
    )
    return GridLayout(
        width=margins_x + ncol * panel_width + (ncol - 1) * GAP,
        height=margins_y + nrow * panel_height + (nrow - 1) * row_gap,
        nrow=nrow,
        ncol=ncol,
        panel_width=panel_width,
        panel_height=panel_height,
        scroll=True,
        row_gap=row_gap,
        margin_left=margin_left,
        margin_bottom=margin_bottom,
    )
