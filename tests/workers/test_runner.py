"""Tests of the worker pool with real worker processes."""

from __future__ import annotations

import queue
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from ddviz.shared.manifest import read_manifest
from ddviz.shared.scatter import ScatterSpec
from ddviz.shared.tasks import ConvertTask, task_to_dict
from ddviz.workers.jobs import WorkerJob
from ddviz.workers.runner import WorkerPool, exit_message

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
    task_id = workers.submit({"kind": "schema", "paths": [str(scatter_path)]})
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
        {"kind": "schema", "paths": [str(tmp_path / "missing.parquet")]}
    )
    message = _until_end(events, task_id)
    assert message["type"] == "error"


def test_convert_task_writes_each_column(
    pool: tuple, scatter_path: Path, tmp_path: Path
) -> None:
    """A convert task reports progress per column and leaves one file each."""
    workers, events = pool
    files = {c: str(tmp_path / "parts" / f"{c}.parquet") for c in ("x", "label")}
    task = ConvertTask(
        str(tmp_path / "schema.parquet"),
        {"x": "Float64", "label": "String"},
        [str(scatter_path)],
        [files],
        {},
    )
    task_id = workers.submit(task_to_dict(task))
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


def test_a_new_task_keeps_the_output_of_a_finished_one(
    pool: tuple, scatter_spec: ScatterSpec, tmp_path: Path
) -> None:
    """A task submitted right after another's done, while its worker still exits, leaves that output and gets no cancel."""
    workers, events = pool
    first = workers.submit({"kind": "plot", "spec": scatter_spec.to_dict()})
    assert _until_end(events, first) == {"type": "done"}
    second = workers.submit({"kind": "plot", "spec": scatter_spec.to_dict()})
    assert read_manifest(tmp_path / "tasks" / str(first))["kind"] == "plot"
    assert _until_end(events, second) == {"type": "done"}
    assert (tmp_path / "tasks" / str(first)).exists()


# A worker that takes its task and ends as polars does when an allocation
# fails past the job's memory cap: a fail-fast abort.
_ABORTING_WORKER = (
    'import os, sys; print(\'{"type": "ready"}\', flush=True); '
    "sys.stdin.readline(); os._exit(-1073740791)"
)


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows exit code")
def test_a_worker_aborted_past_the_memory_cap_is_told_in_words(tmp_path: Path) -> None:
    """A worker that ends with 0xC0000409 before its task ends reports the memory cap, not the bare code."""
    events: queue.Queue = queue.Queue()
    job = WorkerJob(16 * 2**30)
    with open(tmp_path / "workers.log", "ab") as log:
        workers = WorkerPool(
            tmp_path / "tasks",
            lambda i, m: events.put((i, m)),
            job,
            log,
            [sys.executable, "-c", _ABORTING_WORKER],
        )
        try:
            task_id = workers.submit({"kind": "schema", "paths": []})
            message = _until_end(events, task_id)
        finally:
            workers.close()
            job.close()
    assert message == {"type": "error", "message": exit_message(0xC0000409, 16 * 2**30)}
    assert "メモリの上限（16.0GB" in message["message"]


def test_exit_messages_name_the_cause_they_can() -> None:
    """A fail-fast abort names the memory cap; other codes show themselves, in hex when large."""
    assert exit_message(0xC0000409, 15 * 2**30 + 2**29) == (
        "処理のプロセスが異常終了した（終了コード 0xC0000409）。"
        "メモリの上限（15.5GB。物理メモリの半分）を超えたとみられる。"
        "行数の多いデータでは、集約がメモリの上限を超えることがある"
    )
    assert "メモリが足りなかったとみられる" in exit_message(0xC0000409, None)
    assert exit_message(1, None) == "処理のプロセスが異常終了した（終了コード 1）"
    assert exit_message(0xC0000005, None) == (
        "処理のプロセスが異常終了した（終了コード 0xC0000005）"
    )
