"""Task that writes the rows of a drawn plot as a file to save.

The rows are those the plot draws (`drawn_rows`), every row the local
filter keeps, or the rows a box selects, as the selection table lists them
(`ddviz.compute.selection.selection_filter`); the columns are those the
task lists, with the row index first. The rows are found from the column
cache, their indices streamed to a file (`sink_parquet`, the streaming
engine the selection table collects its pages with), then read a chunk
after another (`ddviz.compute.rowsread`) and written as
`ddviz.compute.savefile` writes a file to save.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ddviz.compute.aggregate import INDEX
from ddviz.compute.axisposition import on_axis
from ddviz.compute.missing import drawn_conditions
from ddviz.compute.progress import Emit
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.compute.rowsread import ColumnReader
from ddviz.compute.savefile import VALUE_BYTES, index_name, write_rows
from ddviz.compute.scan import scan_columns
from ddviz.compute.selection import selection_columns, selection_filter
from ddviz.shared.manifest import PlotManifest, write_manifest
from ddviz.shared.scatter import ONE_BAND, ScatterSpec
from ddviz.shared.tasks import PlotDataTask


def _on_axis(spec: ScatterSpec, column: str, log: list[str]) -> pl.Expr:
    """Return whether a row has a place along an axis of a column, as the aggregation draws it."""
    if column == ONE_BAND:
        return pl.lit(True)
    if column in spec.categorical:
        return pl.col(column).is_not_null()
    return on_axis(pl.col(column).cast(pl.Float64), column in log)


def drawn_rows(spec: ScatterSpec) -> list[pl.Expr]:
    """Return the conditions of the rows a plot draws.

    A row is drawn when the local filter keeps it, its color, symbol, row
    and col are drawn (`ddviz.compute.missing.drawn_conditions`), and some
    panel places it: its x and y have a place on that panel's axes (finite,
    positive on a log axis, not null on a categorical axis). A row placed on
    several panels is one row.

    Parameters
    ----------
    spec : ScatterSpec
        The spec of the drawn result.

    Returns
    -------
    list of polars.Expr
        Conditions to filter on.
    """
    placed = [
        _on_axis(spec, x, spec.log_x) & _on_axis(spec, y, spec.log_y)
        for x in spec.x
        for y in spec.y
    ]
    return [
        *drawn_conditions(spec),
        *filter_conditions(spec.filters),
        pl.any_horizontal(placed),
    ]


def _indices(task: PlotDataTask, spec: ScatterSpec, out: Path) -> pl.LazyFrame:
    """Return the row indices (`INDEX`) of the rows of the file, in order: streamed to ``rows.parquet`` in `out` when only some rows are."""
    if task.rows == "selected":
        # As the selection table reads its pages (`run_table`).
        conditions = selection_filter(spec, INDEX)
        read = selection_columns(spec)
    elif task.rows == "drawn":
        conditions = drawn_rows(spec)
        roles = [spec.color, spec.symbol, spec.row, spec.col]
        read = [
            c
            for c in dict.fromkeys([*spec.x, *spec.y, *roles, *filter_columns(spec.filters)])
            if c is not None and c != ONE_BAND
        ]
    else:
        conditions = filter_conditions(spec.filters)
        read = filter_columns(spec.filters)
    if conditions:
        rows = out / "rows.parquet"
        scan_columns({c: spec.files[c] for c in read}, INDEX).filter(
            *conditions
        ).select(INDEX).sink_parquet(rows)
        return pl.scan_parquet(rows)
    # Every row: counted from the footers of any column of the plot.
    column = next(c for c in spec.files if c != ONE_BAND)
    n = scan_columns({column: spec.files[column]}).select(pl.len()).collect()
    return pl.LazyFrame().select(
        pl.int_range(n.item(), dtype=pl.get_index_type()).alias(INDEX)
    )


def run_plot_data(task: PlotDataTask, out: Path, emit: Emit) -> None:
    """Write the rows of a plot task's result, or of a selection, as a file (`ddviz.compute.savefile.write_rows`).

    The selected rows are those of the task's ``selection``, the spec the
    server had when asked: the selection layer's directory is not read, so
    a layer replaced meanwhile changes nothing.

    Progress messages carry the stage ``"export"`` and the task's
    ``export``; once the rows are counted, also ``done`` and ``total``,
    the rows written (for a Parquet file, those the sink received) and to
    write.

    Parameters
    ----------
    task : PlotDataTask
        The result or the selection, the rows and columns, and where to
        read them from.
    out : pathlib.Path
        Directory to write the file into; the manifest names it.
    emit : callable
        Receives progress messages.
    """
    if task.rows == "selected":
        spec = task.selection
    else:
        spec = PlotManifest.read(Path(task.result)).spec
    progress = {"type": "progress", "stage": "export", "export": task.export}
    emit(progress)
    indices = _indices(task, spec, out)
    total = indices.select(pl.len()).collect().item()
    emit({**progress, "done": 0, "total": total})
    reader = ColumnReader(task.source, task.parts, task.columns)
    name = index_name(task.columns)

    def read(chunk: pl.DataFrame, measure: bool) -> pl.DataFrame:
        """Return the values of the rows of `chunk`, the row index first, or with `measure` the bytes of their values of variable size."""
        frames = reader.read(chunk[INDEX], measure=measure)
        if measure:
            return pl.concat(frames, how="horizontal")
        # Columns picked by name keep their chunks; a `select` of
        # expressions would copy the chunk's values into one chunk a
        # column, as its columns are chunked apart.
        return pl.concat([chunk, *frames], how="horizontal").rename({INDEX: name})[
            [name, *task.columns]
        ]

    def received(done: int) -> None:
        """Report the rows written so far."""
        emit({**progress, "done": done, "total": total})

    file = f"data.{task.file_format}"
    # Every value counts VALUE_BYTES, the row index too; texts, binaries and
    # nested values count their bytes besides.
    fixed = VALUE_BYTES * (len(task.columns) + 1)
    write_rows(indices, total, fixed, read, out / file, task.file_format, received)
    (out / "rows.parquet").unlink(missing_ok=True)
    write_manifest(out, {"kind": "plot_data", "file": file})
