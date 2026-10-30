"""Runs a task the UI server described: makes its directory and calls its function."""

from __future__ import annotations

from pathlib import Path

from ddviz.compute.convert import convert_columns
from ddviz.compute.progress import Emit
from ddviz.compute.tasks.columns import run_nonnull, run_schema, run_summary
from ddviz.compute.tasks.plot import run_plot, run_selection
from ddviz.compute.tasks.table import run_table
from ddviz.shared.tasks import (
    ConvertTask,
    NonnullTask,
    PlotTask,
    SchemaTask,
    SelectionTask,
    SummaryTask,
    TableTask,
    task_from_dict,
)


def run_task(data: dict, emit: Emit) -> None:
    """Run a task described by the UI server.

    Parameters
    ----------
    data : dict
        The task (`ddviz.shared.tasks.task_to_dict`) and ``"out"``, the
        directory to write its result into.
    emit : callable
        Receives progress messages.

    Raises
    ------
    ValueError
        For an unknown kind.
    """
    out = Path(data["out"])
    out.mkdir(parents=True, exist_ok=True)
    match task_from_dict(data):
        case SchemaTask(path=path):
            run_schema(path, out, emit)
        case NonnullTask(path=path, names=names):
            run_nonnull(path, names, out, emit)
        case ConvertTask(path=path, files=files):
            convert_columns(path, files, emit)
        case PlotTask(spec=spec):
            run_plot(spec, out, emit)
        case SelectionTask(spec=spec):
            run_selection(spec, out, emit)
        case TableTask(spec=spec, offset=offset, limit=limit, files=files):
            run_table(spec, offset, limit, files, out, emit)
        case SummaryTask(file=file, column=column):
            run_summary(file, column, out, emit)
