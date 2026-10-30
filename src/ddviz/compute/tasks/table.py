"""Task that reads a page of the selected rows for the selection table."""

from __future__ import annotations

import bisect
import itertools
import math
from pathlib import Path

import polars as pl

from ddviz.compute.aggregate import INDEX
from ddviz.compute.convert import column_expr, input_dtypes
from ddviz.compute.progress import Emit
from ddviz.compute.scan import scan_columns
from ddviz.compute.selection import selection_columns, selection_filter
from ddviz.shared.manifest import write_manifest
from ddviz.shared.tasks import SourceFiles, TableTask

# Rows of a table page further apart than this are read with separate
# slices; closer ones with one slice over the rows between them.
TABLE_GAP = 10_000


def _json_value(value: object) -> object:
    """Return a cell value that JSON can carry: NaN and infinities as text."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _spans(rows: list[int]) -> list[tuple[int, int]]:
    """Return slices (start, length) covering sorted rows, split where they are far apart."""
    spans: list[list[int]] = []
    for r in rows:
        if spans and r - spans[-1][1] <= TABLE_GAP:
            spans[-1][1] = r
        else:
            spans.append([r, r])
    return [(lo, hi - lo + 1) for lo, hi in spans]


def _cached_rows(parts: dict[str, list[str]], index: list[int]) -> pl.DataFrame:
    """Return the rows `index` of columns in the column cache, with the row index."""
    # One lazy frame for every slice: a new scan parses the footers again.
    # Slices are read one after another; reading 100 rows spread over 100 row
    # groups at once peaked at 8.7GB on 7 columns of 100M rows.
    frame = scan_columns(parts, INDEX)
    found = [frame.slice(start, length).collect() for start, length in _spans(index)]
    if not found:
        return frame.head(0).collect()
    return pl.concat(found).filter(pl.col(INDEX).is_in(index))


def _source_rows(
    source: SourceFiles, columns: list[str], index: list[int]
) -> pl.DataFrame:
    """Return the rows `index` of columns read from the source files, with the row index.

    Only the files holding the rows are scanned, each once: a scan of all the
    files would parse every footer. Values are cast to the input's types,
    and a file lacking a column gives nulls.
    """
    dtypes = {c: source.dtypes[c] for c in columns}
    target: dict[str, pl.DataType] = {}
    starts = list(itertools.accumulate(source.rows, initial=0))
    by_file: dict[int, list[int]] = {}
    for row in index:
        by_file.setdefault(bisect.bisect_right(starts, row) - 1, []).append(row)
    found = []
    for i, rows in by_file.items():
        scan = pl.scan_parquet(
            source.paths[i], row_index_name=INDEX, row_index_offset=starts[i]
        )
        present = scan.collect_schema()
        if not target and any(
            c not in present or str(present[c]) != d for c, d in dtypes.items()
        ):
            target = input_dtypes(source.schema, dtypes)
        values = [
            column_expr(c, d, present, target)
            if c in present
            else pl.lit(None, dtype=target[c]).alias(c)
            for c, d in dtypes.items()
        ]
        frame = scan.select(INDEX, *values)
        found += [
            frame.slice(start - starts[i], length).collect()
            for start, length in _spans(rows)
        ]
    if found:
        return pl.concat(found).filter(pl.col(INDEX).is_in(index))
    target = target or input_dtypes(source.schema, dtypes)
    return pl.DataFrame(schema={INDEX: pl.UInt32, **target})


def run_table(task: TableTask, out: Path, emit: Emit) -> None:
    """Write a page of the selected rows: their indices and the values of some columns.

    Parameters
    ----------
    task : TableTask
        The selection, the page and where to read its columns from.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    spec = task.spec
    emit({"type": "progress", "stage": "rows"})
    index = (
        scan_columns({c: spec.files[c] for c in selection_columns(spec)}, INDEX)
        .filter(*selection_filter(spec))
        .select(INDEX)
        .slice(task.offset, task.limit)
        .collect(engine="streaming")[INDEX]
        .to_list()
    )
    emit({"type": "progress", "stage": "values"})
    others = [c for c in task.columns if c not in task.parts]
    frames = []
    if task.parts:
        frames.append(_cached_rows(task.parts, index).drop(INDEX))
    if others:
        frames.append(_source_rows(task.source, others, index).drop(INDEX))
    values = pl.concat(frames, how="horizontal") if frames else pl.DataFrame()
    columns = [
        {
            "name": name,
            "dtype": str(values.schema[name]),
            "values": [_json_value(v) for v in values[name].to_list()],
        }
        for name in task.columns
    ]
    write_manifest(
        out,
        {
            "kind": "table",
            "offset": task.offset,
            "index": [int(i) for i in index],
            "columns": columns,
        },
    )
