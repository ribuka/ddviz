"""Turns the graph the user built (`ddviz.encoding.Encoding`) into what a worker draws."""

from __future__ import annotations

from ddviz.encoding import Encoding
from ddviz.scatter import ScatterSpec


def undrawn(encoding: Encoding) -> list[str]:
    """Return the roles that are placed but cannot be drawn yet.

    Parameters
    ----------
    encoding : Encoding
        The graph.

    Returns
    -------
    list of str
        ``["overlay"]`` when overlay has a column, else empty.
    """
    return ["overlay"] if encoding.overlay is not None else []


def drawn_columns(encoding: Encoding) -> list[str]:
    """Return the columns a scatter plot of the graph reads.

    Parameters
    ----------
    encoding : Encoding
        The graph.

    Returns
    -------
    list of str
        The x and y columns and the color, row and col columns, once each.
    """
    columns = [*encoding.x, *encoding.y, encoding.color, encoding.row, encoding.col]
    return list(dict.fromkeys(c for c in columns if c is not None))


def scatter_spec(
    encoding: Encoding,
    files: dict[str, str],
    width: int,
    height: int,
    colors: list[str],
) -> ScatterSpec:
    """Return the overview scatter plot of a graph.

    Every pair of an x and a y column is drawn in a panel of each facet
    cell, colored by color and faceted by row and col; overlay is left out
    (`undrawn`). The hover shows the drawn columns.

    Parameters
    ----------
    encoding : Encoding
        The graph.
    files : dict of str to str
        Parquet file to read each drawn column from.
    width, height : int
        Figure size in pixels.
    colors : list of str
        Series colors as ``#rrggbb``.

    Returns
    -------
    ScatterSpec
        What the worker aggregates.

    Raises
    ------
    ValueError
        When x or y has no column.
    """
    if not encoding.x or not encoding.y:
        raise ValueError("x and y need a column")
    hover = drawn_columns(encoding)
    return ScatterSpec(
        files={c: files[c] for c in hover},
        x=list(encoding.x),
        y=list(encoding.y),
        color=encoding.color,
        row=encoding.row,
        col=encoding.col,
        width=width,
        height=height,
        hover=hover,
        colors=colors,
    )
