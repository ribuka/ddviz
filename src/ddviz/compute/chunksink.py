"""Write data frames that come one after another as one Parquet file.

The frames are the source of a polars IO plugin (`register_io_source`),
whose lazy frame is streamed to `sink_parquet`: polars writes a frame while
the next is made, and writes the columns in parallel. The plugin API is
unstable; `pyproject.toml` pins the polars version it was checked with.

polars holds the rows of a row group until it has them all, so a row group
is kept within the rows of the first frame: when frames are cut to a budget
of bytes, a row group holds about that budget as long as the later rows
are no larger than those of the first frame, however many columns there
are. Later rows larger than those (long texts after short ones) gather
more than the budget in a row group: `sink_parquet` cuts row groups by
rows only.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import polars as pl

# Rows of a row group of the file at most, whatever the frames.
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
    return _chunk_frame(chunks, received)[0]


def _chunk_frame(
    chunks: Iterable[pl.DataFrame], received: Callable[[int], None] | None
) -> tuple[pl.LazyFrame, int]:
    """Return the lazy frame of `chunk_frame` and the rows of its first frame.

    Parameters
    ----------
    chunks : iterable of polars.DataFrame
        As for `chunk_frame`.
    received : callable or None
        As for `chunk_frame`.

    Returns
    -------
    polars.LazyFrame
        The frames one under another.
    int
        The rows of the first frame, taken at once.
    """
    rest = iter(chunks)
    held = [next(rest)]
    schema = held[0].schema
    first_rows = held[0].height

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

    return pl.io.plugins.register_io_source(source, schema=schema), first_rows


def sink_chunks(
    chunks: Iterable[pl.DataFrame],
    path: Path,
    received: Callable[[int], None] | None = None,
) -> None:
    """Write frames of the same schema one after another as one Parquet file.

    The file is compressed with zstd, in row groups of at most the rows of
    the first frame (1 when it has none) and `PARQUET_ROW_GROUP_ROWS`. An
    error raised by `chunks` comes out as it is.

    Parameters
    ----------
    chunks : iterable of polars.DataFrame
        The frames, in their order; there must be one.
    path : pathlib.Path
        The file to write.
    received : callable, optional
        Called as `chunk_frame` calls it, from a thread of polars.
    """
    frame, first_rows = _chunk_frame(chunks, received)
    frame.sink_parquet(
        path,
        compression="zstd",
        row_group_size=min(PARQUET_ROW_GROUP_ROWS, max(1, first_rows)),
    )
