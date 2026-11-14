"""Task that writes the rows of a drawn plot as a file to save.

The rows are those the plot draws (`drawn_rows`), or every row the local
filter keeps; the columns are those the task lists, with the row index
first. The rows are found from the column cache, then written a chunk after
another, so that no more than a chunk's values are held at once: a chunk
ends where its values reach `CHUNK_BYTES`, measured before they are read
(`_cut`), and each chunk reports its progress (`run_plot_data`).
"""

from __future__ import annotations

import bisect
import itertools
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from ddviz.compute.aggregate import INDEX
from ddviz.compute.axisposition import on_axis
from ddviz.compute.convert import column_expr, input_dtypes
from ddviz.compute.missing import drawn_conditions
from ddviz.compute.progress import Emit
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.compute.scan import scan_columns
from ddviz.shared.generated import generated_value
from ddviz.shared.manifest import PlotManifest, write_manifest
from ddviz.shared.scatter import ONE_BAND, ScatterSpec
from ddviz.shared.tasks import PlotDataTask, SourceFiles

# Name of the row index column of the file, unless a column has it
# (`index_name`).
INDEX_NAME = "index"
# Bytes of values a chunk holds at most (`_cut`), and its rows at most.
CHUNK_BYTES = 512 * 2**20
MAX_CHUNK_ROWS = 10_000_000
# Bytes counted for each value besides those of a text, binary or list
# (`_length`): a number, or the offset of a text.
VALUE_BYTES = 8


def index_name(columns: list[str]) -> str:
    """Return the name of the row index column: ``index``, or ``index_2``, ... when a column has it."""
    name, n = INDEX_NAME, 1
    while name in columns:
        n += 1
        name = f"{INDEX_NAME}_{n}"
    return name


def _length(value: pl.Expr, dtype: pl.DataType) -> pl.Expr | None:
    """Return the bytes of each value of a column besides `VALUE_BYTES`, or None for a type of fixed size.

    A text or binary value takes its bytes, a list 8 per item.
    """
    if dtype == pl.String:
        size = value.str.len_bytes()
    elif dtype == pl.Binary:
        size = value.bin.size()
    elif isinstance(dtype, pl.List):
        size = value.list.len() * 8
    else:
        return None
    return size.cast(pl.UInt64).fill_null(0)


def _on_axis(spec: ScatterSpec, column: str, log: list[str]) -> pl.Expr:
    """Return whether a row has a place along an axis of a column, as the aggregation draws it."""
    if column == ONE_BAND:
        return pl.lit(True)
    if column in spec.categorical:
        return pl.col(column).is_not_null()
    return on_axis(pl.col(column).cast(pl.Float64), column in log)


def drawn_rows(spec: ScatterSpec) -> list[pl.Expr]:
    """Return the conditions of the rows a plot draws.

    A row is drawn when the local filter keeps it, its color, symbol, row
    and col are drawn (`ddviz.compute.missing.drawn_conditions`), and some
    panel places it: its x and y have a place on that panel's axes (finite,
    positive on a log axis, not null on a categorical axis). A row placed on
    several panels is one row.

    Parameters
    ----------
    spec : ScatterSpec
        The spec of the drawn result.

    Returns
    -------
    list of polars.Expr
        Conditions to filter on.
    """
    placed = [
        _on_axis(spec, x, spec.log_x) & _on_axis(spec, y, spec.log_y)
        for x in spec.x
        for y in spec.y
    ]
    return [
        *drawn_conditions(spec),
        *filter_conditions(spec.filters),
        pl.any_horizontal(placed),
    ]


