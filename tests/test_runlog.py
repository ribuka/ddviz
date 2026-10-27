"""Tests of the log file and the marker of an abnormal end."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import pytest

from ddviz.runlog import RunLog


@pytest.fixture
def run_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RunLog:
    """Return a RunLog under a temporary directory; the hooks it sets are undone."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(logging.getLogger(), "level", logging.getLogger().level)
    return RunLog(tmp_path)


def test_a_run_that_ends_normally_leaves_no_marker(run_log: RunLog) -> None:
    """The marker is placed while running and removed by a normal end."""
    assert run_log.start() is False
    assert run_log.marker.exists()
    run_log.finish()
    run_log.close()
    assert not run_log.marker.exists()
    assert RunLog(run_log.marker.parent).marker.exists() is False


def test_the_next_run_sees_an_abnormal_end(run_log: RunLog) -> None:
    """A run that never finishes leaves its marker for the next run to find."""
    run_log.start()
    run_log.close()
    assert run_log.start() is True
    run_log.close()
    assert "did not end normally" in run_log.path.read_text(encoding="utf-8")


def test_uncaught_exceptions_go_to_the_log(run_log: RunLog) -> None:
    """Exceptions escaping a thread are written to the log file."""
    run_log.start()

    def fail() -> None:
        raise ValueError("boom")

    thread = threading.Thread(target=fail, name="failing")
    thread.start()
    thread.join()
    run_log.close()
    text = run_log.path.read_text(encoding="utf-8")
    assert "uncaught exception in thread failing" in text
    assert "ValueError: boom" in text
