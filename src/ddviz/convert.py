"""Convert columns of a source Parquet file into the column cache, one file per column."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import polars as pl

from ddviz.cache import PARTIAL

Emit = Callable[[dict], None]


def convert_columns(source: str, files: dict[str, str], emit: Emit) -> None:
    """Write each column of `source` into its own file.

    One scan parses the source's footer once for all the columns. Each column
    is written alone: on 10M rows, writing 100 columns into one file peaked at
    about 5.4GB, against about 0.3GB for one column. A file appears under its
    name only once complete.

    Parameters
    ----------
    source : str
        Parquet file to convert.
    files : dict of str to str
        File to write for each column.
    emit : callable
        Receives a ``progress`` message before each column, with ``done`` and
        ``total`` counts.
    """
    scan = pl.scan_parquet(source)
    total = len(files)
    for done, (column, file) in enumerate(files.items()):
        emit(
            {
                "type": "progress",
                "stage": "convert",
                "column": column,
                "done": done,
                "total": total,
            }
        )
        partial = Path(file + PARTIAL)
        scan.select(column).sink_parquet(partial)
        os.replace(partial, file)