def _cached(
    parts: dict[str, list[str]],
    index: pl.Series,
    lo: int,
    hi: int,
    measure: bool = False,
) -> pl.DataFrame:
    """Return the rows `index` (between `lo` and `hi`) of columns in the column cache, with their values.

    With `measure`, the bytes of the values of variable size (`_length`)
    instead, one column for each such column; the values are not held.
    """
    frame = scan_columns(parts, INDEX, numbers=False)
    if measure:
        schema = frame.collect_schema()
        lengths = [
            size.alias(c)
            for c in parts
            if (size := _length(pl.col(c), schema[c])) is not None
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

    Only the files holding rows between `lo` and `hi` are scanned. Values
    are cast to the input's types, a file lacking a column gives nulls, and
    an added column (`ddviz.shared.generated`) gives the file's value, as
    the selection table reads them (`ddviz.compute.tasks.table`). With
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
        present = scan.collect_schema()
        values = []
        for c in columns:
            if c in source.generated:
                value = generated_value(source.generated[c], source.paths[i])
                expr, dtype = pl.lit(value, dtype=pl.String), pl.String
            else:
                expr, dtype = column_expr(c, source.dtypes[c], present, target), target[c]
                if expr is None:
                    expr = pl.lit(None, dtype=dtype)
            if measure:
                expr = _length(expr, dtype)
            if expr is not None:
                values.append(expr.alias(c))
        begin = max(lo, start)
        found.append(
            scan.select(INDEX, *values)
            .slice(begin - start, min(hi + 1, end) - begin)
            .filter(pl.col(INDEX).is_in(index.implode()))
            .collect(engine="streaming" if measure else "auto")
        )
    if found:
        return pl.concat(found)
    schema = {c: target.get(c, pl.String) for c in columns}
    if measure:
        schema = {c: pl.UInt64 for c, d in schema.items() if _length(pl.col(c), d) is not None}
    return pl.DataFrame(schema={INDEX: index.dtype, **schema})


def _cut(
    index: pl.Series, bytes_of: Callable[[pl.Series], pl.Series | None], fixed: int
) -> int:
    """Return how many rows of `index`, from the first, a chunk takes: as many as `CHUNK_BYTES` holds, at least one.

    `fixed` is the bytes of every row; `bytes_of` returns the bytes of the
    values of variable size of each row, or None when there are none.
    """
    sizes = bytes_of(index)
    if sizes is None:
        return max(1, min(len(index), CHUNK_BYTES // fixed))
    held = ((sizes + fixed).cum_sum() <= CHUNK_BYTES).sum()
    return max(1, min(len(index), held))


class _Writer:
    """Writes the chunks of a CSV or Parquet file one after another."""

    def __init__(self, path: Path, file_format: str) -> None:
        self._path = path
        self._format = file_format
        self._csv = None
        self._parquet: pq.ParquetWriter | None = None

    def write(self, table: pl.DataFrame) -> None:
        """Append a chunk: the first one starts the file with its columns."""
        if self._format == "csv":
            first = self._csv is None
            if first:
                self._csv = self._path.open("wb")
            table.write_csv(self._csv, include_bom=first, include_header=first)
            return
        arrow = table.to_arrow()
        if self._parquet is None:
            self._parquet = pq.ParquetWriter(self._path, arrow.schema)
            self._schema = arrow.schema
        self._parquet.write_table(arrow.cast(self._schema))

    def close(self) -> None:
        """Finish the file."""
        if self._csv is not None:
            self._csv.close()
        if self._parquet is not None:
            self._parquet.close()


def run_plot_data(task: PlotDataTask, out: Path, emit: Emit) -> None:
    """Write the rows of a plot task's result as a file.

    Progress messages carry the stage ``"export"`` and the task's
    ``export``; once the rows are counted, also ``done`` and ``total``,
    the rows written and to write.

    Parameters
    ----------
    task : PlotDataTask
        The result, the rows and columns, and where to read them from.
    out : pathlib.Path
        Directory to write the file into; the manifest names it.
    emit : callable
        Receives progress messages.
    """
    spec = PlotManifest.read(Path(task.result)).spec
    progress = {"type": "progress", "stage": "export", "export": task.export}
    emit(progress)
    if task.rows == "drawn":
        conditions = drawn_rows(spec)
        roles = [spec.color, spec.symbol, spec.row, spec.col]
        read = [
            c
            for c in dict.fromkeys([*spec.x, *spec.y, *roles, *filter_columns(spec.filters)])
            if c is not None and c != ONE_BAND
        ]
    else:
        conditions = filter_conditions(spec.filters)
        read = filter_columns(spec.filters)
    if conditions:
        rows = out / "rows.parquet"
        scan_columns({c: spec.files[c] for c in read}, INDEX).filter(
            *conditions
        ).select(INDEX).sink_parquet(rows)
        indices = pl.scan_parquet(rows)
    else:
        # Every row: counted from the footers of any column of the plot.
        column = next(c for c in spec.files if c != ONE_BAND)
        n = scan_columns({column: spec.files[column]}).select(pl.len()).collect()
        indices = pl.LazyFrame().select(
            pl.int_range(n.item(), dtype=pl.get_index_type()).alias(INDEX)
        )
    total = indices.select(pl.len()).collect().item()
    emit({**progress, "done": 0, "total": total})

    cached = {c: task.parts[c] for c in task.columns if c in task.parts}
    others = [c for c in task.columns if c not in task.parts]
    generated = task.source.generated
    dtypes = {c: d for c, d in task.source.dtypes.items() if c not in generated}
    target = input_dtypes(task.source.schema, dtypes) if dtypes else {}
    name = index_name(task.columns)
    # Every value counts VALUE_BYTES, the row index too; texts, binaries and
    # lists count their bytes besides (`_length`).
    fixed = VALUE_BYTES * (len(task.columns) + 1)

    # Whether no column has values of variable size, once a chunk found it.
    fixed_only: list[bool] = []

    def bytes_of(index: pl.Series) -> pl.Series | None:
        """Return the bytes of the values of variable size of the rows `index`, or None without such values."""
        if fixed_only:
            return None
        lo, hi = index.min(), index.max()
        frames = []
        if cached:
            frames.append(_cached(cached, index, lo, hi, measure=True).drop(INDEX))
        if others:
            frames.append(
                _source(task.source, others, target, index, lo, hi, True).drop(INDEX)
            )
        lengths = pl.concat(frames, how="horizontal")
        if lengths.width == 0:
            fixed_only.append(True)
            return None
        return lengths.sum_horizontal()

    file = f"data.{task.file_format}"
    writer = _Writer(out / file, task.file_format)
    start = 0
    try:
        while True:
            chunk = indices.slice(start, MAX_CHUNK_ROWS).collect()[INDEX]
            if len(chunk):
                chunk = chunk[: _cut(chunk, bytes_of, fixed)]
            lo, hi = (chunk.min(), chunk.max()) if len(chunk) else (0, -1)
            frames = [chunk.to_frame()]
            if cached:
                frames.append(_cached(cached, chunk, lo, hi).drop(INDEX))
            if others:
                frames.append(
                    _source(task.source, others, target, chunk, lo, hi).drop(INDEX)
                )
            table = pl.concat(frames, how="horizontal")
            writer.write(table.select(pl.col(INDEX).alias(name), *task.columns))
            start += len(chunk)
            emit({**progress, "done": start, "total": total})
            if start >= total:
                break
    finally:
        writer.close()
    (out / "rows.parquet").unlink(missing_ok=True)
    write_manifest(out, {"kind": "plot_data", "file": file})
