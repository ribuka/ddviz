"""Tests of the summed working set of processes."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from ddviz.workers import workingset
from ddviz.workers.workingset import total_working_set

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@windows
def test_a_running_process_has_a_working_set() -> None:
    """The running test process takes some physical memory."""
    assert total_working_set([os.getpid()]) > 1024**2


@windows
def test_a_process_that_ended_after_listing_is_left_out() -> None:
    """An ended process counts nothing; the others still count."""
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()  # the Popen holds its handle, so the id stays the ended process's
    assert total_working_set([ended.pid]) == 0
    assert total_working_set([ended.pid, os.getpid()]) > 0


def test_each_id_counts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repeated id is measured once."""
    measured: list[int] = []

    def fake(_: object, pid: int) -> int:
        measured.append(pid)
        return pid * 100

    monkeypatch.setattr(workingset, "_IS_WINDOWS", True)
    monkeypatch.setattr(workingset, "_kernel32", lambda: None)
    monkeypatch.setattr(workingset, "_working_set", fake)
    assert total_working_set([1, 2, 1, 2, 3]) == 600
    assert measured == [1, 2, 3]


def test_ended_processes_drop_out_and_a_failure_makes_it_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ended process is left out; one that may run but cannot be measured makes the sum None."""

    def fake(_: object, pid: int) -> int:
        if pid == 2:
            raise workingset._Gone
        if pid == 3:
            raise PermissionError("denied")
        return 10

    monkeypatch.setattr(workingset, "_IS_WINDOWS", True)
    monkeypatch.setattr(workingset, "_kernel32", lambda: None)
    monkeypatch.setattr(workingset, "_working_set", fake)
    assert total_working_set([1, 2]) == 10
    assert total_working_set([1, 2, 3]) is None


def test_off_windows_it_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off Windows nothing is measured."""
    monkeypatch.setattr(workingset, "_IS_WINDOWS", False)
    assert total_working_set([os.getpid()]) is None
