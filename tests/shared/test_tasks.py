"""Tests of the tasks the UI server hands to workers."""

from __future__ import annotations

import json

import pytest

from ddviz.shared.scatter import ScatterSpec
from ddviz.shared.tasks import (
    TASKS,
    ConvertTask,
    JoinConvertTask,
    JoinedFiles,
    JoinEqualTask,
    JoinRowsTask,
    JoinSummaryTask,
    JoinTask,
    LevelIndexTask,
    LevelSearchTask,
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
        NonnullTask(["a.parquet", "b.parquet"], ["x", "y"], []),
        ConvertTask(
            "schema.parquet",
            {"x": "Float64"},
            ["a.parquet"],
            [{"x": "a/x.parquet", "source": "a/s.parquet"}],
            {"source": "source"},
        ),
        JoinTask(
            [{"left": "k", "right": "lot"}],
            {"k": ["a/k.parquet", "b/k.parquet"]},
            {"lot": ["r/lot.parquet"]},
            [3, 4],
            5,
            ["a/m.parquet", "b/m.parquet"],
            "_joined",
            ["a/j.parquet", "b/j.parquet"],
        ),
        JoinConvertTask(
            {"v_joined": "v"},
            {"v": ["r/v.parquet"]},
            [3, 4],
            [1],
            ["b/m.parquet"],
            [{"v_joined": "b/v.parquet"}],
        ),
        JoinEqualTask(
            [{"left": "v", "right": "v"}],
            {"v": ["a/v.parquet", "b/v.parquet"]},
            {"v": ["r/v.parquet"]},
            [3, 4],
            ["a/m.parquet", "b/m.parquet"],
        ),
        JoinSummaryTask(
            [{"left": "k", "right": "id"}],
            {"k": ["a/k.parquet", "b/k.parquet"]},
            {"id": ["r/id.parquet"]},
            ["a/m.parquet", "b/m.parquet"],
            7,
            5,
        ),
        JoinRowsTask(
            "parquet",
            "key",
            [{"left": "k", "right": "id"}],
            ["a/m.parquet", "b/m.parquet"],
            ["k", "x", "source", "filename"],
            {"source": "source", "filename": "filename"},
            {"k": ["a/k.parquet", "b/k.parquet"]},
            SourceFiles(["a.parquet", "b.parquet"], [3, 4], "a/schema.parquet", {"x": "Float64"}, {"source": "source"}),
            ["id", "v"],
            {},
            {"id": ["r/id.parquet"]},
            SourceFiles(["r.parquet"], [5], "r/schema.parquet", {"v": "Float64"}, {}),
            "token",
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
                ["a.parquet", "b.parquet"],
                [3, 4],
                "schema.parquet",
                {"y": "Int64", "filename": "String"},
                {"filename": "filename"},
            ),
        ),
        SummaryTask(["a/x.parquet", "b/x.parquet"], "x"),
        LevelIndexTask(["a/g.parquet", "b/g.parquet"], "g", "level-index/1.parquet"),
        LevelSearchTask("level-index/1.parquet", "id 7", "count"),
        PlotDataTask(
            "tasks/1",
            "csv",
            "drawn",
            ["x", "y"],
            {"x": ["a/x.parquet"]},
            SourceFiles(
                ["a.parquet"],
                [3],
                "schema.parquet",
                {"y": "Int64"},
                {},
                JoinedFiles(
                    {"_joined": None, "v": "v"},
                    ["a/m.parquet"],
                    {},
                    SourceFiles(["r.parquet"], [5], "r/schema.parquet", {"v": "Float64"}, {}),
                ),
            ),
            "token",
        ),
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
