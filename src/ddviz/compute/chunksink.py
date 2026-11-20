"""Write data frames that come one after another as one Parquet file.

`sink_chunks` makes the frames the source of a polars IO plugin
(`register_io_source`), whose lazy frame is streamed to `sink_parquet`:
polars writes a frame while the next is made, and writes the columns in
parallel. The plugin API is unstable; `pyproject.toml` pins the polars
version it was checked with. polars holds the rows of a row group until it
has them all and cuts row groups by rows only, so the caller gives the
rows of a row group.

The plugin's source has no back pressure: polars asks for the next frame
however far its writing lags, and holds the frames it took and the pages
made of them until they are written, so while the disk wrote slowly the
memory grew by more than a frame for each frame taken ahead (Issue #322).
`sink_chunks` therefore waits to make the next frame until polars has
written the row groups of the frames before the last one handed on: the
frame being written and the one being made are the two in memory.
polars tells which files it wrote only at the end, so the sink is given
a file object of its own (`_Paced`), and
the bytes polars writes to it are read as they pass: the page headers
are skipped with their pages, and the metadata polars writes after the
pages of each column chunk counts a column chunk written; a row group is
written once all its column chunks (the leaf columns of the schema) are.
polars encodes a whole row group before it writes it, then writes it at
once through a buffer of 8 KiB (`io::BufWriter`), so the last bytes of a
row group come to the file only with the first ones of the next: those
of the frames before the last one handed on come with the row group the
last one fills. Nothing is judged by time, but two ends of the
wait, to never hang: a write that fails (polars still asks for every
frame before it raises the error) and `STALL_SECONDS` in which polars,
out of `write`, writes nothing. Frames of less than `PACED_BYTES` are not
waited for: their row groups may not fill the buffer, and they do not
weigh on the memory. Bytes that do not read as page headers or column
metadata end the waits. Cancelling kills the process, waiting or not.

`write_chunks` writes each frame as a row group of its own with pyarrow's
`ParquetWriter`, one after another: slower, for frames whose rows differ
too much for row groups of a number of rows.
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import BinaryIO

import polars as pl
import pyarrow.parquet as pq

# Rows of a row group of a file at most, whatever the frames.
PARQUET_ROW_GROUP_ROWS = 1_048_576
# Seconds out of `write` without a write after which a frame is handed on anyway.
STALL_SECONDS = 5.0
# Seconds between looks at the writes while a frame waits.
POLL_SECONDS = 0.01
# Bytes (`estimated_size`) of the frames handed on since the last wait from which the next frame waits.
PACED_BYTES = 8 * 2**20
# The magic bytes at the start of a Parquet file.
MAGIC = b"PAR1"


def chunk_frame(
    chunks: Iterable[pl.DataFrame], received: Callable[[int], None] | None = None
) -> pl.LazyFrame:
    """Return a lazy frame that reads frames of the same schema one after another.

    The first frame is taken at once, for the schema; there must be one.
    The frame can be collected or sunk once only: the frames are not held
    once handed on.

    Parameters
    ----------
    chunks : iterable of polars.DataFrame
        The frames, in their order; the first one gives the schema.
    received : callable, optional
        Called with the rows of the frames handed on so far, just before
        each frame after the first is handed on.

    Returns
    -------
    polars.LazyFrame
        The frames one under another.
    """
    rest = iter(chunks)
    held = [next(rest)]
    schema = held[0].schema

    def frames() -> Iterator[pl.DataFrame]:
        """Yield the first frame, then the others."""
        while held:
            yield held.pop()
        yield from rest

    def source(
        with_columns: list[str] | None,
        predicate: pl.Expr | None,
        n_rows: int | None,
        batch_size: int | None,
    ) -> Iterator[pl.DataFrame]:
        """Yield the frames, filtered, projected and cut to `n_rows`; `batch_size` is a hint left unused."""
        handed = taken = 0
        for chunk in frames():
            if handed and received is not None:
                received(handed)
            handed += chunk.height
            if predicate is not None:
                chunk = chunk.filter(predicate)
            if with_columns is not None:
                chunk = chunk.select(with_columns)
            if n_rows is not None:
                chunk = chunk.head(n_rows - taken)
            taken += chunk.height
            yield chunk
            # Not held while the next frame is made.
            del chunk
            if n_rows is not None and taken >= n_rows:
                return

    return pl.io.plugins.register_io_source(source, schema=schema)


def _varint(b: bytes, i: int) -> tuple[int, int]:
    """Return the unsigned varint at `i` of `b` and the index after it."""
    value = shift = 0
    while True:
        byte = b[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return value, i


def _skip(b: bytes, i: int, kind: int) -> int:  # noqa: C901, PLR0912
    """Return the index after the thrift compact value of type `kind` at `i` of `b`."""
    if kind in (1, 2):
        return i
    if kind == 3:
        return i + 1
    if kind in (4, 5, 6):
        return _varint(b, i)[1]
    if kind == 7:
        return i + 8
    if kind == 8:
        n, i = _varint(b, i)
        return i + n
    if kind in (9, 10):
        head = b[i]
        i += 1
        n, item = head >> 4, head & 0x0F
        if n == 15:
            n, i = _varint(b, i)
        if item in (1, 2):
            return i + n
        for _ in range(n):
            i = _skip(b, i, item)
        return i
    if kind == 11:
        n, i = _varint(b, i)
        if n:
            head = b[i]
            i += 1
            for _ in range(n):
                i = _skip(b, _skip(b, i, head >> 4), head & 0x0F)
        return i
    if kind == 12:
        while True:
            head = b[i]
            i += 1
            if head == 0:
                return i
            if not head >> 4:
                i = _varint(b, i)[1]
            i = _skip(b, i, head & 0x0F)
    raise ValueError(f"no thrift type {kind}")


def _header(b: bytes) -> tuple[int, int | None]:
    """Read the thrift struct at the start of `b`: a page header or the metadata of a column chunk.

    Returns
    -------
    end : int
        The index after the struct.
    page : int or None
        For a page header, the bytes of its page (`compressed_page_size`);
        None for column metadata. Both begin with an int (the type);
        the second field of column metadata is a list (the encodings),
        that of a page header an int. The page indexes and the footer
        polars writes after the row groups are not read.

    Raises
    ------
    IndexError
        When `b` ends within the struct.
    ValueError
        When the struct is neither.
    """
    i = field = count = 0
    second = page = None
    while True:
        head = b[i]
        i += 1
        if head == 0:
            break
        kind = head & 0x0F
        if head >> 4:
            field += head >> 4
        else:
            v, i = _varint(b, i)
            field = (v >> 1) ^ -(v & 1)
        count += 1
        if count == 1 and kind != 5:
            raise ValueError("neither a page header nor column metadata")
        if count == 2:
            second = kind
        if field == 3 and kind == 5 and second == 5:
            v, i = _varint(b, i)
            page = (v >> 1) ^ -(v & 1)
        else:
            i = _skip(b, i, kind)
    if i > len(b):
        raise IndexError("the struct goes on")
    if second == 5 and page is not None:
        return i, page
    if second == 9:
        return i, None
    raise ValueError("neither a page header nor column metadata")


def _leaves(frame: pl.DataFrame) -> int:
    """Return the leaf columns, the column chunks of a row group, of a Parquet file of a frame's schema."""
    buffer = io.BytesIO()
    frame.clear().write_parquet(buffer)
    buffer.seek(0)
    return pq.read_metadata(buffer).num_columns


