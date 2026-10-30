"""Lazy frame over the Parquet files that hold the columns of a plot."""

from __future__ import annotations

import polars as pl


def scan_columns(
    files: dict[str, list[str]], row_index: str | None = None
) -> pl.LazyFrame:
    """Return the columns of `files` side by side as one lazy frame.

    A column is held by a list of files read one after another (its parts
    in the column cache, one per source file) with one scan: on 100M rows
    split into 1,000 files, one scan of the list aggregated in about 4.9s
    and 5.5GB, as one file did in 3.2s and 5.1GB, while concatenating a scan
    per file went past 5.9GB at 100 files. Columns held by the same files
    share a scan; scans of different files are concatenated horizontally, so
    every list must have the same rows in the same order (the column cache
    holds copies of the source's columns).

    Parameters
    ----------
    files : dict of str to list of str
        Parquet files holding each column, in the order of the output columns.
    row_index : str or None
        Name of a row index column to put first. The first scan adds it:
        ``with_row_index`` on 100M rows raised the streaming peak from about
        4.1GB to 6.7GB.

    Returns
    -------
    polars.LazyFrame
        The columns.
    """
    by_file: dict[tuple[str, ...], list[str]] = {}
    for column, paths in files.items():
        by_file.setdefault(tuple(paths), []).append(column)
    head = [] if row_index is None else [row_index]
    parts = [
        pl.scan_parquet(
            list(paths), row_index_name=row_index if i == 0 else None
        ).select((head if i == 0 else []) + columns)
        for i, (paths, columns) in enumerate(by_file.items())
    ]
    frame = parts[0] if len(parts) == 1 else pl.concat(parts, how="horizontal")
    return frame.select(head + list(files))
