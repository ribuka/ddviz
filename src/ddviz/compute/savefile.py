"""Write a file of rows to save, a chunk after another (`write_rows`): the rows of a plot (`ddviz.compute.tasks.plotdata`) or of a join (`ddviz.compute.joinrows`).

The rows are read a chunk after another, so that only a chunk's values or
two are held at once: a chunk ends where its values reach its budget,
measured before they are read (`_cut`). A CSV cuts and appends each chunk
and reports it written; a chunk with nested or binary values, which a CSV
cannot hold, is written in `JSON_PIECES` pieces of its rows, each turned
into texts only while it is written (`_csv_value`). A Parquet file cuts
every chunk first, keeping their rows alone, then streams them to a sink
(`ddviz.compute.chunksink`), which writes one while the next is read, so
that its chunks take half the budget; its row groups are kept within the
rows of the fewest of a chunk (`_row_group_rows`), and it reports each
chunk the sink receives.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.chunksink import PARQUET_ROW_GROUP_ROWS, sink_chunks, write_chunks

# Bytes of values a chunk of a CSV holds at most (`_cut`), and its rows at
# most; a chunk of a Parquet file holds half of each.
CHUNK_BYTES = 512 * 2**20
MAX_CHUNK_ROWS = 10_000_000
# Bytes counted for each value besides those of texts, binaries and nested
# values (`value_bytes`): a number, or the offset of a text or a list.
VALUE_BYTES = 8
# Pieces of its rows a chunk of a CSV with nested or binary values is
# written in (`_csv_value`): their texts, as JSON, take about 3 times the
# bytes of the values, so a chunk turned into texts at once would hold them
# all; 6 million rows of lists of 10 floats (526 MiB) peaked 1.6 GiB above
# the chunk at once, 0.24 GiB in 16 pieces.
JSON_PIECES = 16

# Reads a chunk of the rows (`write_rows`): given the chunk of the rows'
# frame and whether to measure, the table to write, or with `measure` the
# bytes of its values of variable size, one column for each such column
# (none when there are none).
ReadChunk = Callable[[pl.DataFrame, bool], pl.DataFrame]


def value_bytes(value: pl.Expr, dtype: pl.DataType) -> pl.Expr | None:
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
        return value_bytes(value.arr.to_list(), pl.List(dtype.inner))
    elif isinstance(dtype, pl.List):
        size = value.list.len().cast(pl.UInt64) * VALUE_BYTES
        inner = value_bytes(pl.element(), dtype.inner)
        if inner is not None:
            size = size + value.list.eval(inner).list.sum()
    elif isinstance(dtype, pl.Struct):
        fields = [
            value_bytes(value.struct.field(f.name), f.dtype) for f in dtype.fields
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


def _cut(
    chunk: pl.DataFrame,
    bytes_of: Callable[[pl.DataFrame], pl.Series | None],
    fixed: int,
    budget: int,
) -> tuple[int, np.ndarray | None]:
    """Return how many rows of `chunk`, from the first, a chunk takes: as many as `budget` bytes hold, at least one.

    `fixed` is the bytes of every row; `bytes_of` returns the bytes of the
    values of variable size of each row, or None when there are none. The
    bytes of each row taken come too, or None when every row has `fixed`.
    """
    sizes = bytes_of(chunk)
    if sizes is None:
        return max(1, min(len(chunk), budget // fixed)), None
    rows = (sizes + fixed).cast(pl.Int64)
    taken = max(1, min(len(chunk), (rows.cum_sum() <= budget).sum()))
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


class _Chunks:
    """The chunks of the rows of a file, cut within a budget of bytes (`_cut`), and their tables."""

    def __init__(self, rows: pl.LazyFrame, total: int, fixed: int, read: ReadChunk) -> None:
        self.rows = rows
        self.total = total
        self.fixed = fixed
        self.read = read
        # Whether no column has values of variable size, once a chunk found it.
        self.fixed_only = False

    def bytes_of(self, chunk: pl.DataFrame) -> pl.Series | None:
        """Return the bytes of the values of variable size of the rows of `chunk`, or None without such values."""
        if self.fixed_only:
            return None
        lengths = self.read(chunk, True)
        if lengths.width == 0:
            self.fixed_only = True
            return None
        return lengths.sum_horizontal()

    def cuts(self, budget: int, max_rows: int) -> Iterator[tuple[pl.DataFrame, np.ndarray | None]]:
        """Yield the rows of each chunk of the file, in order: at least one chunk, of no row when there are none.

        The bytes of each row of the chunk come too, or None when every
        row has `fixed` (`_cut`).
        """
        start = 0
        while True:
            chunk = self.rows.slice(start, max_rows).collect()
            held = None
            if len(chunk):
                taken, held = _cut(chunk, self.bytes_of, self.fixed, budget)
                chunk = chunk[:taken]
            start += len(chunk)
            yield chunk, held
            del chunk, held
            if start >= self.total:
                return

    def tables(self, chunks: Iterable[pl.DataFrame]) -> Iterator[pl.DataFrame]:
        """Yield the table of the rows of each chunk."""
        for chunk in chunks:
            table = self.read(chunk, False)
            # Only the chunk handed on is held while the next is made.
            del chunk
            yield table
            del table


def _write_csv(chunks: _Chunks, path: Path, received: Callable[[int], None]) -> None:
    """Write the chunks as a CSV, reporting the rows written after each."""
    done = 0
    # The texts of the nested and binary columns, found from the first
    # chunk: every chunk has its types.
    texts: list[pl.Expr] | None = None
    with path.open("wb") as csv:
        cut = (chunk for chunk, _ in chunks.cuts(CHUNK_BYTES, MAX_CHUNK_ROWS))
        for i, table in enumerate(chunks.tables(cut)):
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
            received(done)


def _write_parquet(chunks: _Chunks, path: Path, received: Callable[[int], None]) -> None:
    """Write the chunks as a Parquet file, reporting the rows the sink received.

    The sink makes the next chunk while it writes one: half the bytes and
    rows keep the two within those of a CSV chunk. Every chunk is cut
    first, its rows alone kept, so that the rows of a row group are known
    before it is written (`_row_group_rows`); the bytes of the rows of a
    chunk are kept only until the next is cut, to keep a row group across
    the two within the budget (`_across`).
    """
    sizes: list[int] = []
    most = PARQUET_ROW_GROUP_ROWS
    before = None
    for chunk, held in chunks.cuts(CHUNK_BYTES // 2, MAX_CHUNK_ROWS // 2):
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
    tables = chunks.tables(
        chunks.rows.slice(start, rows).collect()
        for start, rows in zip(starts, sizes, strict=True)
    )
    group = _row_group_rows(sizes, most)
    if group is None:
        write_chunks(tables, path, received)
    else:
        sink_chunks(tables, path, group, received)
    received(chunks.total)


def write_rows(
    rows: pl.LazyFrame,
    total: int,
    fixed: int,
    read: ReadChunk,
    path: Path,
    file_format: str,
    received: Callable[[int], None],
) -> None:
    """Write the rows of a file to save, a chunk after another.

    A CSV holds a nested value (a list, an array or a struct) as its JSON,
    and a binary value, outside or inside, as its lowercase hexadecimal
    text; a null value is an empty cell, and a NaN or an infinity inside a
    nested value is null in its JSON. A Parquet file holds the values with
    their types.

    Parameters
    ----------
    rows : polars.LazyFrame
        What tells the rows of the file apart, in their order: a chunk of
        it is what `read` reads.
    total : int
        The rows of `rows`.
    fixed : int
        The bytes every row takes besides its values of variable size
        (`VALUE_BYTES` a value).
    read : callable
        Reads a chunk of the rows (`ReadChunk`).
    path : pathlib.Path
        The file to write.
    file_format : str
        ``"csv"`` or ``"parquet"``.
    received : callable
        Called with the rows written so far (for a Parquet file, those the
        sink received), and with `total` at the end of a Parquet file.
    """
    chunks = _Chunks(rows, total, fixed, read)
    if file_format == "csv":
        _write_csv(chunks, path, received)
    else:
        _write_parquet(chunks, path, received)
