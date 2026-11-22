"""Runs a task the UI server described: makes its directory and calls its function."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ddviz.compute.convert import convert_columns
from ddviz.compute.join import run_join, run_join_convert, run_join_equal
from ddviz.compute.joinsummary import run_join_summary
from ddviz.compute.progress import Emit
from ddviz.compute.tasks.columns import run_nonnull, run_schema, run_summary
from ddviz.compute.tasks.levels import run_level_index, run_level_search
from ddviz.compute.tasks.plot import run_plot, run_selection
from ddviz.compute.tasks.plotdata import run_plot_data
from ddviz.compute.tasks.table import run_table
from ddviz.shared.tasks import (
    ConvertTask,
    JoinConvertTask,
    JoinEqualTask,
    JoinSummaryTask,
    JoinTask,
    LevelIndexTask,
    LevelSearchTask,
    NonnullTask,
    PlotDataTask,
    PlotTask,
    SchemaTask,
    SelectionTask,
    SummaryTask,
    TableTask,
    Task,
    task_from_dict,
)

# The function of each type of task, called with the task, the directory to
# write into and the receiver of progress messages.
RUNNERS: dict[type, Callable[[Task, Path, Emit], None]] = {
    SchemaTask: lambda t, out, emit: run_schema(t.paths, out, emit),
    NonnullTask: lambda t, out, emit: run_nonnull(t.paths, t.names, t.generated, out, emit),
    ConvertTask: lambda t, _out, emit: convert_columns(t, emit),
    JoinTask: run_join,
    JoinConvertTask: run_join_convert,
    JoinEqualTask: run_join_equal,
    JoinSummaryTask: run_join_summary,
    PlotTask: lambda t, out, emit: run_plot(t.spec, out, emit),
    SelectionTask: lambda t, out, emit: run_selection(t.spec, out, emit),
    TableTask: run_table,
    SummaryTask: lambda t, out, emit: run_summary(t.parts, t.column, out, emit),
    LevelIndexTask: lambda t, out, emit: run_level_index(t.parts, t.column, t.index, out, emit),
    LevelSearchTask: lambda t, out, emit: run_level_search(t.index, t.query, t.order, out, emit),
    PlotDataTask: run_plot_data,
}


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
    RUNNERS[type(task)](task, out, emit)
