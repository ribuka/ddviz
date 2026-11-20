"""Join another table (the joined table) to the input side by side: the map of its rows and the parts of its columns.

A join by keys finds, once, the row of the joined table of each row of the
input (`run_join`): a left join of the input's keys and row index on the
joined table's keys and row index, with `polars_helpers.merge`, which keeps
the rows of the input in their order. The rows found are written per file of
the input as parts of the map (`ddviz.shared.joined.MAP_COLUMN`, null where
no row matches), with the parts of ``_joined``, the merge's indicator. A
column of the joined table is converted when first used, as any column
(`run_join_convert`): per file of the input, its values gathered through the
map. A join by rows needs no map: the part of a file holds the joined
table's rows from the rows of the files before.
"""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import polars_helpers as plh

from ddviz.compute.aggregate import INDEX
from ddviz.compute.progress import Emit
from ddviz.compute.scan import scan_columns
from ddviz.compute.tasks.columns import supertype
from ddviz.shared.cache import PARTIAL
from ddviz.shared.joined import BOTH, INDICATOR, MAP_COLUMN
from ddviz.shared.manifest import write_manifest
from ddviz.shared.tasks import JoinConvertTask, JoinTask

# The rows of the joined table a map holds fit 32 bits below this.
UINT32_ROWS = 2**32
# Examples of duplicate keys a refusal shows.
DUPLICATE_EXAMPLES = 5
# The joined table's row index in the merge.
_ROW = "__ddviz_row"


def map_dtype(right_rows: int) -> pl.DataType:
    """Return the type of the map of a joined table of `right_rows` rows: UInt32, or UInt64 from 2^32 rows."""
    return pl.UInt32 if right_rows < UINT32_ROWS else pl.UInt64


def _write(frame: pl.DataFrame, file: str) -> None:
    """Write a part under a temporary name, then rename it, so that it appears only once complete."""
    partial = Path(file + PARTIAL)
    partial.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(partial)
    os.replace(partial, file)


def _text(row: tuple) -> str:
    """Return a key's values as a refusal shows them: a value alone, or ``(a, b)``."""
    if len(row) == 1:
        return str(row[0])
    return "(" + ", ".join(str(v) for v in row) + ")"


def duplicate_keys(right: pl.LazyFrame, keys: list[str]) -> tuple[int, list[str]]:
    """Return the sets of key values more than one row of the joined table holds, and the first of them.

    A set with a null is left out: it matches no row.

    Parameters
    ----------
    right : polars.LazyFrame
        The joined table's keys.
    keys : list of str
        The keys.

    Returns
    -------
    count : int
        The sets held by several rows.
    examples : list of str
        The first `DUPLICATE_EXAMPLES` of them, in ascending order (`_text`).
    """
    found = (
        right.select(keys)
        .drop_nulls()
        .group_by(keys)
        .agg(pl.len().alias("__n"))
        .filter(pl.col("__n") > 1)
        .select(keys)
        .sort(keys)
        .collect()
    )
    return found.height, [_text(r) for r in found.head(DUPLICATE_EXAMPLES).rows()]


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
    The input is merged at once: a merge too large for the worker's memory
    fails.

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
    left = scan_columns({k["left"]: task.left[k["left"]] for k in task.keys}, INDEX, False)
    right = scan_columns(
        {k["right"]: task.right[k["right"]] for k in task.keys}, _ROW, False
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
    right = right.select(pl.col(_ROW).cast(map_dtype(task.right_rows)), *rights)
    count, examples = duplicate_keys(
        right.select(pl.col(c).alias(task.keys[i]["right"]) for i, c in enumerate(right_on)),
        [k["right"] for k in task.keys],
    )
    if count:
        _refuse(
            out,
            f"結合する表でキーが重複しています：{count:,} 組（例：{'、'.join(examples)}）",
        )
        return
    merged = (
        plh.merge(
            left.select(INDEX, *lefts),
            right,
            left_on=left_on,
            right_on=right_on,
            how="left",
            indicator=INDICATOR,
        )
        .select(INDEX, _ROW, INDICATOR)
        .collect()
    )
    if not merged[INDEX].is_sorted():
        merged = merged.sort(INDEX)
    matched = int((merged[INDICATOR] == BOTH).sum())
    start = 0
    for rows, map_part, indicator in zip(task.rows, task.maps, task.indicators, strict=True):
        piece = merged.slice(start, rows)
        start += rows
        _write(piece.select(pl.col(_ROW).alias(MAP_COLUMN)), map_part)
        _write(piece.select(pl.col(INDICATOR).alias(task.indicator)), indicator)
    write_manifest(out, {"kind": "join", "matched": matched})


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
