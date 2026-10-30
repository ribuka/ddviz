"""Convert columns of the source files into parts of the column cache, one file per column and source file."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl

from ddviz.compute.progress import Emit
from ddviz.shared.cache import PARTIAL
from ddviz.shared.tasks import ConvertTask


def input_dtypes(schema: str, dtypes: dict[str, str]) -> dict[str, pl.DataType]:
    """Return the input's types of columns from its schema file.

    Parameters
    ----------
    schema : str
        Empty Parquet file with the input's type of every column.
    dtypes : dict of str to str
        The columns, with their types as text.

    Returns
    -------
    dict of str to polars.DataType
        The type of each column.
    """
    found = pl.read_parquet_schema(schema)
    return {name: found[name] for name in dtypes}


def column_expr(
    column: str, dtype: str, present: pl.Schema, target: dict[str, pl.DataType]
) -> pl.Expr | None:
    """Return a source file's values of a column in the input's type.

    Parameters
    ----------
    column : str
        The column.
    dtype : str
        The input's type of the column, as text.
    present : polars.Schema
        The columns of the source file.
    target : dict of str to polars.DataType
        The input's types; read only when the file's type differs.

    Returns
    -------
    polars.Expr or None
        The values, cast when the file's type differs; None when the file
        lacks the column.
    """
    if column not in present:
        return None
    if str(present[column]) == dtype:
        return pl.col(column)
    # A supertype cast; a value out of range becomes null.
    return pl.col(column).cast(target[column], strict=False)


def convert_columns(task: ConvertTask, emit: Emit) -> None:
    """Write each column of each source file into its own part.

    Each source file is scanned once, which parses its footer once for all
    its columns. Each part is written alone: on 10M rows, writing 100 columns
    into one file peaked at about 5.4GB, against about 0.3GB for one column.
    A file lacking a column gets a part of nulls in the input's type, made
    without reading the file (100M rows in 0.04s). A part appears under its
    name only once complete.

    Parameters
    ----------
    task : ConvertTask
        The source files and the parts to write.
    emit : callable
        Receives a ``progress`` message before each part, with ``done`` and
        ``total`` counts.
    """
    target: dict[str, pl.DataType] = {}
    total = sum(len(parts) for parts in task.parts)
    done = 0
    for source, parts in zip(task.sources, task.parts, strict=True):
        scan = pl.scan_parquet(source)
        present = scan.collect_schema()
        rows: int | None = None
        for column, file in parts.items():
            emit(
                {
                    "type": "progress",
                    "stage": "convert",
                    "column": column,
                    "done": done,
                    "total": total,
                }
            )
            done += 1
            dtype = task.dtypes[column]
            if (column not in present or str(present[column]) != dtype) and not target:
                target = input_dtypes(task.schema, task.dtypes)
            expr = column_expr(column, dtype, present, target)
            partial = Path(file + PARTIAL)
            partial.parent.mkdir(parents=True, exist_ok=True)
            if expr is not None:
                scan.select(expr).sink_parquet(partial)
            else:
                if rows is None:
                    rows = scan.select(pl.len()).collect().item()
                pl.LazyFrame().select(
                    pl.repeat(None, rows, dtype=target[column]).alias(column)
                ).sink_parquet(partial)
            os.replace(partial, file)
