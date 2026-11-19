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
`sink_chunks` therefore makes the next frame, then waits to hand it on
until polars has written the row groups of the frames handed on before:
the frame being written and the next one are the two in memory. polars
tells which files it wrote only at the end, so whether it has written is
judged by the writes of the file (not by its size on the disk, which
needs the bytes of the rows): the sink is given a file object of its own
(`_Paced`), whose `write` polars calls page by page. polars has written
the row groups handed on once it has written, since the frame before was
handed on, at least half what it wrote for the frame before that, and has
been out of `write` for `IDLE_SECONDS`; while the disk is slow it stays
in `write`, and it may pause to make the pages of a row group, hence the
half. The wait is polled. It ends at once when a write fails (polars
still asks for every frame before it raises the error), and after
`STALL_SECONDS` without a write since the frame before was handed on (it
has nothing to write), to never hang.
Frames of less than `PACED_BYTES` are not waited for: polars gathers
small writes (a few KiB) until more come, so their pages may not be
written until the next frame, and such frames do not weigh on the memory.
Cancelling kills the process, waiting or not.

`write_chunks` writes each frame as a row group of its own with pyarrow's
`ParquetWriter`, one after another: slower, for frames whose rows differ
too much for row groups of a number of rows.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import BinaryIO

import polars as pl
import pyarrow.parquet as pq

# Rows of a row group of a file at most, whatever the frames.
PARQUET_ROW_GROUP_ROWS = 1_048_576
# Seconds out of `write` after which polars has written what it had.
IDLE_SECONDS = 0.05
# Seconds without a write after which the next frame is handed on anyway.
STALL_SECONDS = 1.0
# Seconds between looks at the writes while a frame waits.
POLL_SECONDS = 0.01
# Bytes (`estimated_size`) of the frames handed on since the last wait from which the next frame waits.
PACED_BYTES = 8 * 2**20


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


class _Paced:
    """The file polars writes to, which tells when the frames handed on are written.

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
        self._bytes = 0
        self._writing = False
        self._failed = False
        self._last = time.perf_counter()

    def write(self, data: bytes) -> int:
        """Write bytes, noting when polars writes."""
        self._writing = True
        try:
            n = self._file.write(data)
        except BaseException:
            self._failed = True
            raise
        finally:
            self._writing = False
            self._last = time.perf_counter()
        self._bytes += n
        return n

    def flush(self) -> None:
        """Flush the file."""
        self._file.flush()

    def tell(self) -> int:
        """Return the position in the file."""
        return self._file.tell()

    def frames(self, chunks: Iterable[pl.DataFrame]) -> Iterator[pl.DataFrame]:
        """Yield the frames, each after the first once polars has written the row groups of those before it.

        A frame is made before it waits. The rows of a row group not yet
        complete are not written until more come, so a frame that leaves
        no new complete row group does not wait. polars may also stop
        writing for a while to make the pages of a row group, so a frame
        waits for at least half the bytes written between the hands of
        the two frames before it: frames of about the same bytes give
        pages of about the same bytes.
        """
        rest = iter(chunks)
        handed = groups = size = 0
        # Bytes written when the frame before and the one before it were handed on.
        mark = before = 0
        at = time.perf_counter()
        for frame in rest:
            if handed // self._rows > groups and size >= PACED_BYTES:
                self._wait(mark + max(1, (mark - before) // 2), at)
                groups, size = handed // self._rows, 0
            handed += frame.height
            size += frame.estimated_size()
            before, mark, at = mark, self._bytes, time.perf_counter()
            yield frame
            # Not held while the next frame is made.
            del frame

    def _wait(self, least: int, at: float) -> None:
        """Return once polars has written `least` bytes and stopped, a write failed, or nothing was written for `STALL_SECONDS` since `at`."""
        while not self._failed:
            if not self._writing:
                now = time.perf_counter()
                if self._bytes >= least and now - self._last >= IDLE_SECONDS:
                    return
                if now - max(self._last, at) >= STALL_SECONDS:
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
    rows (the last one fewer), whatever the frames. A frame is handed on
    once polars has written the row groups of those before it
    (`_Paced`). An error raised by `chunks` comes out as it is.

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
