"""Tests of the worker pool with real worker processes."""

from __future__ import annotations

import queue
from collections.abc import Iterator
from pathlib import Path

import pytest

from ddviz.jobs import WorkerJob
from ddviz.manifest import read_manifest
from ddviz.runner import WorkerPool
from ddviz.scatter import ScatterSpec

TIMEOUT = 60


@pytest.fixture
def pool(tmp_path: Path) -> Iterator[tuple[WorkerPool, queue.Queue]]:
    """Start a pool whose events land in a queue."""
    events: queue.Queue = queue.Queue()
    job = WorkerJob(None)
    with open(tmp_path / "workers.log", "ab") as log:
        started = WorkerPool(
            tmp_path / "tasks", lambda i, m: events.put((i, m)), job, log
        )
        yield started, events
        started.close()
        job.close()


def _until_end(events: queue.Queue, task_id: int) -> dict:
    """Return the final message of a task, skipping progress."""
    while True:
        got, message = events.get(timeout=TIMEOUT)
        if got == task_id and message["type"] in ("done", "error", "cancelled"):
            return message


def test_schema_task_writes_its_manifest(
    pool: tuple, scatter_path: Path, tmp_path: Path
) -> None:
    """A schema task ends with done and lists the columns."""
    workers, events = pool
    task_id = workers.submit({"kind": "schema", "path": str(scatter_path)})
    assert _until_end(events, task_id) == {"type": "done"}
    columns = read_manifest(tmp_path / "tasks" / str(task_id))["columns"]
    assert [c["name"] for c in columns] == ["x", "y", "label", "color", "facet"]


def test_a_new_task_kills_the_running_one(
    pool: tuple, scatter_spec: ScatterSpec, tmp_path: Path
) -> None:
    """Submitting again cancels the first task and removes its output; the second completes."""
    workers, events = pool
    first = workers.submit({"kind": "plot", "spec": scatter_spec.to_dict()})
    second = workers.submit({"kind": "plot", "spec": scatter_spec.to_dict()})
    assert _until_end(events, first) == {"type": "cancelled"}
    assert not (tmp_path / "tasks" / str(first)).exists()
    assert _until_end(events, second) == {"type": "done"}
    assert read_manifest(tmp_path / "tasks" / str(second))["kind"] == "plot"


def test_cancel_kills_the_running_task(
    pool: tuple, scatter_spec: ScatterSpec, tmp_path: Path
) -> None:
    """Cancelling ends the running task as cancelled and removes its output."""
    workers, events = pool
    task_id = workers.submit({"kind": "plot", "spec": scatter_spec.to_dict()})
    workers.cancel()
    assert _until_end(events, task_id) == {"type": "cancelled"}
    assert not (tmp_path / "tasks" / str(task_id)).exists()
    workers.cancel()


def test_a_failing_task_reports_an_error(pool: tuple, tmp_path: Path) -> None:
    """A task on a missing file ends with an error message."""
    workers, events = pool
    task_id = workers.submit(
        {"kind": "schema", "path": str(tmp_path / "missing.parquet")}
    )
    message = _until_end(events, task_id)
    assert message["type"] == "error"


def test_convert_task_writes_each_column(
    pool: tuple, scatter_path: Path, tmp_path: Path
) -> None:
    """A convert task reports progress per column and leaves one file each."""
    workers, events = pool
    files = {c: str(tmp_path / f"{c}.parquet") for c in ("x", "label")}
    task_id = workers.submit(
        {"kind": "convert", "path": str(scatter_path), "files": files}
    )
    seen = []
    while True:
        got, message = events.get(timeout=TIMEOUT)
        if got != task_id:
            continue
        if message["type"] != "progress":
            break
        seen.append(message["column"])
    assert message == {"type": "done"}
    assert seen == ["x", "label"]
    assert all(Path(f).exists() for f in files.values())
