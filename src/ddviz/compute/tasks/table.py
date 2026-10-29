"""Task that reads a page of the selected rows for the selection table."""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl

from ddviz.compute.aggregate import INDEX
from ddviz.compute.progress import Emit
from ddviz.compute.scan import scan_columns
from ddviz.compute.selection import selection_columns, selection_filter
from ddviz.shared.manifest import write_manifest
from ddviz.shared.scatter import ScatterSpec

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


def run_table(
    spec: ScatterSpec,
    offset: int,
    limit: int,
    files: dict[str, str],
    out: Path,
    emit: Emit,
) -> None:
    """Write a page of the selected rows: their indices and the values of some columns.

    Parameters
    ----------
    spec : ScatterSpec
        A spec with a selection; its files hold the selection's columns.
    offset, limit : int
        The page: the selected rows from `offset`, at most `limit`, in row
        order.
    files : dict of str to str
        Parquet file to read each column of the page from: a file of the
        column cache, or the source.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "rows"})
    index = (
        scan_columns({c: spec.files[c] for c in selection_columns(spec)}, INDEX)
        .filter(*selection_filter(spec))
        .select(INDEX)
        .slice(offset, limit)
        .collect(engine="streaming")[INDEX]
        .to_list()
    )
    emit({"type": "progress", "stage": "values"})
    # One lazy frame for every slice: a new scan parses the footer again
    # (about 0.5s for a file of 1M column chunks). Slices are read one after
    # another; reading 100 rows spread over 100 row groups at once peaked at
    # 8.7GB on 7 columns of 100M rows.
    frame = scan_columns(files, INDEX) if files else None
    parts = []
    if frame is not None:
        for start, length in _spans(index):
            parts.append(frame.slice(start, length).collect())
    if parts:
        values = pl.concat(parts).filter(pl.col(INDEX).is_in(index))
    elif frame is not None:
        # No row is selected: the columns are empty, with their types.
        values = frame.head(0).collect()
    else:
        values = pl.DataFrame({INDEX: index}, schema={INDEX: pl.UInt32})
    columns = [
        {
            "name": name,
            "dtype": str(values.schema[name]),
            "values": [_json_value(v) for v in values[name].to_list()],
        }
        for name in files
    ]
    write_manifest(
        out,
        {
            "kind": "table",
            "offset": offset,
            "index": [int(i) for i in index],
            "columns": columns,
        },
    )
