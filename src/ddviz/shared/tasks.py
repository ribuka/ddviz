"""The tasks the UI server hands to workers, one type per kind.

A task goes to the worker as JSON (`task_to_dict`): its fields and its
``"kind"``; the worker pool adds ``"out"``, the directory to write into.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import ClassVar

from ddviz.shared.scatter import ScatterSpec


@dataclass(frozen=True)
class SchemaTask:
    """Read the column names and types of a Parquet file.

    Parameters
    ----------
    path : str
        The Parquet file.
    """

    KIND: ClassVar[str] = "schema"
    path: str


@dataclass(frozen=True)
class NonnullTask:
    """Measure the share of non-null values of each column (`ddviz.compute.nonnull`).

    Parameters
    ----------
    path : str
        The Parquet file.
    names : list of str
        Its columns, in schema order.
    """

    KIND: ClassVar[str] = "nonnull"
    path: str
    names: list[str]


@dataclass(frozen=True)
class ConvertTask:
    """Convert columns of a Parquet file into the column cache (`ddviz.compute.convert`).

    Parameters
    ----------
    path : str
        The Parquet file.
    files : dict of str to str
        The file to write for each column.
    """

    KIND: ClassVar[str] = "convert"
    path: str
    files: dict[str, str]


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
    files : dict of str to str
        The file to read each column of the page from.
    """

    KIND: ClassVar[str] = "table"
    spec: ScatterSpec
    offset: int
    limit: int
    files: dict[str, str]


@dataclass(frozen=True)
class SummaryTask:
    """Summarize a column for the filter pane (`ddviz.compute.summary`).

    Parameters
    ----------
    file : str
        The Parquet file holding the column.
    column : str
        The column.
    """

    KIND: ClassVar[str] = "summary"
    file: str
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
    return cls(**values)
