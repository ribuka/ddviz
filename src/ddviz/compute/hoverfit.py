"""Chooses the hover columns a plot task writes so that its hover files fit their limit.

The hover files of a result (`ddviz.compute.tasks.plot.run_plot`) grow with
its non-empty bins: per bin a key, a count, a row index and a value of each
hover column. When they would pass the limit (`ScatterSpec.hover_bytes`),
the columns off the axes go first, the last of the hover first; when even
the axis columns pass it, the result has no hover files at all.
"""

from __future__ import annotations

from collections.abc import Sequence

# Bytes of the header numpy writes before the data of a ``.npy`` file.
NPY_HEADER = 128
# Bytes per bin of keys.npy (int64), count.npy (uint32) and index.npy (int64).
BIN_BYTES = 8 + 4 + 8


def hover_size(n_bins: int, occupancy_bytes: int, column_bytes: Sequence[int]) -> int:
    """Return the bytes of a result's hover files.

    Parameters
    ----------
    n_bins : int
        Non-empty bins of the result.
    occupancy_bytes : int
        Bytes of the occupancy bitmask's data.
    column_bytes : sequence of int
        Bytes per bin of each hover column written.

    Returns
    -------
    int
        The bytes of keys, count, index, occupancy and the columns, with
        their headers.
    """
    files = 4 + len(column_bytes)
    return (
        n_bins * (BIN_BYTES + sum(column_bytes)) + occupancy_bytes + files * NPY_HEADER
    )


def fit_hover(
    columns: dict[str, int],
    axes: Sequence[str],
    n_bins: int,
    occupancy_bytes: int,
    limit: int | None,
) -> list[str] | None:
    """Return the hover columns to write within a limit of bytes.

    Parameters
    ----------
    columns : dict of str to int
        Bytes per bin of each hover column, in the hover's order.
    axes : sequence of str
        The x and y columns, which are kept while the files can have any.
    n_bins : int
        Non-empty bins of the result.
    occupancy_bytes : int
        Bytes of the occupancy bitmask's data.
    limit : int or None
        Most bytes of the hover files; None for no limit.

    Returns
    -------
    list of str or None
        The columns kept, in the hover's order; None when the files do not
        fit even with the axis columns alone.
    """
    kept = list(columns)
    if limit is None:
        return kept

    def fits(names: list[str]) -> bool:
        size = hover_size(n_bins, occupancy_bytes, [columns[c] for c in names])
        return size <= limit

    others = [c for c in reversed(kept) if c not in axes]
    while not fits(kept):
        if not others:
            return None
        kept.remove(others.pop(0))
    return kept
