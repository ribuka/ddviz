"""Tests of the tasks the UI server hands to workers."""

from __future__ import annotations

import json

import pytest

from ddviz.shared.scatter import ScatterSpec
from ddviz.shared.tasks import (
    TASKS,
    ConvertTask,
    NonnullTask,
    PlotDataTask,
    PlotTask,
    SchemaTask,
    SelectionTask,
    SourceFiles,
    SummaryTask,
    TableTask,
    Task,
    task_from_dict,
    task_to_dict,
)


def _every_task(spec: ScatterSpec) -> list[Task]:
    """Return one task of each kind."""
    return [
        SchemaTask(["a.parquet", "b.parquet"]),
        NonnullTask(["a.parquet", "b.parquet"], ["x", "y"]),
        ConvertTask(
            "schema.parquet",
            {"x": "Float64"},
            ["a.parquet"],
            [{"x": "a/x.parquet"}],
        ),
        PlotTask(spec),
        SelectionTask(spec),
        TableTask(
            spec,
            100,
            50,
            ["x", "y"],
            {"x": ["a/x.parquet", "b/x.parquet"]},
            SourceFiles(
                ["a.parquet", "b.parquet"], [3, 4], "schema.parquet", {"y": "Int64"}
            ),
        ),
        SummaryTask(["a/x.parquet", "b/x.parquet"], "x"),
        PlotDataTask("tasks/1", "csv"),
    ]


def test_every_kind_has_a_task(scatter_spec: ScatterSpec) -> None:
    """Each kind names one task type, and every type is listed."""
    assert sorted(TASKS) == sorted(t.KIND for t in _every_task(scatter_spec))


def test_tasks_survive_json(scatter_spec: ScatterSpec) -> None:
    """A task sent as JSON with the pool's ``"out"`` comes back the same."""
    for task in _every_task(scatter_spec):
        data = json.loads(json.dumps(task_to_dict(task)))
        assert data["kind"] == task.KIND
        assert task_from_dict({**data, "out": "tasks/1"}) == task


def test_unknown_kind() -> None:
    """An unknown kind is refused."""
    with pytest.raises(ValueError, match="unknown task kind"):
        task_from_dict({"kind": "nope"})
