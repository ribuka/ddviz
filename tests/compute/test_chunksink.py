"""Tests of writing data frames one after another as one Parquet file."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddviz.compute import chunksink
from ddviz.compute.chunksink import chunk_frame, sink_chunks, write_chunks


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


def _row_groups(path: Path) -> list[int]:
    """Return the rows of each row group of a Parquet file."""
    meta = pq.ParquetFile(path).metadata
    return [meta.row_group(i).num_rows for i in range(meta.num_row_groups)]


def _typed() -> list[pl.DataFrame]:
    """Return frames of the same schema with values of many types: categories, dates, times with a time zone, nested texts and nulls."""
    frame = pl.DataFrame(
        {
            "index": pl.Series(range(6), dtype=pl.UInt32),
            "s": ["a", None, "ccc", "d", "", "f"],
            "c": pl.Series(["a", "b", "a", "c", "b", "a"], dtype=pl.Categorical),
            "e": pl.Series(["a", "b"] * 3, dtype=pl.Enum(["a", "b", "z"])),
            "b": [True, False, None, True, False, True],
            "i": pl.Series([1, 2, 3, None, 5, 6], dtype=pl.Int8),
            "d": [date(2026, 1, i) for i in range(1, 7)],
            "t": pl.Series(
                [datetime(2026, 1, 2, i, tzinfo=UTC) for i in range(6)]
            ).dt.convert_time_zone("Asia/Tokyo"),
            "l": [["a"], [], None, ["b", "c"], ["d"], ["e"]],
            "st": [{"s": str(i), "n": i} for i in range(6)],
            "bin": [bytes([i]) for i in range(6)],
        }
    )
    return [frame[:2], frame[2:5], frame[5:]]


def test_the_file_is_the_frames_one_under_another(tmp_path: Path) -> None:
    """The file holds the frames in their order, compressed with zstd, in row groups of the rows given, whatever the frames."""
    frames = _chunks()
    path = tmp_path / "data.parquet"
    received: list[int] = []
    sink_chunks(iter(frames), path, 4, received.append)
    assert pl.read_parquet(path).equals(pl.concat(frames))
    assert _row_groups(path) == [4] * 6 + [1]
    meta = pq.ParquetFile(path).metadata
    groups = [meta.row_group(i) for i in range(meta.num_row_groups)]
    assert {g.column(c).compression for g in groups for c in range(3)} == {"ZSTD"}
    # Before each frame after the first, the rows of those before it.
    assert received == [5, 6, 6, 18]


def _ends(path: Path) -> list[int]:
    """Return the byte where each row group of a Parquet file ends."""
    meta = pq.ParquetFile(path).metadata
    ends = []
    for i in range(meta.num_row_groups):
        group = meta.row_group(i)
        columns = [group.column(c) for c in range(group.num_columns)]
        ends.append(
            max(
                (c.dictionary_page_offset or c.data_page_offset) + c.total_compressed_size
                for c in columns
            )
        )
    return ends


def test_a_frame_waits_until_those_before_it_are_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the disk writes slowly, a frame is handed on only once the row groups of the frames before it are written."""
    rng = np.random.default_rng(0)
    frames = [
        pl.DataFrame({f"c{c}": rng.standard_normal(40_000) for c in range(8)})
        for _ in range(5)
    ]
    written = [0]
    write = chunksink._Paced.write

    def slow(self: chunksink._Paced, data: bytes) -> int:
        """Write slowly, counting the bytes written."""
        time.sleep(0.01)
        n = write(self, data)
        written[0] += n
        return n

    monkeypatch.setattr(chunksink._Paced, "write", slow)
    monkeypatch.setattr(chunksink, "PACED_BYTES", 0)
    # Not to take a pause of the writing thread for the end of the writes.
    monkeypatch.setattr(chunksink, "IDLE_SECONDS", 0.2)
    handed: list[tuple[int, int]] = []
    path = tmp_path / "data.parquet"
    sink_chunks(iter(frames), path, 30_000, lambda rows: handed.append((rows, written[0])))
    assert pl.read_parquet(path).equals(pl.concat(frames))
    ends = _ends(path)
    assert [rows for rows, _ in handed] == [40_000, 80_000, 120_000, 160_000]
    for rows, at in handed:
        # The complete row groups of the rows handed on before the frame.
        assert at >= ends[rows // 30_000 - 1]


def test_a_failed_write_ends_the_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once a write fails, the frames are handed on at once: polars asks for every frame before it raises the error."""
    rng = np.random.default_rng(0)
    frames = [
        pl.DataFrame({f"c{c}": rng.standard_normal(40_000) for c in range(8)})
        for _ in range(10)
    ]
    write = chunksink._Paced.write

    def failing(self: chunksink._Paced, data: bytes) -> int:
        """Fail once a frame's bytes are written."""
        if self._bytes > 2_000_000:
            self._file.close()
        return write(self, data)

    monkeypatch.setattr(chunksink._Paced, "write", failing)
    monkeypatch.setattr(chunksink, "PACED_BYTES", 0)
    start = time.perf_counter()
    with pytest.raises(pl.exceptions.ComputeError):
        sink_chunks(iter(frames), tmp_path / "data.parquet", 30_000)
    # Waiting `STALL_SECONDS` for each frame would take 8 seconds or more.
    assert time.perf_counter() - start < chunksink.STALL_SECONDS * 4


def test_no_rows_give_a_file_of_typed_columns(tmp_path: Path) -> None:
    """A single frame of no row writes a file of no row with the frame's types."""
    empty = _chunks()[2]
    path = tmp_path / "empty.parquet"
    sink_chunks([empty], path, 1)
    saved = pl.read_parquet(path)
    assert saved.height == 0
    assert saved.schema == empty.schema


def test_writing_a_row_group_for_each_frame(tmp_path: Path) -> None:
    """`write_chunks` writes the frames in their order, compressed with zstd, a row group for each frame."""
    frames = [f for f in _chunks() if f.height]
    path = tmp_path / "data.parquet"
    received: list[int] = []
    write_chunks(iter(frames), path, received.append)
    assert pl.read_parquet(path).equals(pl.concat(frames))
    assert _row_groups(path) == [5, 1, 12, 7]
    meta = pq.ParquetFile(path).metadata
    groups = [meta.row_group(i) for i in range(meta.num_row_groups)]
    assert {g.column(c).compression for g in groups for c in range(3)} == {"ZSTD"}
    # After each frame after the first is made, the rows of those before it.
    assert received == [5, 6, 18]


def test_a_frame_of_many_rows_is_cut_into_row_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`write_chunks` cuts a frame of more than `PARQUET_ROW_GROUP_ROWS` rows into row groups of those rows."""
    monkeypatch.setattr(chunksink, "PARQUET_ROW_GROUP_ROWS", 5)
    frames = [f for f in _chunks() if f.height]
    path = tmp_path / "data.parquet"
    write_chunks(iter(frames), path)
    assert pl.read_parquet(path).equals(pl.concat(frames))
    assert _row_groups(path) == [5, 1, 5, 5, 2, 5, 2]


def test_both_ways_write_the_same_types(tmp_path: Path) -> None:
    """`sink_chunks` and `write_chunks` write the same values with the same polars and arrow types."""
    frames = _typed()
    sunk, written = tmp_path / "sunk.parquet", tmp_path / "written.parquet"
    sink_chunks(iter(frames), sunk, 2)
    write_chunks(iter(frames), written)
    whole = pl.concat(frames)
    assert pl.read_parquet(sunk).equals(whole)
    assert pl.read_parquet(written).equals(whole)
    assert pl.read_parquet(written).schema == whole.schema
    assert pq.read_schema(written).types == pq.read_schema(sunk).types
    assert pq.read_schema(written).field("index").type == pa.uint32()
    assert pq.read_schema(written).field("s").type == pa.large_string()


@pytest.mark.parametrize(
    "write", [write_chunks, lambda c, p: sink_chunks(c, p, 2)], ids=["write", "sink"]
)
def test_an_error_making_a_frame_comes_out_as_it_is(
    tmp_path: Path, write: Callable[[Iterator[pl.DataFrame], Path], None]
) -> None:
    """An error raised making a frame after the first comes out with its own type."""

    def frames() -> Iterator[pl.DataFrame]:
        """Yield the first frame, then fail."""
        yield _chunks()[0]
        raise MemoryError("out of memory")

    with pytest.raises(MemoryError, match="out of memory"):
        write(frames(), tmp_path / "data.parquet")


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
    assert query(chunk_frame(iter(frames))).collect().equals(query(pl.concat(frames)))


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
