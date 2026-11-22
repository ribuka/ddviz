"""Task that writes the rows of both tables of a join by keys before it is made, as a file to save: a full outer join with the state of each row.

The rows come from the map of the dry run (`ddviz.compute.join.run_join`),
without another merge: first every row of the input, in its order, beside
the row of the joined table its map holds (nulls for none; a row of the
joined table several rows match comes as often); then the rows of the
joined table no row of the input matches
(`ddviz.compute.join.write_matched`), in its order, beside nulls. Their row
numbers are streamed to a file, then read a chunk after another
(`ddviz.compute.rowsread`): the input's columns with the joined table's
through the map, as a column a join added is read
(`ddviz.compute.joinread`), or the joined table's alone; and written as
`ddviz.compute.savefile` writes a file to save.

The columns (`join_rows_columns`): the state (``_joined``: ``both``,
``left_only`` or ``right_only``), the row numbers of the input (``index``,
as a saved plot's) and of the joined table (``index_joined``), the keys of
the input, those of the joined table, then the other columns of each:
their added columns (``source``, ``filename``) for the keys only, all of
them otherwise. The input's columns keep their names; the three first take
``_2``, ``_3``, ... when a column of the input has theirs; the joined
table's are named as a join adds them (`ddviz.shared.joined.joined_names`),
after the input's columns and those three.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import polars as pl

from ddviz.compute.join import MATCHED, write_matched
from ddviz.compute.progress import Emit
from ddviz.compute.rowsread import ColumnReader
from ddviz.compute.savefile import INDEX_NAME, VALUE_BYTES, numbered, write_rows
from ddviz.compute.scan import scan_columns
from ddviz.shared.joined import INDICATOR, MAP_COLUMN, RIGHT_ONLY, SUFFIX, joined_names
from ddviz.shared.manifest import write_manifest
from ddviz.shared.tasks import JoinedFiles, JoinRowsTask

# The rows of the input and of the joined table of each row of the file,
# in the file of the rows.
_LEFT = "__ddviz_left"
_RIGHT = "__ddviz_right"


@dataclasses.dataclass(frozen=True)
class JoinRowsColumns:
    """The columns of the file of the rows of both tables, in order (`join_rows_columns`).

    Parameters
    ----------
    state : str
        The state of each row (``_joined``).
    index, index_joined : str
        The row numbers of the input and of the joined table.
    left : list of str
        The input's columns, its keys first.
    right : dict of str to str
        The joined table's columns, its keys first, under their names in
        the file, with the column each holds.
    keys : int
        The pairs of keys.
    """

    state: str
    index: str
    index_joined: str
    left: list[str]
    right: dict[str, str]
    keys: int

    @property
    def names(self) -> list[str]:
        """Return the names of the columns, in order: the three first, the keys of each table, then the other columns of each."""
        n = self.keys
        right = list(self.right)
        return [self.state, self.index, self.index_joined, *self.left[:n], *right[:n], *self.left[n:], *right[n:]]


def join_rows_columns(task: JoinRowsTask) -> JoinRowsColumns:
    """Return the columns of the file and their names.

    The names do not depend on ``columns``: a column has the same name with
    the keys only and with all the columns.

    Parameters
    ----------
    task : JoinRowsTask
        The keys and the columns of both tables.

    Returns
    -------
    JoinRowsColumns
        The columns.
    """
    taken = set(task.left_columns)
    named = []
    for base in (INDICATOR, INDEX_NAME, INDEX_NAME + SUFFIX):
        named.append(numbered(base, taken))
        taken.add(named[-1])
    lefts = [k["left"] for k in task.keys]
    rights = [k["right"] for k in task.keys]
    plain = [c for c in task.right_columns if c not in rights and c not in task.right_generated]
    generated = {c: k for c, k in task.right_generated.items() if c not in rights}
    names = joined_names(taken, [*rights, *plain], generated, False)
    by_right = {held: name for name, held in names.items()}
    if task.columns == "key":
        left = [*lefts, *(c for c in task.left_columns if c in task.left_generated and c not in lefts)]
        right = [*rights, *generated]
    else:
        left = [*lefts, *(c for c in task.left_columns if c not in lefts)]
        right = [*rights, *(c for c in task.right_columns if c not in rights)]
    return JoinRowsColumns(*named, left, {by_right[c]: c for c in right}, len(task.keys))


def _rows(task: JoinRowsTask, out: Path) -> tuple[pl.LazyFrame, int]:
    """Stream the rows of the input and of the joined table of each row of the file to ``rows.parquet`` in `out`; return them and how many."""
    right_rows = sum(task.right_files.rows)
    matched = out / "matched.parquet"
    found = write_matched(task.maps, right_rows, matched)
    index = pl.get_index_type()
    left = scan_columns({MAP_COLUMN: task.maps}, _LEFT, False).select(
        pl.col(_LEFT).cast(index), pl.col(MAP_COLUMN).cast(index).alias(_RIGHT)
    )
    right = (
        pl.scan_parquet(matched, row_index_name=_RIGHT)
        .filter(~pl.col(MATCHED))
        .select(pl.lit(None, index).alias(_LEFT), pl.col(_RIGHT).cast(index))
    )
    rows = out / "rows.parquet"
    pl.concat([left, right]).sink_parquet(rows)
    matched.unlink()
    return pl.scan_parquet(rows), sum(task.left_files.rows) + right_rows - found


def _sizes(frames: list[pl.DataFrame], rows: int, extra: int) -> pl.Series:
    """Return the bytes of the values of variable size of each of `rows` rows, from their `frames`, and `extra` more."""
    lengths = pl.concat(frames, how="horizontal") if frames else pl.DataFrame()
    if lengths.width == 0:
        return pl.repeat(extra, rows, dtype=pl.Int64, eager=True)
    return lengths.sum_horizontal().cast(pl.Int64) + extra


def run_join_rows(task: JoinRowsTask, out: Path, emit: Emit) -> None:
    """Write the rows of both tables, a full outer join through the map of the dry run, as a file.

    Progress messages carry the stage ``"export"`` and the task's
    ``export``; once the rows are counted, also ``done`` and ``total``, as
    those of a saved plot's (`ddviz.compute.tasks.plotdata.run_plot_data`).

    Parameters
    ----------
    task : JoinRowsTask
        The keys, the map, the columns of both tables and where to read
        them from.
    out : pathlib.Path
        Directory to write the file into; the manifest names it.
    emit : callable
        Receives progress messages.
    """
    progress = {"type": "progress", "stage": "export", "export": task.export}
    emit(progress)
    columns = join_rows_columns(task)
    rows, total = _rows(task, out)
    emit({**progress, "done": 0, "total": total})
    # The input's rows read with the joined table's columns through the map,
    # as a join adds them, with the state (None: both or left_only).
    joined = JoinedFiles(
        {columns.state: None, **columns.right}, task.maps, task.right_parts, task.right_files
    )
    both = ColumnReader(
        dataclasses.replace(task.left_files, joined=joined),
        task.left_parts,
        [*columns.left, columns.state, *columns.right],
    )
    alone = ColumnReader(task.right_files, task.right_parts, list(columns.right.values()))

    def read(chunk: pl.DataFrame, measure: bool) -> pl.DataFrame:
        """Return the rows of `chunk`, those of the input first, or with `measure` the bytes of their values of variable size."""
        lefts = chunk.filter(pl.col(_LEFT).is_not_null())
        rights = chunk.filter(pl.col(_LEFT).is_null())
        top = both.read(lefts[_LEFT], measure=measure)
        bottom = alone.read(rights[_RIGHT], measure=measure)
        if measure:
            sizes = [_sizes(top, lefts.height, 0), _sizes(bottom, rights.height, len(RIGHT_ONLY))]
            return pl.DataFrame({"bytes": pl.concat(sizes)})
        first = pl.concat([lefts, *top], how="horizontal")
        second = pl.concat([rights, *bottom], how="horizontal")
        held = [
            first[_LEFT].alias(columns.index),
            first[_RIGHT].alias(columns.index_joined),
            *(first[c] for c in [columns.state, *columns.left, *columns.right]),
        ]
        alone_rows = [
            second[_LEFT].alias(columns.index),
            second[_RIGHT].alias(columns.index_joined),
            pl.repeat(RIGHT_ONLY, second.height, dtype=pl.String, eager=True).alias(columns.state),
            *(pl.repeat(None, second.height, dtype=first[c].dtype, eager=True).alias(c) for c in columns.left),
            *(second[held_by].alias(name) for name, held_by in columns.right.items()),
        ]
        return pl.concat(
            [pl.DataFrame(held), pl.DataFrame(alone_rows)], how="vertical"
        ).select(columns.names)

    def received(done: int) -> None:
        """Report the rows written so far."""
        emit({**progress, "done": done, "total": total})

    file = f"data.{task.file_format}"
    fixed = VALUE_BYTES * len(columns.names)
    write_rows(rows, total, fixed, read, out / file, task.file_format, received)
    (out / "rows.parquet").unlink(missing_ok=True)
    write_manifest(out, {"kind": "join_rows", "file": file})
