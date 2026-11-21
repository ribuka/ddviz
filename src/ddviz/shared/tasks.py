"""The tasks the UI server hands to workers, one type per kind.

A task goes to the worker as JSON (`task_to_dict`): its fields and its
``"kind"``; the worker pool adds ``"out"``, the directory to write into.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import ClassVar

from ddviz.shared.scatter import ScatterSpec


@dataclass(frozen=True)
class SourceFiles:
    """The source files of an input, for reading columns not in the column cache.

    Parameters
    ----------
    paths : list of str
        The Parquet files in reading order.
    rows : list of int
        The rows of each.
    schema : str
        Empty Parquet file with the input's type of every column.
    dtypes : dict of str to str
        The input's type of each column to read, as text.
    generated : dict of str to str
        The kind of each added column to read (`ddviz.shared.generated`).
    joined : JoinedFiles or None
        Where to read the columns a join added (`ddviz.shared.joined`),
        which are in none of `dtypes` and `generated`; None without such
        columns.
    """

    paths: list[str]
    rows: list[int]
    schema: str
    dtypes: dict[str, str]
    generated: dict[str, str]
    joined: JoinedFiles | None = None

    @classmethod
    def from_dict(cls, data: dict) -> SourceFiles:
        """Return the files from their JSON (`dataclasses.asdict`)."""
        joined = data.get("joined")
        if joined is not None:
            joined = JoinedFiles(**{**joined, "source": cls.from_dict(joined["source"])})
        return cls(**{**data, "joined": joined})


@dataclass(frozen=True)
class JoinedFiles:
    """Where to read columns a join added to an input, not converted yet (`ddviz.compute.joinread`).

    Parameters
    ----------
    columns : dict of str to str or None
        Per column to read, the column of the joined table it holds; None
        for ``_joined``.
    maps : list of str
        For a join by keys, the parts of the map, one per file of the
        input: each row's row of the joined table, or null
        (`ddviz.shared.joined.MAP_COLUMN`); empty for a join by rows, where
        a row of the input is the same row of the joined table.
    parts : dict of str to list of str
        The parts of columns of the joined table in its column cache.
    source : SourceFiles
        The joined table's files, for its other columns.
    """

    columns: dict[str, str | None]
    maps: list[str]
    parts: dict[str, list[str]]
    source: SourceFiles


@dataclass(frozen=True)
class SchemaTask:
    """Read the columns of Parquet files read one after another as one table.

    Parameters
    ----------
    paths : list of str
        The Parquet files in reading order.
    """

    KIND: ClassVar[str] = "schema"
    paths: list[str]


@dataclass(frozen=True)
class NonnullTask:
    """Count the non-null values of each column (`ddviz.compute.nonnull`).

    Parameters
    ----------
    paths : list of str
        The Parquet files read as one table.
    names : list of str
        Their columns, in schema order.
    generated : list of str
        The added columns among them (`ddviz.shared.generated`).
    """

    KIND: ClassVar[str] = "nonnull"
    paths: list[str]
    names: list[str]
    generated: list[str]


@dataclass(frozen=True)
class ConvertTask:
    """Convert columns of Parquet files into parts of the column cache (`ddviz.compute.convert`).

    Parameters
    ----------
    schema : str
        Empty Parquet file with the type of every column of the input
        (`ddviz.compute.tasks.columns.run_schema`).
    dtypes : dict of str to str
        The input's type of each column to convert, as text.
    sources : list of str
        Source files with parts to write.
    parts : list of dict of str to str
        Per source file, the part to write for each column.
    generated : dict of str to str
        The kind of each added column to convert (`ddviz.shared.generated`):
        its parts hold a value made from the source file, not read from it.
    """

    KIND: ClassVar[str] = "convert"
    schema: str
    dtypes: dict[str, str]
    sources: list[str]
    parts: list[dict[str, str]]
    generated: dict[str, str]


@dataclass(frozen=True)
class JoinTask:
    """Find each row's row of the joined table by keys, and write the map and ``_joined`` (`ddviz.compute.join`).

    Parameters
    ----------
    keys : list of dict of str to str
        The pairs of keys, ``{"left", "right"}``: a column of the input and
        one of the joined table.
    left : dict of str to list of str
        The parts of the input's keys in its column cache.
    right : dict of str to list of str
        The parts of the joined table's keys in its column cache.
    rows : list of int
        The rows of each file of the input.
    right_rows : int
        The rows of the joined table.
    maps : list of str
        Per file of the input, the part of the map to write
        (`ddviz.shared.joined.MAP_COLUMN`).
    indicator : str
        The name of ``_joined`` in the input (`ddviz.shared.joined.joined_names`).
    indicators : list of str
        Per file of the input, the part of ``_joined`` to write.
    """

    KIND: ClassVar[str] = "join"
    keys: list[dict[str, str]]
    left: dict[str, list[str]]
    right: dict[str, list[str]]
    rows: list[int]
    right_rows: int
    maps: list[str]
    indicator: str
    indicators: list[str]


@dataclass(frozen=True)
class JoinConvertTask:
    """Write the parts of columns a join added, from the joined table's parts (`ddviz.compute.join`).

    Parameters
    ----------
    columns : dict of str to str
        Per column to write, the column of the joined table it holds.
    right : dict of str to list of str
        The parts of those columns of the joined table in its column cache.
    rows : list of int
        The rows of each file of the input.
    files : list of int
        The files of the input with parts to write, by position.
    maps : list of str
        For a join by keys, the part of the map of each of `files`; empty
        for a join by rows, where a file's part holds the joined table's
        rows from the rows of the files before.
    parts : list of dict of str to str
        Per file of `files`, the part to write for each column.
    """

    KIND: ClassVar[str] = "join_convert"
    columns: dict[str, str]
    right: dict[str, list[str]]
    rows: list[int]
    files: list[int]
    maps: list[str]
    parts: list[dict[str, str]]


@dataclass(frozen=True)
class JoinEqualTask:
    """Find the columns of the joined table named like the input's that hold the same values in the rows joined (`ddviz.compute.join`).

    Parameters
    ----------
    pairs : list of dict of str to str
        The columns to compare, ``{"left", "right"}``: a column of the input
        and the one of the joined table named alike.
    left : dict of str to list of str
        The parts of the input's columns in its column cache, one per file.
    right : dict of str to list of str
        The parts of the joined table's columns in its column cache.
    rows : list of int
        The rows of each file of the input.
    maps : list of str
        For a join by keys, the part of the map of each file of the input
        (`ddviz.shared.joined.MAP_COLUMN`); empty for a join by rows, where
        a file holds the joined table's rows from the rows of the files
        before.
    """

    KIND: ClassVar[str] = "join_equal"
    pairs: list[dict[str, str]]
    left: dict[str, list[str]]
    right: dict[str, list[str]]
    rows: list[int]
    maps: list[str]


@dataclass(frozen=True)
class PlotTask:
    """Aggregate a plot and write its images and hover files.

    Parameters
    ----------
    spec : ScatterSpec
        What to plot.
    """

    KIND: ClassVar[str] = "plot"
    spec: ScatterSpec


@dataclass(frozen=True)
class SelectionTask:
    """Aggregate the selected rows of a drawn result as a layer.

    Parameters
    ----------
    spec : ScatterSpec
        The result's spec with its view and a selection.
    """

    KIND: ClassVar[str] = "selection"
    spec: ScatterSpec


@dataclass(frozen=True)
class TableTask:
    """Read a page of the selected rows.

    Parameters
    ----------
    spec : ScatterSpec
        A spec with a selection.
    offset, limit : int
        The page: the selected rows from `offset`, at most `limit`.
    columns : list of str
        The columns of the page, in order.
    parts : dict of str to list of str
        The parts of the columns in the column cache; the other columns are
        read from the source files.
    source : SourceFiles
        The source files.
    """

    KIND: ClassVar[str] = "table"
    spec: ScatterSpec
    offset: int
    limit: int
    columns: list[str]
    parts: dict[str, list[str]]
    source: SourceFiles


@dataclass(frozen=True)
class SummaryTask:
    """Summarize a column for the filter pane (`ddviz.compute.summary`).

    Parameters
    ----------
    parts : list of str
        The parts of the column in the column cache.
    column : str
        The column.
    """

    KIND: ClassVar[str] = "summary"
    parts: list[str]
    column: str


@dataclass(frozen=True)
class LevelIndexTask:
    """Write the index of a column's levels for the filter card's search (`ddviz.compute.levelindex`).

    Parameters
    ----------
    parts : list of str
        The parts of the column in the column cache.
    column : str
        The column.
    index : str
        Where the index goes.
    """

    KIND: ClassVar[str] = "level_index"
    parts: list[str]
    column: str
    index: str


@dataclass(frozen=True)
class LevelSearchTask:
    """Search the index of a column's levels (`ddviz.compute.levelindex.search_index`).

    Parameters
    ----------
    index : str
        The index.
    query : str
        The search input.
    order : str
        ``"name"`` or ``"count"``.
    """

    KIND: ClassVar[str] = "level_search"
    index: str
    query: str
    order: str


@dataclass(frozen=True)
class PlotDataTask:
    """Write the rows of a plot's result as a file to save (`ddviz.compute.tasks.plotdata`).

    Parameters
    ----------
    result : str
        The plot task's output directory; for ``"selected"`` rows, the
        selection layer's, which the worker does not read.
    file_format : str
        ``"csv"`` or ``"parquet"``.
    rows : str
        ``"drawn"``: the rows the plot draws; ``"filtered"``: the rows the
        local filter keeps; ``"selected"``: the rows the selection of
        `selection` picks (`ddviz.compute.selection.selection_filter`).
    columns : list of str
        The columns of the file, in order, after the row index.
    parts : dict of str to list of str
        The parts of the columns in the column cache; the other columns are
        read from the source files.
    source : SourceFiles
        The source files.
    export : str
        Token the page gave, carried by the progress messages.
    selection : ScatterSpec or None
        For ``"selected"`` rows, the selection layer's spec with its
        selection, as the server had it when asked; None otherwise.
    """

    KIND: ClassVar[str] = "plot_data"
    result: str
    file_format: str
    rows: str
    columns: list[str]
    parts: dict[str, list[str]]
    source: SourceFiles
    export: str
    selection: ScatterSpec | None = None


Task = (
    SchemaTask
    | NonnullTask
    | ConvertTask
    | JoinTask
    | JoinConvertTask
    | JoinEqualTask
    | PlotTask
    | SelectionTask
    | TableTask
    | SummaryTask
    | LevelIndexTask
    | LevelSearchTask
    | PlotDataTask
)
TASKS: dict[str, type[Task]] = {
    t.KIND: t
    for t in (
        SchemaTask,
        NonnullTask,
        ConvertTask,
        JoinTask,
        JoinConvertTask,
        JoinEqualTask,
        PlotTask,
        SelectionTask,
        TableTask,
        SummaryTask,
        LevelIndexTask,
        LevelSearchTask,
        PlotDataTask,
    )
}


def task_to_dict(task: Task) -> dict:
    """Return a task as the JSON-ready dict a worker reads.

    Parameters
    ----------
    task : Task
        The task.

    Returns
    -------
    dict
        Its fields and its ``"kind"``.
    """
    return {"kind": task.KIND, **asdict(task)}


def task_from_dict(data: dict) -> Task:
    """Build a task from a dict like `task_to_dict`'s; other keys (``"out"``) are left out.

    Parameters
    ----------
    data : dict
        The task as JSON.

    Returns
    -------
    Task
        The task.

    Raises
    ------
    ValueError
        For an unknown kind.
    """
    cls = TASKS.get(data["kind"])
    if cls is None:
        raise ValueError(f"unknown task kind: {data['kind']}")
    values = {f.name: data[f.name] for f in fields(cls)}
    for key in ("spec", "selection"):
        if values.get(key) is not None:
            values[key] = ScatterSpec.from_dict(values[key])
    if "source" in values:
        values["source"] = SourceFiles.from_dict(values["source"])
    return cls(**values)