class _Paced:
    """The file polars writes to, which counts the column chunks written to tell when the frames handed on are written.

    Parameters
    ----------
    file : BinaryIO
        The file to write to.
    row_group_rows : int
        The rows of a row group of the sink.
    """

    def __init__(self, file: BinaryIO, row_group_rows: int) -> None:
        self._file = file
        self._rows = row_group_rows
        self._chunks = 0
        # Bytes of a page (or the magic) still to skip, and of a struct cut by a write.
        self._skip = len(MAGIC)
        self._part = bytearray()
        self._lost = False
        self._writing = False
        self._failed = False
        self._last = time.perf_counter()

    def write(self, data: bytes) -> int:
        """Write bytes, reading the structs in them."""
        self._writing = True
        try:
            n = self._file.write(data)
        except BaseException:
            self._failed = True
            raise
        finally:
            self._writing = False
            self._last = time.perf_counter()
        self._read(memoryview(data)[:n])
        return n

    def flush(self) -> None:
        """Flush the file."""
        self._file.flush()

    def tell(self) -> int:
        """Return the position in the file."""
        return self._file.tell()

    def _read(self, view: memoryview) -> None:
        """Count the column chunks whose metadata the bytes end, skipping the pages."""
        while view and not self._lost:
            if self._skip:
                n = min(self._skip, len(view))
                self._skip -= n
                view = view[n:]
                continue
            size = 256
            while True:
                head = bytes(self._part) + bytes(view[:size])
                try:
                    end, page = _header(head)
                    break
                except IndexError:
                    if size >= len(view):
                        self._part += view
                        return
                    size *= 8
                except ValueError:
                    self._lost = True
                    return
            view = view[end - len(self._part) :]
            self._part.clear()
            if page is None:
                self._chunks += 1
            else:
                self._skip = page

    def frames(self, chunks: Iterable[pl.DataFrame]) -> Iterator[pl.DataFrame]:
        """Yield the frames, making each after the second once polars has written the row groups of the frames before the last one handed on.

        The rows of the last frame handed on fill the row group after
        those (a frame but the last has a row group of rows at least),
        whose bytes bring theirs out of the buffer; when the last frame
        handed on is the last of all and fills none, the row groups but
        the last complete one are waited for.
        """
        rest = iter(chunks)
        leaves = before = handed = size = 0
        while True:
            groups = min(before // self._rows, handed // self._rows - 1)
            if groups > 0 and groups * leaves > self._chunks and size >= PACED_BYTES:
                self._wait(groups * leaves)
                size = 0
            frame = next(rest, None)
            if frame is None:
                return
            if not leaves:
                leaves = _leaves(frame)
            before, handed = handed, handed + frame.height
            size += frame.estimated_size()
            yield frame
            # Not held while the next frame is made.
            del frame

    def _wait(self, need: int) -> None:
        """Return once `need` column chunks are written, a write failed, the bytes were not read, or nothing was written for `STALL_SECONDS` out of `write`."""
        since = time.perf_counter()
        while self._chunks < need and not (self._failed or self._lost):
            idle = time.perf_counter() - max(self._last, since)
            if not self._writing and idle >= STALL_SECONDS:
                return
            time.sleep(POLL_SECONDS)


def sink_chunks(
    chunks: Iterable[pl.DataFrame],
    path: Path,
    row_group_rows: int,
    received: Callable[[int], None] | None = None,
) -> None:
    """Write frames of the same schema one after another as one Parquet file, streamed to `sink_parquet`.

    The file is compressed with zstd, in row groups of `row_group_rows`
    rows (the last one fewer), whatever the frames. A frame is made once
    polars has written the row groups of the frames before the last one
    handed on (`_Paced`). An error raised by `chunks` comes out as it is.

    Parameters
    ----------
    chunks : iterable of polars.DataFrame
        The frames, in their order; there must be one.
    path : pathlib.Path
        The file to write.
    row_group_rows : int
        The rows of a row group, at least 1.
    received : callable, optional
        Called as `chunk_frame` calls it, from a thread of polars.
    """
    with path.open("wb") as file:
        paced = _Paced(file, row_group_rows)
        chunk_frame(paced.frames(chunks), received).sink_parquet(
            paced, compression="zstd", row_group_size=row_group_rows
        )


def write_chunks(
    chunks: Iterable[pl.DataFrame],
    path: Path,
    received: Callable[[int], None] | None = None,
) -> None:
    """Write frames of the same schema one after another as one Parquet file, a row group for each frame.

    The file is compressed with zstd. A frame of more than
    `PARQUET_ROW_GROUP_ROWS` rows is cut into row groups of those rows. The
    values have the arrow types `sink_chunks` writes (texts
    `large_string`). An error raised by `chunks` comes out as it is.

    Parameters
    ----------
    chunks : iterable of polars.DataFrame
        The frames, in their order; there must be one.
    path : pathlib.Path
        The file to write.
    received : callable, optional
        Called with the rows of the frames written so far, just after
        each frame after the first is made.
    """
    writer = None
    written = 0
    try:
        for frame in chunks:
            if writer is not None and received is not None:
                received(written)
            # The arrow types polars writes to a Parquet file of its own.
            table = frame.to_arrow(compat_level=pl.CompatLevel.oldest())
            del frame
            if writer is None:
                writer = pq.ParquetWriter(path, table.schema, compression="zstd")
            writer.write_table(
                table, row_group_size=max(1, min(PARQUET_ROW_GROUP_ROWS, table.num_rows))
            )
            written += table.num_rows
            # Not held while the next frame is made.
            del table
    finally:
        if writer is not None:
            writer.close()
