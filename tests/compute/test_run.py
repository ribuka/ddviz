"""Tests of running a task the UI server described."""

from __future__ import annotations

from pathlib import Path

import pytest

from ddviz.compute.tasks.run import run_task
from ddviz.shared.manifest import read_manifest
from ddviz.shared.tasks import SchemaTask, task_to_dict


def test_run_task_makes_the_directory_and_runs_the_task(
    tmp_path: Path, scatter_path: Path
) -> None:
    """A schema task writes its manifest into a directory it makes."""
    out = tmp_path / "tasks" / "1"
    run_task({**task_to_dict(SchemaTask([str(scatter_path)])), "out": str(out)}, print)
    names = [c["name"] for c in read_manifest(out)["columns"]]
    assert names == ["x", "y", "label", "color", "facet"]


def test_run_task_refuses_an_unknown_kind(tmp_path: Path) -> None:
    """An unknown kind is an error."""
    with pytest.raises(ValueError, match="unknown task kind"):
        run_task({"kind": "nope", "out": str(tmp_path / "out")}, print)
