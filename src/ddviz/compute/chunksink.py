"""Write data frames that come one after another as one Parquet file.

`sink_chunks` makes the frames the source of a polars IO plugin
(`register_io_source`), whose lazy frame is streamed to `sink_parquet`:
polars writes a frame while the next is made, and writes the columns in
parallel. The plugin API is unstable; `pyproject.toml` pins the polars
version it was checked with. polars holds the rows of a row group until it
has them all and cuts row groups by rows only, so the caller gives the
rows of a row group.

`write_chunks` writes each frame as a row group of its own with pyarrow's
`ParquetWriter`, one after another: slower, for frames whose rows differ
too much for row groups of a number of rows.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

# Rows of a row group of a file at most, whatever the frames.
PARQUET_ROW_GROUP_ROWS = 1_048_576


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


def sink_chunks(
    chunks: Iterable[pl.DataFrame],
    path: Path,
    row_group_rows: int,
    received: Callable[[int], None] | None = None,
) -> None:
    """Write frames of the same schema one after another as one Parquet file, streamed to `sink_parquet`.

    The file is compressed with zstd, in row groups of `row_group_rows`
    rows (the last one fewer), whatever the frames. An error raised by
    `chunks` comes out as it is.

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
    chunk_frame(chunks, received).sink_parquet(
        path, compression="zstd", row_group_size=row_group_rows
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
