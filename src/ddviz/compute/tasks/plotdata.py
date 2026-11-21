"""Task that writes the rows of a drawn plot as a file to save.

The rows are those the plot draws (`drawn_rows`), every row the local
filter keeps, or the rows a box selects, as the selection table lists them
(`ddviz.compute.selection.selection_filter`); the columns are those the
task lists, with the row index first. The rows are found from the column
cache, their indices streamed to a file (`sink_parquet`, the streaming
engine the selection table collects its pages with), then read a chunk after
another, so that only a chunk's values or two are held at once: a chunk
ends where its values reach its budget, measured before they are read
(`_cut`). A CSV cuts and appends each chunk and reports it written; a
chunk with nested or binary values, which a CSV cannot hold, is written in
`JSON_PIECES` pieces of its rows, each turned into texts only while it is
written (`_csv_value`). A Parquet file cuts every chunk first, keeping their rows alone, then streams
them to a sink (`ddviz.compute.chunksink`), which writes one while the next
is read, so that its chunks take half the budget; its row groups are kept
within the rows of the fewest of a chunk (`_row_group_rows`), and it
reports each chunk the sink receives (`run_plot_data`).
"""

from __future__ import annotations

import bisect
import itertools
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.aggregate import INDEX
from ddviz.compute.axisposition import on_axis
from ddviz.compute.chunksink import PARQUET_ROW_GROUP_ROWS, sink_chunks, write_chunks
from ddviz.compute.convert import input_dtypes
from ddviz.compute.joinread import joined_rows
from ddviz.compute.missing import drawn_conditions
from ddviz.compute.progress import Emit
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.compute.scan import scan_columns
from ddviz.compute.selection import selection_columns, selection_filter
from ddviz.compute.sourceread import file_values
from ddviz.shared.manifest import PlotManifest, write_manifest
from ddviz.shared.scatter import ONE_BAND, ScatterSpec
from ddviz.shared.tasks import PlotDataTask, SourceFiles

# Name of the row index column of the file, unless a column has it
# (`index_name`).
INDEX_NAME = "index"
# Bytes of values a chunk of a CSV holds at most (`_cut`), and its rows at
# most; a chunk of a Parquet file holds half of each.
CHUNK_BYTES = 512 * 2**20
MAX_CHUNK_ROWS = 10_000_000
# Bytes counted for each value besides those of texts, binaries and nested
# values (`_length`): a number, or the offset of a text or a list.
VALUE_BYTES = 8
# Pieces of its rows a chunk of a CSV with nested or binary values is
# written in (`_csv_value`): their texts, as JSON, take about 3 times the
# bytes of the values, so a chunk turned into texts at once would hold them
# all; 6 million rows of lists of 10 floats (526 MiB) peaked 1.6 GiB above
# the chunk at once, 0.24 GiB in 16 pieces.
JSON_PIECES = 16


def index_name(columns: list[str]) -> str:
    """Return the name of the row index column: ``index``, or ``index_2``, ... when a column has it."""
    name, n = INDEX_NAME, 1
    while name in columns:
        n += 1
        name = f"{INDEX_NAME}_{n}"
    return name


def _length(value: pl.Expr, dtype: pl.DataType) -> pl.Expr | None:
    """Return the bytes of each value of a column besides `VALUE_BYTES`, or None for a type of fixed size.

    A text or binary value takes its bytes. A nested value counts its items
    as values themselves, down to their texts: a list (or an array) takes
    `VALUE_BYTES` and the bytes besides of each item, a struct those of
    each field.
    """
    if dtype == pl.String:
        size = value.str.len_bytes()
    elif dtype == pl.Binary:
        size = value.bin.size()
    elif isinstance(dtype, pl.Array):
        return _length(value.arr.to_list(), pl.List(dtype.inner))
    elif isinstance(dtype, pl.List):
        size = value.list.len().cast(pl.UInt64) * VALUE_BYTES
        inner = _length(pl.element(), dtype.inner)
        if inner is not None:
            size = size + value.list.eval(inner).list.sum()
    elif isinstance(dtype, pl.Struct):
        fields = [
            _length(value.struct.field(f.name), f.dtype) for f in dtype.fields
        ]
        parts = [f for f in fields if f is not None]
        extra = VALUE_BYTES * (len(dtype.fields) - 1)
        if not parts and extra <= 0:
            return None
        size = pl.sum_horizontal(pl.lit(extra, dtype=pl.UInt64), *parts)
    else:
        return None
    return size.cast(pl.UInt64).fill_null(0)


