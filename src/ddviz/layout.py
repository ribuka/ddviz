"""Pixel layout of a facet grid of panels in a figure."""

from __future__ import annotations

from dataclasses import dataclass

# Figure margins in pixels: room for tick labels, facet labels and the legend.
MARGIN_LEFT = 60
MARGIN_RIGHT = 140
MARGIN_TOP = 40
MARGIN_BOTTOM = 50
# Gap between panels in pixels.
GAP = 6


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
    """

    width: int
    height: int
    nrow: int
    ncol: int
    panel_width: int
    panel_height: int

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
        area = self.height - MARGIN_TOP - MARGIN_BOTTOM
        top = row * (self.panel_height + GAP)
        return (1 - (top + self.panel_height) / area, 1 - top / area)


def grid_layout(width: int, height: int, nrow: int, ncol: int) -> GridLayout:
    """Split a figure into a facet grid of equal panels.

    Parameters
    ----------
    width, height : int
        Figure size in pixels.
    nrow, ncol : int
        Facet rows and columns.

    Returns
    -------
    GridLayout
        The layout; each panel is at least one pixel.
    """
    area_w = width - MARGIN_LEFT - MARGIN_RIGHT
    area_h = height - MARGIN_TOP - MARGIN_BOTTOM
    return GridLayout(
        width=width,
        height=height,
        nrow=nrow,
        ncol=ncol,
        panel_width=max((area_w - GAP * (ncol - 1)) // ncol, 1),
        panel_height=max((area_h - GAP * (nrow - 1)) // nrow, 1),
    )
