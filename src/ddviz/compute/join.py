"""Join another table (the joined table) to the input side by side: the map of its rows and the parts of its columns.

A join by keys finds, once, the row of the joined table of each row of the
input (`run_join`): a left join of the input's keys on the joined table's
keys and row index, with `polars_helpers.merge_on_disk`, which keeps its
intermediate data and its result on disk and the rows of the input in their
order. The rows found are written per file of the input as parts of the map (`ddviz.shared.joined.MAP_COLUMN`, null where
no row matches), with the parts of ``_joined``, the merge's indicator. A
column of the joined table is converted when first used, as any column
(`run_join_convert`): per file of the input, its values gathered through the
map. A join by rows needs no map: the part of a file holds the joined
table's rows from the rows of the files before. A join may leave out the
columns named like the input's that hold the same values in the rows joined,
found through the same map (`run_join_equal`). The rows of the joined table
some row of the input matches are found from the map too (`write_matched`),
and rows are split on disk by the hash of their keys (`hash_pieces`), for
the summary and the rows of both tables of a dry run
(`ddviz.compute.joinsummary`, `ddviz.compute.joinrows`).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import polars as pl
import polars_helpers as plh

from ddviz.compute.progress import Emit
from ddviz.compute.scan import scan_columns
from ddviz.compute.tasks.columns import supertype
from ddviz.shared.cache import PARTIAL
from ddviz.shared.joined import BOTH, INDICATOR, MAP_COLUMN
from ddviz.shared.manifest import write_manifest
from ddviz.shared.tasks import JoinConvertTask, JoinEqualTask, JoinTask

# The rows of the joined table a map holds fit 32 bits below this.
UINT32_ROWS = 2**32
# Examples of duplicate keys a refusal shows.
DUPLICATE_EXAMPLES = 5
# A joined table of up to this many rows is merged, and its duplicate keys
# found, in one piece; a larger one in `BUCKETS` pieces by the hash of its
# keys. On 100M rows joined with 1M-10M, one piece was faster and used less
# memory than 16; on 100M with 100M, one piece does not fit 8 GiB.
ONE_BUCKET_ROWS = 10_000_000
BUCKETS = 16
# The column of the file of the rows of the joined table matched (`write_matched`).
MATCHED = "matched"
# The row index of the joined table in the merge, the count of a key in the
# check of duplicates, and the piece of a key, named apart from the keys
# (`_free`).
_ROW = "__ddviz_row"
_COUNT = "__ddviz_count"
_BUCKET = "__ddviz_bucket"


def map_dtype(right_rows: int) -> pl.DataType:
    """Return the type of the map of a joined table of `right_rows` rows: UInt32, or UInt64 from 2^32 rows."""
    return pl.UInt32 if right_rows < UINT32_ROWS else pl.UInt64


def _free(name: str, taken: set[str]) -> str:
    """Return `name`, or it with underscores before, until no column of `taken` has it."""
    while name in taken:
        name = "_" + name
    return name


def _write(frame: pl.DataFrame, file: str) -> None:
    """Write a part under a temporary name, then rename it, so that it appears only once complete."""
    partial = Path(file + PARTIAL)
    partial.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(partial)
    os.replace(partial, file)


def _sink(frame: pl.LazyFrame, file: str) -> None:
    """Sink a part with the streaming engine under a temporary name, then rename it, as `_write` does."""
    partial = Path(file + PARTIAL)
    partial.parent.mkdir(parents=True, exist_ok=True)
    frame.sink_parquet(partial, engine="streaming")
    os.replace(partial, file)


def _text(row: tuple) -> str:
    """Return a key's values as a refusal shows them: a value alone, or ``(a, b)``."""
    if len(row) == 1:
        return str(row[0])
    return "(" + ", ".join(str(v) for v in row) + ")"


