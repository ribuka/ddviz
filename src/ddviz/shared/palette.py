"""Series colors."""

from __future__ import annotations

# plotly's default qualitative colors, so the legend looks like plotly's.
DEFAULT_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


def series_color(colors: list[str], series: int) -> str:
    """Return the color of a series, cycling over `colors`.

    Parameters
    ----------
    colors : list of str
        Colors as ``#rrggbb``; the defaults when empty.
    series : int
        Series index.

    Returns
    -------
    str
        The color.
    """
    colors = colors or DEFAULT_COLORS
    return colors[series % len(colors)]
