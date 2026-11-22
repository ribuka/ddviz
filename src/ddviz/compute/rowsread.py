"""Read rows of the columns of an input by their row index, a chunk of a file to save at a time (`ColumnReader`).

A column is read from its parts in the column cache when the task has them
(`_cached`), from the source files otherwise (`_source`), and a column a
join added and not converted through the join's map (`_joined`,
`ddviz.compute.joinread`). Each reads only the rows between the first and
the last asked for. With ``measure``, the bytes of the values of variable
size are read instead (`ddviz.compute.savefile.value_bytes`), so that a
chunk is cut before its values are held.
"""

from __future__ import annotations

import bisect
import itertools

import polars as pl

from ddviz.compute.aggregate import INDEX
from ddviz.compute.convert import input_dtypes
from ddviz.compute.joinread import joined_rows
from ddviz.compute.savefile import value_bytes
from ddviz.compute.scan import scan_columns
from ddviz.compute.sourceread import file_values
from ddviz.shared.tasks import SourceFiles


def _cached(
    parts: dict[str, list[str]],
    index: pl.Series,
    lo: int,
    hi: int,
    measure: bool = False,
) -> pl.DataFrame:
    """Return the rows `index` (between `lo` and `hi`) of columns in the column cache, with their values.

    With `measure`, the bytes of the values of variable size (`value_bytes`)
    instead, one column for each such column; the values are not held.
    """
    frame = scan_columns(parts, INDEX, numbers=False)
    if measure:
        schema = frame.collect_schema()
        lengths = [
            size.alias(c)
            for c in parts
            if (size := value_bytes(pl.col(c), schema[c])) is not None
        ]
        frame = frame.select(INDEX, *lengths)
    return (
        frame.slice(lo, hi - lo + 1)
        .filter(pl.col(INDEX).is_in(index.implode()))
        .collect(engine="streaming" if measure else "auto")
    )


def _source(
    source: SourceFiles,
    columns: list[str],
    target: dict[str, pl.DataType],
    index: pl.Series,
    lo: int,
    hi: int,
    measure: bool = False,
) -> pl.DataFrame:
    """Return the rows `index` (between `lo` and `hi`) of columns read from the source files.

    Only the files holding rows between `lo` and `hi` are scanned, each
    file's values given by `ddviz.compute.sourceread.file_values`. With
    `measure`, the bytes of the values of variable size instead, as
    `_cached` gives them.
    """
    starts = list(itertools.accumulate(source.rows, initial=0))
    first = max(bisect.bisect_right(starts, lo) - 1, 0)
    found = []
    for i in range(first, len(source.paths)):
        start, end = starts[i], starts[i + 1]
        if start > hi:
            break
        if end <= lo:
            continue
        scan = pl.scan_parquet(
            source.paths[i], row_index_name=INDEX, row_index_offset=start
        )
        values = file_values(
            source, source.paths[i], columns, scan.collect_schema(), target
        )
        if measure:
            dtypes = {c: pl.String if c in source.generated else target[c] for c in values}
            values = {
                c: size.alias(c)
                for c, expr in values.items()
                if (size := value_bytes(expr, dtypes[c])) is not None
            }
        begin = max(lo, start)
        found.append(
            scan.select(INDEX, *values.values())
            .slice(begin - start, min(hi + 1, end) - begin)
            .filter(pl.col(INDEX).is_in(index.implode()))
            .collect(engine="streaming" if measure else "auto")
        )
    if found:
        return pl.concat(found)
    schema = {c: target.get(c, pl.String) for c in columns}
    if measure:
        schema = {c: pl.UInt64 for c, d in schema.items() if value_bytes(pl.col(c), d) is not None}
    return pl.DataFrame(schema={INDEX: index.dtype, **schema})


def _joined(
    source: SourceFiles,
    columns: list[str],
    target: dict[str, pl.DataType],
    index: pl.Series,
    lo: int,
    hi: int,
    measure: bool = False,
) -> pl.DataFrame:
    """Return the rows `index` (between `lo` and `hi`) of columns a join added, not converted (`ddviz.compute.joinread`).

    The joined table's rows are read as those of the input are (`_cached`,
    `_source`), with `target`, the joined table's types. With `measure`, the
    bytes of the values of variable size instead, as `_cached` gives them.
    """
    joined = source.joined

    def read_right(held: list[str], rows: pl.Series) -> pl.DataFrame:
        """Return the joined table's rows `rows` of the columns `held`."""
        first, last = (rows.min(), rows.max()) if len(rows) else (0, -1)
        cached = {c: joined.parts[c] for c in held if c in joined.parts}
        others = [c for c in held if c not in joined.parts]
        frames = []
        if cached:
            frames.append(_cached(cached, rows, first, last, measure))
        if others:
            found = _source(joined.source, others, target, rows, first, last, measure)
            frames.append(found.drop(INDEX) if frames else found)
        return pl.concat(frames, how="horizontal")

    spans = [(lo, hi - lo + 1)]
    return joined_rows(
        joined, columns, index, spans, read_right, value_bytes if measure else None
    )


def _target(source: SourceFiles) -> dict[str, pl.DataType]:
    """Return the types the columns of `source` not added (`ddviz.shared.generated`) are read as."""
    dtypes = {c: d for c, d in source.dtypes.items() if c not in source.generated}
    return input_dtypes(source.schema, dtypes) if dtypes else {}


class ColumnReader:
    """Reads rows of columns of an input by their row index, from the column cache, the source files, or through a join.

    Parameters
    ----------
    source : SourceFiles
        The source files, for the columns not in `parts`.
    parts : dict of str to list of str
        The parts of columns in the column cache.
    columns : list of str
        The columns to read.
    """

    def __init__(self, source: SourceFiles, parts: dict[str, list[str]], columns: list[str]) -> None:
        self.source = source
        self.cached = {c: parts[c] for c in columns if c in parts}
        added = source.joined.columns if source.joined is not None else {}
        self.others = [c for c in columns if c not in parts and c not in added]
        self.joined = [c for c in columns if c not in parts and c in added]
        self.target = _target(source) if self.others else {}
        self.right_target = _target(source.joined.source) if self.joined else {}

    def read(self, index: pl.Series, *, measure: bool) -> list[pl.DataFrame]:
        """Return the rows `index` (sorted) of the columns, or with `measure` the bytes of their values of variable size, as frames without the row index.

        Parameters
        ----------
        index : polars.Series
            The rows to read, in ascending order.
        measure : bool
            Whether to read the bytes of the values of variable size, one
            column for each such column, instead of the values.

        Returns
        -------
        list of polars.DataFrame
            The columns read from the cache, the source files and through
            the join, each frame in the order of `index`.
        """
        lo, hi = (index.min(), index.max()) if len(index) else (0, -1)
        frames = []
        if self.cached:
            frames.append(_cached(self.cached, index, lo, hi, measure=measure).drop(INDEX))
        if self.others:
            frames.append(
                _source(self.source, self.others, self.target, index, lo, hi, measure=measure).drop(INDEX)
            )
        if self.joined:
            frames.append(
                _joined(self.source, self.joined, self.right_target, index, lo, hi, measure=measure).drop(INDEX)
            )
        return frames
