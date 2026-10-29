"""Runs a task the UI server described: picks its function by kind and makes its directory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ddviz.compute.convert import convert_columns
from ddviz.compute.progress import Emit
from ddviz.compute.tasks.columns import run_nonnull, run_schema, run_summary
from ddviz.compute.tasks.plot import run_plot, run_selection
from ddviz.compute.tasks.table import run_table
from ddviz.shared.scatter import ScatterSpec

# The function of each kind of task, called with the task, its directory and
# the emitter of its progress messages.
KINDS: dict[str, Callable[[dict, Path, Emit], None]] = {
    "schema": lambda t, out, emit: run_schema(t["path"], out, emit),
    "nonnull": lambda t, out, emit: run_nonnull(t["path"], t["names"], out, emit),
    "convert": lambda t, out, emit: convert_columns(t["path"], t["files"], emit),
    "plot": lambda t, out, emit: run_plot(ScatterSpec.from_dict(t["spec"]), out, emit),
    "selection": lambda t, out, emit: run_selection(
        ScatterSpec.from_dict(t["spec"]), out, emit
    ),
    "table": lambda t, out, emit: run_table(
        ScatterSpec.from_dict(t["spec"]), t["offset"], t["limit"], t["files"], out, emit
    ),
    "summary": lambda t, out, emit: run_summary(t["file"], t["column"], out, emit),
}


def run_task(task: dict, emit: Emit) -> None:
    """Run a task described by the UI server.

    Parameters
    ----------
    task : dict
        ``{"kind": "schema" | "nonnull" | "convert" | "plot" | "selection" |
        "table" | "summary",
        "out": directory, ...}``; ``"path"`` for a schema task, ``"path"``
        and ``"names"`` (the columns in schema order) for a nonnull task, ``"path"``
        and ``"files"`` (the file to write for each column) for a convert
        task, ``"spec"`` for a plot or selection task, and ``"spec"``,
        ``"offset"``, ``"limit"`` and ``"files"`` (the file to read each
        column from) for a table task, and ``"file"`` and ``"column"`` for
        a summary task.
    emit : callable
        Receives progress messages.

    Raises
    ------
    ValueError
        For an unknown kind.
    """
    out = Path(task["out"])
    out.mkdir(parents=True, exist_ok=True)
    run = KINDS.get(task["kind"])
    if run is None:
        raise ValueError(f"unknown task kind: {task['kind']}")
    run(task, out, emit)
