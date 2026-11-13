"""Tasks that read the columns of the input: its schema, their non-null shares, a summary."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ddviz.compute.progress import Emit
from ddviz.compute.summary import summarize_column
from ddviz.compute.temporal import temporal_kind
from ddviz.shared.cache import SCHEMA
from ddviz.shared.generated import generated_names
from ddviz.shared.manifest import write_manifest


def supertype(a: pl.DataType, b: pl.DataType) -> pl.DataType:
    """Return the type both types cast to, by polars' rules (Int32 and Float64 give Float64).

    Raises
    ------
    ValueError
        When the types have none.
    """
    empty = [pl.DataFrame(schema={"c": a}), pl.DataFrame(schema={"c": b})]
    try:
        return pl.concat(empty, how="vertical_relaxed").schema["c"]
    except pl.exceptions.PolarsError as error:
        raise ValueError(f"no common type of {a} and {b}") from error


def run_schema(paths: list[str], out: Path, emit: Emit) -> None:
    """Write the columns of Parquet files read one after another as one table.

    The columns are those of every file, in the order they first appear. A
    column whose type differs between files gets the type all its types
    cast to (`supertype`); such columns are listed as ``casts``, so that the
    page can tell. A file lacking a column holds nulls in it. Two files or
    more add, after them, the String columns of each row's source file
    (`ddviz.shared.generated`), listed as ``generated``.

    Each file is scanned once and dropped before the next, so that only one
    footer is in memory.

    Parameters
    ----------
    paths : list of str
        Parquet files in reading order.
    out : pathlib.Path
        Directory to write the result into: the manifest, with ``columns``
        (``{"name", "dtype", "numeric", "temporal"}`` each: a temporal column
        is numeric, with its kind, `ddviz.compute.temporal.temporal_kind`),
        ``rows``, the rows of each file, ``generated``, the added columns
        with their kinds, and ``schema.parquet``, an empty file with the
        type of every column.
    emit : callable
        Receives a ``progress`` message before each file.
    """
    dtypes: dict[str, pl.DataType] = {}
    # The types of each column found in the files, for those with several.
    variants: dict[str, dict[str, None]] = {}
    rows = []
    for done, path in enumerate(paths):
        emit({"type": "progress", "stage": "schema", "done": done, "total": len(paths)})
        scan = pl.scan_parquet(path)
        for name, dtype in scan.collect_schema().items():
            known = dtypes.get(name)
            if known is None:
                dtypes[name] = dtype
            elif dtype != known:
                variants.setdefault(name, {str(known): None})[str(dtype)] = None
                try:
                    dtypes[name] = supertype(known, dtype)
                except ValueError as error:
                    raise ValueError(f"{name}: {error}") from error
        # The row count comes from the footer the scan has parsed.
        rows.append(scan.select(pl.len()).collect().item())
    generated = generated_names(dtypes, len(paths))
    dtypes.update(dict.fromkeys(generated, pl.String))
    pl.DataFrame(schema=dtypes).write_parquet(out / SCHEMA)
    columns = []
    for name, dtype in dtypes.items():
        kind = temporal_kind(dtype)
        numeric = dtype.is_numeric() or kind is not None
        columns.append(
            {"name": name, "dtype": str(dtype), "numeric": numeric, "temporal": kind}
        )
    casts = [
        {"name": name, "dtypes": list(found), "dtype": str(dtypes[name])}
        for name, found in variants.items()
    ]
    write_manifest(
        out,
        {
            "kind": "schema",
            "columns": columns,
            "rows": rows,
            "casts": casts,
            "generated": generated,
        },
    )


def run_nonnull(
    paths: list[str], names: list[str], generated: list[str], out: Path, emit: Emit
) -> None:
    """Write the non-null values of each column and the rows (`ddviz.compute.nonnull`).

    An added column (`ddviz.shared.generated`) has a value in every row.

    Parameters
    ----------
    paths : list of str
        Parquet files read as one table.
    names : list of str
        Column names, in schema order.
    generated : list of str
        The added columns among them.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    # Imported here, so that standby workers do not load pyarrow.
    from ddviz.compute.nonnull import nonnull_counts

    counts, rows = nonnull_counts(paths, names)
    added = set(generated)
    counts = [
        (rows or None) if name in added else count
        for name, count in zip(names, counts, strict=True)
    ]
    write_manifest(out, {"kind": "nonnull", "counts": counts, "rows": rows})


def run_summary(parts: list[str], column: str, out: Path, emit: Emit) -> None:
    """Write what the filter pane shows of a column (`ddviz.compute.summary`).

    Parameters
    ----------
    parts : list of str
        Parquet files holding the column, read one after another.
    column : str
        The column.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "summary"})
    summary = summarize_column(parts, column)
    write_manifest(out, {"kind": "summary", "column": column, **summary})
