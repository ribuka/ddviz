"""Tests of the workers' Job Object listing its processes."""

from __future__ import annotations

import subprocess
import sys

import pytest

from ddviz.workers.jobs import WorkerJob

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

# Waits until its stdin closes.
_WAITING = "import sys; sys.stdin.read()"


def _start(job: WorkerJob) -> subprocess.Popen:
    """Start a waiting process inside the job."""
    process = subprocess.Popen(
        [sys.executable, "-c", _WAITING],
        stdin=subprocess.PIPE,
        creationflags=job.creationflags,
    )
    job.adopt(process.pid)
    return process


@windows
def test_the_job_lists_all_its_processes_past_the_first_buffer() -> None:
    """More processes than the first buffer holds are all listed, children of the launcher too."""
    job = WorkerJob(None)
    processes = [_start(job) for _ in range(20)]
    try:
        pids = job.process_ids()
        assert pids is not None
        assert {p.pid for p in processes} <= set(pids)
        assert len(pids) == len(set(pids))
    finally:
        job.close()
        for process in processes:
            process.wait(30)


@windows
def test_an_ended_process_leaves_the_list() -> None:
    """A process that has ended is no longer listed."""
    job = WorkerJob(None)
    try:
        process = _start(job)
        assert process.pid in job.process_ids()
        process.communicate(b"", timeout=30)
        assert process.pid not in job.process_ids()
    finally:
        job.close()


def test_a_closed_job_lists_nothing() -> None:
    """Once closed, or off Windows, the job has no list."""
    job = WorkerJob(None)
    job.close()
    assert job.process_ids() is None