def _duplicates(right: pl.LazyFrame, keys: list[str]) -> tuple[int, list[tuple]]:
    """Return the sets of key values more than one row of `right` holds, and the first of them, counted in memory."""
    count = _free(_COUNT, set(keys))
    found = (
        right.group_by(keys)
        .agg(pl.len().alias(count))
        .filter(pl.col(count) > 1)
        .select(keys)
        .sort(keys)
        .collect()
    )
    return found.height, found.head(DUPLICATE_EXAMPLES).rows()


@contextmanager
def hash_pieces(frame: pl.LazyFrame, keys: list[str], buckets: int, work: Path) -> Iterator[list[list[Path]]]:
    """Split the rows of `frame` on disk by the hash of their `keys` into `buckets` pieces, and yield the files of each piece.

    One streaming sink writes the pieces; a set of key values lies in one
    piece only. The pieces are removed when the context ends.

    Parameters
    ----------
    frame : polars.LazyFrame
        The rows to split.
    keys : list of str
        The columns whose values decide the piece of a row.
    buckets : int
        The pieces.
    work : pathlib.Path
        Directory for the pieces, removed at the end.

    Yields
    ------
    list of list of pathlib.Path
        The files of each piece holding rows.
    """
    bucket = _free(_BUCKET, set(frame.collect_schema().names()))
    try:
        frame.with_columns(
            (pl.struct(keys).hash(seed=0) % buckets).alias(bucket)
        ).sink_parquet(
            pl.PartitionBy(work, key=bucket, include_key=False), engine="streaming"
        )
        # A piece may be written as several files in its directory
        # (``<bucket>=<n>/``): it is read with all of them.
        pieces: dict[Path, list[Path]] = {}
        for file in sorted(work.rglob("*.parquet")):
            pieces.setdefault(file.parent, []).append(file)
        yield list(pieces.values())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def duplicate_keys(
    right: pl.LazyFrame, keys: list[str], buckets: int, work: Path
) -> tuple[int, list[str]]:
    """Return the sets of key values more than one row of the joined table holds, and the first of them.

    A set with a null is left out: it matches no row. With several
    `buckets`, the keys are split on disk by their hash with one streaming
    sink, and each piece is counted in memory: on 100M rows, counting at
    once took 6.28 GiB for Int64 keys and over 9 GiB for String keys, and in
    16 pieces 1.12 GiB and 1.69 GiB. A set lies in one piece only, so the
    first sets of all are among the first of each piece.

    Parameters
    ----------
    right : polars.LazyFrame
        The joined table's keys.
    keys : list of str
        The keys.
    buckets : int
        The pieces the keys are counted in.
    work : pathlib.Path
        Directory for the pieces, removed before returning; unused with one
        bucket.

    Returns
    -------
    count : int
        The sets held by several rows.
    examples : list of str
        The first `DUPLICATE_EXAMPLES` of them, in ascending order (`_text`).
    """
    right = right.select(keys).drop_nulls()
    if buckets == 1:
        count, first = _duplicates(right, keys)
        return count, [_text(r) for r in first]
    count, first = 0, []
    with hash_pieces(right, keys, buckets, work) as pieces:
        for files in pieces:
            found, rows = _duplicates(pl.scan_parquet(files), keys)
            count += found
            first += rows
    examples = pl.DataFrame(first, schema=right.collect_schema(), orient="row").sort(keys)
    return count, [_text(r) for r in examples.head(DUPLICATE_EXAMPLES).rows()]


def write_matched(maps: list[str], right_rows: int, file: Path) -> int:
    """Write whether a row of the input matched each row of the joined table, and return the rows matched.

    Parameters
    ----------
    maps : list of str
        The parts of the map (`MAP_COLUMN`), read one at a time.
    right_rows : int
        The rows of the joined table.
    file : pathlib.Path
        The Parquet file to write: per row of the joined table, in order,
        `MATCHED` (Boolean).

    Returns
    -------
    int
        The rows of the joined table some row of the input matched.
    """
    matched = np.zeros(right_rows, dtype=bool)
    for part in maps:
        rows = pl.read_parquet(part, columns=[MAP_COLUMN])[MAP_COLUMN].drop_nulls().to_numpy()
        matched[rows] = True
        del rows
    pl.DataFrame({MATCHED: matched}).write_parquet(file)
    return int(matched.sum())


