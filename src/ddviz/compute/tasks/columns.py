"""Tasks that read the columns of the file: its schema, their non-null shares, a summary."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ddviz.compute.progress import Emit
from ddviz.compute.summary import summarize_column
from ddviz.shared.manifest import write_manifest


def run_schema(path: str, out: Path, emit: Emit) -> None:
    """Write the column names and types of a Parquet file.

    Parameters
    ----------
    path : str
        Parquet file.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    schema = pl.scan_parquet(path).collect_schema()
    columns = [
        {"name": name, "dtype": str(dtype), "numeric": dtype.is_numeric()}
        for name, dtype in schema.items()
    ]
    write_manifest(out, {"kind": "schema", "columns": columns})


def run_nonnull(path: str, names: list[str], out: Path, emit: Emit) -> None:
    """Write the share of non-null values of each column (`ddviz.compute.nonnull`).

    Parameters
    ----------
    path : str
        Parquet file.
    names : list of str
        Column names, in schema order.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    # Imported here, so that standby workers do not load pyarrow.
    from ddviz.compute.nonnull import nonnull_shares

    shares = nonnull_shares(path, names)
    write_manifest(out, {"kind": "nonnull", "shares": shares})


def run_summary(file: str, column: str, out: Path, emit: Emit) -> None:
    """Write what the filter pane shows of a column (`ddviz.compute.summary`).

    Parameters
    ----------
    file : str
        Parquet file holding the column.
    column : str
        The column.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "summary"})
    summary = summarize_column(file, column)
    write_manifest(out, {"kind": "summary", "column": column, **summary})
