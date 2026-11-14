"""Tests of writing data frames one after another as one Parquet file."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from ddviz.compute import chunksink
from ddviz.compute.chunksink import chunk_frame, sink_chunks


def _chunks() -> list[pl.DataFrame]:
    """Return frames of the same schema with numbers, texts and nulls, of uneven rows."""
    frames = []
    start = 0
    for rows in (5, 1, 0, 12, 7):
        index = list(range(start, start + rows))
        frames.append(
            pl.DataFrame(
                {
                    "index": pl.Series(index, dtype=pl.UInt32),
                    "x": [float(i) if i % 4 else None for i in index],
                    "s": [f"t{i}" for i in index],
                }
            )
        )
        start += rows
    return frames


def test_the_file_is_the_frames_one_under_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file holds the frames in their order, compressed with zstd, in row groups of at most `PARQUET_ROW_GROUP_ROWS`."""
    monkeypatch.setattr(chunksink, "PARQUET_ROW_GROUP_ROWS", 4)
    frames = _chunks()
    path = tmp_path / "data.parquet"
    received: list[int] = []
    sink_chunks(iter(frames), path, received.append)
    assert pl.read_parquet(path).equals(pl.concat(frames))
    meta = pq.ParquetFile(path).metadata
    groups = [meta.row_group(i) for i in range(meta.num_row_groups)]
    assert sum(g.num_rows for g in groups) == 25
    assert max(g.num_rows for g in groups) == 4
    assert {g.column(c).compression for g in groups for c in range(3)} == {"ZSTD"}
    # Before each frame after the first, the rows of those before it.
    assert received == [5, 6, 6, 18]


def test_no_rows_give_a_file_of_typed_columns(tmp_path: Path) -> None:
    """A single frame of no row writes a file of no row with the frame's types."""
    empty = _chunks()[2]
    path = tmp_path / "empty.parquet"
    sink_chunks([empty], path)
    saved = pl.read_parquet(path)
    assert saved.height == 0
    assert saved.schema == empty.schema


@pytest.mark.parametrize(
    "query",
    [
        lambda f: f.select("s", "index"),
        lambda f: f.filter(pl.col("x") > 10),
        lambda f: f.head(8),
        lambda f: f.head(0),
        lambda f: f.filter(pl.col("x").is_null()).select("s").head(3),
    ],
    ids=["select", "filter", "head", "head-0", "all"],
)
def test_a_query_of_the_frame_is_that_of_the_frames(
    query: Callable[[pl.LazyFrame | pl.DataFrame], pl.LazyFrame | pl.DataFrame],
) -> None:
    """Selecting, filtering and taking the first rows of the lazy frame give what they give on the frames together."""
    frames = _chunks()
    assert query(chunk_frame(iter(frames))).collect().equals(
        query(pl.concat(frames))
    )


def test_the_first_frame_is_taken_at_once_the_others_as_read() -> None:
    """The lazy frame takes the first frame for its schema, and the others only as it is read."""
    taken: list[int] = []

    def frames() -> Iterator[pl.DataFrame]:
        """Yield the frames, noting each one taken."""
        for i, frame in enumerate(_chunks()):
            taken.append(i)
            yield frame

    lazy = chunk_frame(frames())
    assert taken == [0]
    assert lazy.collect().height == 25
    assert taken == [0, 1, 2, 3, 4]