def _has_binary(dtype: pl.DataType) -> bool:
    """Return whether a type is binary, or a list, an array or a struct with binary values inside."""
    if dtype == pl.Binary:
        return True
    if isinstance(dtype, (pl.List, pl.Array)):
        return _has_binary(dtype.inner)
    if isinstance(dtype, pl.Struct):
        return any(_has_binary(f.dtype) for f in dtype.fields)
    return False


def _binary_as_hex(value: pl.Expr, dtype: pl.DataType) -> pl.Expr:
    """Return the values with their binaries, outside or inside nested values, as lowercase hexadecimal texts.

    An array becomes a list; a part without binaries is left as it is, and a
    null struct stays null.
    """
    if not _has_binary(dtype):
        return value
    if dtype == pl.Binary:
        return value.bin.encode("hex")
    if isinstance(dtype, pl.Array):
        return _binary_as_hex(value.arr.to_list(), pl.List(dtype.inner))
    if isinstance(dtype, pl.List):
        return value.list.eval(_binary_as_hex(pl.element(), dtype.inner))
    fields = [
        _binary_as_hex(value.struct.field(f.name), f.dtype).alias(f.name)
        for f in dtype.fields
    ]
    return pl.when(value.is_not_null()).then(pl.struct(fields))


def _csv_value(name: str, dtype: pl.DataType) -> pl.Expr | None:
    """Return the texts a CSV holds for the values of a nested or binary column, or None for a column of another type.

    A binary value is its lowercase hexadecimal text (`_binary_as_hex`); a
    list, an array or a struct is its JSON, as polars encodes a struct,
    with its binaries as those texts (polars cannot encode a binary inside).
    A null value stays null: an empty cell.
    """
    if not (dtype == pl.Binary or isinstance(dtype, (pl.List, pl.Array, pl.Struct))):
        return None
    value = _binary_as_hex(pl.col(name), dtype)
    if isinstance(dtype, pl.Struct):
        value = value.struct.json_encode()
    elif dtype != pl.Binary:
        # A list in a struct of a field, the struct's `{"v":` and `}` cut off.
        value = pl.struct(value.alias("v")).struct.json_encode().str.slice(5).str.head(-1)
    return pl.when(pl.col(name).is_not_null()).then(value).alias(name)


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
                if (size := _length(expr, dtypes[c])) is not None
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
        schema = {c: pl.UInt64 for c, d in schema.items() if _length(pl.col(c), d) is not None}
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
        joined, columns, index, spans, read_right, _length if measure else None
    )


