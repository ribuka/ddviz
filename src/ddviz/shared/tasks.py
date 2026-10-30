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
    """

    paths: list[str]
    rows: list[int]
    schema: str
    dtypes: dict[str, str]


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
    """

    KIND: ClassVar[str] = "nonnull"
    paths: list[str]
    names: list[str]


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
    """

    KIND: ClassVar[str] = "convert"
    schema: str
    dtypes: dict[str, str]
    sources: list[str]
    parts: list[dict[str, str]]


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


Task = (
    SchemaTask
    | NonnullTask
    | ConvertTask
    | PlotTask
    | SelectionTask
    | TableTask
    | SummaryTask
)
TASKS: dict[str, type[Task]] = {
    t.KIND: t
    for t in (
        SchemaTask,
        NonnullTask,
        ConvertTask,
        PlotTask,
        SelectionTask,
        TableTask,
        SummaryTask,
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
    if "spec" in values:
        values["spec"] = ScatterSpec.from_dict(values["spec"])
    if "source" in values:
        values["source"] = SourceFiles(**values["source"])
    return cls(**values)