def _refuse(out: Path, message: str) -> None:
    """Write a join refused for the reason the user is told (400)."""
    write_manifest(out, {"kind": "join", "refused": message})


def run_join(task: JoinTask, out: Path, emit: Emit) -> None:
    """Write the map of the joined table's rows and ``_joined`` for each file of the input.

    The keys of each pair are compared in the type both cast to
    (`ddviz.compute.tasks.columns.supertype`); a null key matches no row.
    A join is refused (the manifest's ``refused``, the reason as the user
    reads it) when a pair has no such type, or when several rows of the
    joined table hold the same keys, which would add rows to the input.
    The merge keeps its intermediate data and its result on disk under
    `out` (`polars_helpers.merge_on_disk`), in one piece for a joined table
    of up to `ONE_BUCKET_ROWS` rows and in `BUCKETS` pieces above. The parts
    are sunk from the result file by file, and the result is then removed.

    Parameters
    ----------
    task : JoinTask
        The keys, their parts, and the parts to write.
    out : pathlib.Path
        Directory to write the result into: the manifest, with ``matched``,
        the rows of the input a row of the joined table matched.
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "join"})
    # The row index is named apart from the keys, which then take names of
    # their own (``l0``, ``r0``, ...), apart from the row index.
    row = _free(_ROW, {k["right"] for k in task.keys})
    left = scan_columns({k["left"]: task.left[k["left"]] for k in task.keys}, None, False)
    right = scan_columns(
        {k["right"]: task.right[k["right"]] for k in task.keys}, row, False
    )
    left_types, right_types = left.collect_schema(), right.collect_schema()
    lefts, rights = [], []
    for i, pair in enumerate(task.keys):
        a, b = left_types[pair["left"]], right_types[pair["right"]]
        try:
            common = supertype(a, b)
        except ValueError:
            _refuse(
                out,
                f"キーの型が合いません：{pair['left']}（{a}）と {pair['right']}（{b}）",
            )
            return
        lefts.append(pl.col(pair["left"]).cast(common, strict=False).alias(f"l{i}"))
        rights.append(pl.col(pair["right"]).cast(common, strict=False).alias(f"r{i}"))
    left_on = [f"l{i}" for i in range(len(lefts))]
    right_on = [f"r{i}" for i in range(len(rights))]
    right = right.select(pl.col(row).cast(map_dtype(task.right_rows)).alias(_ROW), *rights)
    left = left.select(*lefts)
    buckets = 1 if task.right_rows <= ONE_BUCKET_ROWS else BUCKETS
    count, examples = duplicate_keys(right, right_on, buckets, out / "duplicates")
    if count:
        _refuse(
            out,
            f"結合する表でキーが重複しています：{count:,} 組（例：{'、'.join(examples)}）",
        )
        return
    merged = plh.merge_on_disk(
        left,
        right,
        left_on=left_on,
        right_on=right_on,
        how="left",
        indicator=INDICATOR,
        directory=out / "merge",
        delete_on_exit=False,
        buckets=buckets,
    ).select(_ROW, INDICATOR)
    matched = merged.select((pl.col(INDICATOR) == BOTH).sum()).collect().item()
    start = 0
    for rows, map_part, indicator in zip(task.rows, task.maps, task.indicators, strict=True):
        piece = merged.slice(start, rows)
        start += rows
        _sink(piece.select(pl.col(_ROW).alias(MAP_COLUMN)), map_part)
        _sink(piece.select(pl.col(INDICATOR).alias(task.indicator)), indicator)
    shutil.rmtree(out / "merge")
    write_manifest(out, {"kind": "join", "matched": int(matched)})


def run_join_convert(task: JoinConvertTask, out: Path, emit: Emit) -> None:
    """Write the parts of columns a join added, and count their non-null values.

    A column of the joined table is read once, from its parts in its column
    cache. For a join by keys, the part of a file of the input is its values
    gathered through the file's map (null where no row matched); for a join
    by rows, the joined table's rows from the rows of the files before.

    Parameters
    ----------
    task : JoinConvertTask
        The columns, the joined table's parts and the parts to write.
    out : pathlib.Path
        Directory to write the result into: the manifest, with ``nonnull``,
        the non-null values of each part written.
    emit : callable
        Receives a ``progress`` message before each part, with ``done`` and
        ``total`` counts.
    """
    starts = [sum(task.rows[:i]) for i in range(len(task.rows))]
    total = sum(len(parts) for parts in task.parts)
    done = 0
    nonnull: dict[str, int] = {}
    for column, held in task.columns.items():
        values = pl.scan_parquet(task.right[held]).select(held).collect()[held]
        for j, (i, parts) in enumerate(zip(task.files, task.parts, strict=True)):
            if column not in parts:
                continue
            emit(
                {
                    "type": "progress",
                    "stage": "convert",
                    "column": column,
                    "done": done,
                    "total": total,
                }
            )
            done += 1
            if task.maps:
                rows = pl.read_parquet(task.maps[j], columns=[MAP_COLUMN])[MAP_COLUMN]
                part = values.gather(rows)
                del rows
            else:
                part = values.slice(starts[i], task.rows[i])
            _write(part.alias(column).to_frame(), parts[column])
            nonnull[parts[column]] = len(part) - part.null_count()
            del part
        del values
    write_manifest(out, {"kind": "join_convert", "nonnull": nonnull})


def _same_values(task: JoinEqualTask, pair: dict[str, str]) -> bool:
    """Return whether the rows joined, at least one, hold the same values in both columns of `pair`.

    The two columns are cast to the type both cast to
    (`ddviz.compute.tasks.columns.supertype`) and compared with
    `polars.Series.eq_missing`: two nulls are equal. Columns of no such
    type differ. A row of the input no row of the joined table matched is
    not compared. The input is read file by file, and the files after the
    first one that differs are not read.
    """
    left, right = pair["left"], pair["right"]
    values = pl.scan_parquet(task.right[right]).select(right).collect()[right]
    parts = task.left[left]
    try:
        common = supertype(pl.scan_parquet(parts[0]).collect_schema()[left], values.dtype)
    except ValueError:
        return False
    values = values.cast(common, strict=False)
    start, joined = 0, 0
    for i, (rows, part) in enumerate(zip(task.rows, parts, strict=True)):
        mine = pl.read_parquet(part, columns=[left])[left].cast(common, strict=False)
        if task.maps:
            found = pl.read_parquet(task.maps[i], columns=[MAP_COLUMN])[MAP_COLUMN]
            kept = found.is_not_null()
            theirs = values.gather(found.filter(kept))
            mine = mine.filter(kept)
            del found, kept
        else:
            theirs = values.slice(start, rows)
        start += rows
        if not mine.eq_missing(theirs).all():
            return False
        joined += len(mine)
    return joined > 0


def run_join_equal(task: JoinEqualTask, out: Path, emit: Emit) -> None:
    """Find which columns of the input hold, in the rows joined, the same values as the joined table's named alike.

    Parameters
    ----------
    task : JoinEqualTask
        The pairs of columns, their parts, and the map of a join by keys.
    out : pathlib.Path
        Directory to write the result into: the manifest, with ``equal``,
        the columns of the input of the pairs whose values are the same
        (`_same_values`), in the order of the pairs.
    emit : callable
        Receives a ``progress`` message before each pair, with ``done`` and
        ``total`` counts and the input's column.
    """
    equal = []
    for done, pair in enumerate(task.pairs):
        emit(
            {
                "type": "progress",
                "stage": "compare",
                "done": done,
                "total": len(task.pairs),
                "column": pair["left"],
            }
        )
        if _same_values(task, pair):
            equal.append(pair["left"])
    write_manifest(out, {"kind": "join_equal", "equal": equal})
