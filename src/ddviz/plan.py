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
        ``"x2"``, ``"y3"`` and so on for the n-th axes, and ``"overlay"``.
    """
    roles = [
        f"{axis}{i + 1}"
        for axis in ("x", "y")
        for i in range(1, len(getattr(encoding, axis)))
    ]
    if encoding.overlay is not None:
        roles.append("overlay")
    return roles


def drawn_columns(encoding: Encoding) -> list[str]:
    """Return the columns a scatter plot of the graph reads.

    Parameters
    ----------
    encoding : Encoding
        The graph.

    Returns
    -------
    list of str
        The first x and y columns and the color, row and col columns, once each.
    """
    columns = [
        *encoding.x[:1],
        *encoding.y[:1],
        encoding.color,
        encoding.row,
        encoding.col,
    ]
    return list(dict.fromkeys(c for c in columns if c is not None))


def scatter_spec(
    encoding: Encoding,
    files: dict[str, str],
    width: int,
    height: int,
    colors: list[str],
) -> ScatterSpec:
    """Return the overview scatter plot of a graph.

    The first x and y columns are drawn, colored by color and faceted by row
    and col; the n-th axes and overlay are left out (`undrawn`). The hover
    shows the drawn columns.

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
    roles = {
        "x": encoding.x[0],
        "y": encoding.y[0],
        "color": encoding.color,
        "row": encoding.row,
        "col": encoding.col,
    }
    hover = drawn_columns(encoding)
    return ScatterSpec(
        files={c: files[c] for c in hover},
        width=width,
        height=height,
        hover=hover,
        colors=colors,
        **roles,
    )