def _cut(
    index: pl.Series,
    bytes_of: Callable[[pl.Series], pl.Series | None],
    fixed: int,
    budget: int,
) -> tuple[int, np.ndarray | None]:
    """Return how many rows of `index`, from the first, a chunk takes: as many as `budget` bytes hold, at least one.

    `fixed` is the bytes of every row; `bytes_of` returns the bytes of the
    values of variable size of each row, or None when there are none. The
    bytes of each row taken come too, or None when every row has `fixed`.
    """
    sizes = bytes_of(index)
    if sizes is None:
        return max(1, min(len(index), budget // fixed)), None
    rows = (sizes + fixed).cast(pl.Int64)
    taken = max(1, min(len(index), (rows.cum_sum() <= budget).sum()))
    return taken, rows[:taken].to_numpy()


def _across(before: np.ndarray, after: np.ndarray, rows: int, budget: int) -> int:
    """Return the most rows, at most `rows`, that every run of as many rows from the end of a chunk into the next holds within `budget` bytes.

    `before` and `after` are the bytes of each row of the two chunks, from
    the end of the one (at least `rows` rows) and from the start of the
    other. The rows found are at least 1, and within 1/1024 of the most.
    """
    tail = before[len(before) - (rows - 1) :] if rows > 1 else before[:0]
    near = np.concatenate([tail, after[: rows - 1]])
    sums = np.concatenate([[0], np.cumsum(near)])
    t = len(tail)

    def fits(m: int) -> bool:
        """Return whether every run of `m` rows across the end of the chunk holds within the budget."""
        # Runs ending after the first row of the next chunk and starting
        # before it: sums[e] - sums[e - m] for t < e < t + m.
        last = min(t + m - 1, len(near))
        if last <= t:
            return True
        return int((sums[t + 1 : last + 1] - sums[t + 1 - m : last + 1 - m]).max()) <= budget

    if fits(rows):
        return rows
    lo, hi = 1, rows
    while hi - lo > max(1, hi >> 10):
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def _row_group_rows(sizes: list[int], most: int) -> int | None:
    """Return the rows of a row group of a Parquet file of chunks of `sizes` rows, or None for a row group for each chunk.

    Every chunk but the last holds at least the fewest rows of them (those
    of the only chunk when there is one; 1 when it has none), so that many
    rows of a chunk are within its budget, as are those of the last chunk.
    `most` keeps the rows of a row group across two chunks within the
    budget too (`_across`), and within `PARQUET_ROW_GROUP_ROWS`. When row
    groups of these rows would be more than twice as many as the chunks or
    as row groups of `PARQUET_ROW_GROUP_ROWS` rows (rows far larger than
    the others make a chunk of few rows), None.
    """
    total = sum(sizes)
    rows = min(most, max(1, min(sizes[:-1] or sizes)))
    least = max(len(sizes), -(-total // PARQUET_ROW_GROUP_ROWS))
    return rows if -(-total // rows) <= 2 * least else None


def run_plot_data(task: PlotDataTask, out: Path, emit: Emit) -> None:  # noqa: C901, PLR0912, PLR0915
    """Write the rows of a plot task's result, or of a selection, as a file.

    The selected rows are those of the task's ``selection``, the spec the
    server had when asked: the selection layer's directory is not read, so
    a layer replaced meanwhile changes nothing.

    Progress messages carry the stage ``"export"`` and the task's
    ``export``; once the rows are counted, also ``done`` and ``total``,
    the rows written (for a Parquet file, those the sink received) and to
    write.

    A CSV holds a nested value (a list, an array or a struct) as its JSON,
    and a binary value, outside or inside, as its lowercase hexadecimal
    text; a null value is an empty cell, and a NaN or an infinity inside a
    nested value is null in its JSON. A Parquet file holds the values with
    their types.

    Parameters
    ----------
    task : PlotDataTask
        The result or the selection, the rows and columns, and where to
        read them from.
    out : pathlib.Path
        Directory to write the file into; the manifest names it.
    emit : callable
        Receives progress messages.
    """
    if task.rows == "selected":
        spec = task.selection
    else:
        spec = PlotManifest.read(Path(task.result)).spec
    progress = {"type": "progress", "stage": "export", "export": task.export}
    emit(progress)
    if task.rows == "selected":
        # As the selection table reads its pages (`run_table`).
        conditions = selection_filter(spec, INDEX)
        read = selection_columns(spec)
    elif task.rows == "drawn":
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
    joined_files = task.source.joined
    added = joined_files.columns if joined_files is not None else {}
    others = [c for c in task.columns if c not in task.parts and c not in added]
    joined = [c for c in task.columns if c not in task.parts and c in added]
    generated = task.source.generated
    dtypes = {c: d for c, d in task.source.dtypes.items() if c not in generated}
    target = input_dtypes(task.source.schema, dtypes) if dtypes else {}
    right_target: dict[str, pl.DataType] = {}
    if joined:
        right = joined_files.source
        right_dtypes = {c: d for c, d in right.dtypes.items() if c not in right.generated}
        right_target = input_dtypes(right.schema, right_dtypes) if right_dtypes else {}
    name = index_name(task.columns)
    # Every value counts VALUE_BYTES, the row index too; texts, binaries and
    # nested values count their bytes besides (`_length`).
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
        if joined:
            frames.append(
                _joined(task.source, joined, right_target, index, lo, hi, True).drop(INDEX)
            )
        lengths = pl.concat(frames, how="horizontal")
        if lengths.width == 0:
            fixed_only.append(True)
            return None
        return lengths.sum_horizontal()

    def cuts(budget: int, max_rows: int) -> Iterator[tuple[pl.Series, np.ndarray | None]]:
        """Yield the row indices of each chunk of the file, in order: at least one chunk, of no row when there are none.

        The bytes of each row of the chunk come too, or None when every
        row has `fixed` (`_cut`).
        """
        start = 0
        while True:
            chunk = indices.slice(start, max_rows).collect()[INDEX]
            held = None
            if len(chunk):
                rows, held = _cut(chunk, bytes_of, fixed, budget)
                chunk = chunk[:rows]
            start += len(chunk)
            yield chunk, held
            del chunk, held
            if start >= total:
                return

    def read(chunks: Iterable[pl.Series]) -> Iterator[pl.DataFrame]:
        """Yield the values of the rows of each chunk, the row index first."""
        for chunk in chunks:
            lo, hi = (chunk.min(), chunk.max()) if len(chunk) else (0, -1)
            frames = [chunk.to_frame()]
            if cached:
                frames.append(_cached(cached, chunk, lo, hi).drop(INDEX))
            if others:
                frames.append(
                    _source(task.source, others, target, chunk, lo, hi).drop(INDEX)
                )
            if joined:
                frames.append(
                    _joined(task.source, joined, right_target, chunk, lo, hi).drop(INDEX)
                )
            # Columns picked by name keep their chunks; a `select` of
            # expressions would copy the chunk's values into one chunk a
            # column, as its columns are chunked apart.
            table = pl.concat(frames, how="horizontal").rename({INDEX: name})[
                [name, *task.columns]
            ]
            # Only the chunk handed on is held while the next is made.
            del chunk, frames
            yield table
            del table

    file = f"data.{task.file_format}"
    path = out / file
    if task.file_format == "csv":
        done = 0
        # The texts of the nested and binary columns, found from the first
        # chunk: every chunk has its types.
        texts: list[pl.Expr] | None = None
        with path.open("wb") as csv:
            chunks = (chunk for chunk, _ in cuts(CHUNK_BYTES, MAX_CHUNK_ROWS))
            for i, table in enumerate(read(chunks)):
                if texts is None:
                    texts = [
                        e for c, d in table.schema.items() if (e := _csv_value(c, d)) is not None
                    ]
                if texts and table.height:
                    # Only a piece's texts are held at once.
                    pieces = table.iter_slices(-(-table.height // JSON_PIECES))
                else:
                    pieces = iter([table])
                for j, piece in enumerate(pieces):
                    first = i == 0 and j == 0
                    piece.with_columns(texts).write_csv(
                        csv, include_bom=first, include_header=first
                    )
                    del piece
                done += table.height
                emit({**progress, "done": done, "total": total})
    else:
        # The sink makes the next chunk while it writes one: half the bytes
        # and rows keep the two within those of a CSV chunk. Every chunk is
        # cut first, its rows alone kept, so that the rows of a row group
        # are known before it is written (`_row_group_rows`); the bytes of
        # the rows of a chunk are kept only until the next is cut, to keep
        # a row group across the two within the budget (`_across`).
        sizes: list[int] = []
        most = PARQUET_ROW_GROUP_ROWS
        before = None
        for chunk, held in cuts(CHUNK_BYTES // 2, MAX_CHUNK_ROWS // 2):
            if sizes:
                # The chunk before is not the last one.
                most = min(most, sizes[-1])
                if before is not None and held is not None:
                    most = _across(before, held, most, CHUNK_BYTES // 2)
            sizes.append(len(chunk))
            before = None if held is None else held[-PARQUET_ROW_GROUP_ROWS:]
            del chunk, held
        del before
        starts = itertools.accumulate(sizes[:-1], initial=0)
        chunks = read(
            indices.slice(start, rows).collect()[INDEX]
            for start, rows in zip(starts, sizes, strict=True)
        )

        def received(done: int) -> None:
            """Report the rows the file received so far."""
            emit({**progress, "done": done, "total": total})

        group = _row_group_rows(sizes, most)
        if group is None:
            write_chunks(chunks, path, received)
        else:
            sink_chunks(chunks, path, group, received)
        emit({**progress, "done": total, "total": total})
    (out / "rows.parquet").unlink(missing_ok=True)
    write_manifest(out, {"kind": "plot_data", "file": file})
