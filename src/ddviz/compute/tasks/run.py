"""Runs a task the UI server described: makes its directory and calls its function."""

from __future__ import annotations

from pathlib import Path

from ddviz.compute.convert import convert_columns
from ddviz.compute.progress import Emit
from ddviz.compute.tasks.columns import run_nonnull, run_schema, run_summary
from ddviz.compute.tasks.plot import run_plot, run_selection
from ddviz.compute.tasks.plotdata import run_plot_data
from ddviz.compute.tasks.table import run_table
from ddviz.shared.tasks import (
    ConvertTask,
    NonnullTask,
    PlotDataTask,
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
    task = task_from_dict(data)
    match task:
        case SchemaTask(paths=paths):
            run_schema(paths, out, emit)
        case NonnullTask(paths=paths, names=names):
            run_nonnull(paths, names, out, emit)
        case ConvertTask():
            convert_columns(task, emit)
        case PlotTask(spec=spec):
            run_plot(spec, out, emit)
        case SelectionTask(spec=spec):
            run_selection(spec, out, emit)
        case TableTask():
            run_table(task, out, emit)
        case SummaryTask(parts=parts, column=column):
            run_summary(parts, column, out, emit)
        case PlotDataTask(result=result, file_format=file_format):
            run_plot_data(Path(result), file_format, out, emit)
