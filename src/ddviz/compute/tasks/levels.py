"""Tasks of the filter card that searches a column's levels: its index and a search of it."""

from __future__ import annotations

from pathlib import Path

from ddviz.compute.levelindex import build_index, search_index
from ddviz.compute.progress import Emit
from ddviz.shared.manifest import write_manifest


def run_level_index(
    parts: list[str], column: str, index: str, out: Path, emit: Emit
) -> None:
    """Write the index of a column's levels (`ddviz.compute.levelindex.build_index`).

    Parameters
    ----------
    parts : list of str
        Parquet files holding the column, read one after another.
    column : str
        The column.
    index : str
        Where the index goes.
    out : pathlib.Path
        Directory to write the result into: the manifest, with ``index``
        (None for a column with too many levels) and ``n_levels``.
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "level_index"})
    built = build_index(parts, column, Path(index))
    write_manifest(out, {"kind": "level_index", "column": column, **built})


def run_level_search(index: str, query: str, order: str, out: Path, emit: Emit) -> None:
    """Write the levels of an index that match a search (`ddviz.compute.levelindex.search_index`).

    Parameters
    ----------
    index : str
        The index.
    query : str
        The search input.
    order : str
        ``"name"`` or ``"count"``.
    out : pathlib.Path
        Directory to write the result into: the manifest, with ``levels``,
        ``truncated`` and ``n_levels``.
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "level_search"})
    found = search_index(Path(index), query, order)
    write_manifest(out, {"kind": "level_search", **found})
