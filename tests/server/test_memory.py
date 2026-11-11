"""Tests of the memory shown in the footer: what each side sums, and ``GET /api/memory``."""

from __future__ import annotations

import os
import queue
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ddviz.server import memory
from ddviz.server.app import create_app
from ddviz.server.auth import COOKIE
from ddviz.server.memory import MemoryMeter
from ddviz.server.settings import Settings
from ddviz.workers.jobs import WorkerJob
from ddviz.workers.runner import WorkerPool

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
TOKEN = "secret-of-the-run"

# A worker that says it is ready, then holds its task until killed.
_HOLDING_WORKER = (
    "import sys, time\n"
    "print('ready', flush=True)\n"
    "sys.stdin.readline()\n"
    "time.sleep(600)\n"
)


@pytest.fixture
def spied(monkeypatch: pytest.MonkeyPatch) -> list[list[int]]:
    """Record the ids each sum is asked for, and still measure them."""
    asked: list[list[int]] = []
    real = memory.total_working_set

    def spy(pids: list[int]) -> int | None:
        asked.append(list(pids))
        return real(pids)

    monkeypatch.setattr(memory, "total_working_set", spy)
    return asked


@windows
def test_the_backend_sums_this_process_and_waiting_and_working_workers(
    tmp_path: Path, spied: list[list[int]]
) -> None:
    """The backend is this process, the worker running a task and the standby one."""
    job = WorkerJob(None)
    events: queue.Queue = queue.Queue()
    with open(tmp_path / "workers.log", "ab") as log:
        pool = WorkerPool(
            tmp_path / "tasks",
            lambda i, m: events.put((i, m)),
            job,
            log,
            [sys.executable, "-c", _HOLDING_WORKER],
        )
        try:
            pool.submit({"kind": "schema", "paths": []})
            working = pool._running.process.pid
            waiting = pool._standby.pid
            meter = MemoryMeter(None)
            meter.job = job
            backend = meter.backend()
            (asked,) = spied
            assert asked[0] == os.getpid()
            assert {working, waiting} <= set(asked)
            assert backend is not None
            assert backend > 0
        finally:
            pool.close()
            job.close()


def test_each_side_is_unknown_on_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """A side that cannot be listed or measured is None; the other still counts."""

    class _Job:
        def __init__(self, pids: list[int] | None) -> None:
            self.pids = pids

        def process_ids(self) -> list[int] | None:
            return self.pids

    monkeypatch.setattr(
        memory, "total_working_set", lambda pids: None if 666 in pids else 7 * len(pids)
    )
    meter = MemoryMeter(lambda: [10, 11])
    meter.job = _Job([5])
    assert meter.measure() == {"backend_bytes": 14, "frontend_bytes": 14}
    meter.job = _Job(None)  # the job cannot be listed
    assert meter.measure() == {"backend_bytes": None, "frontend_bytes": 14}
    meter.job = _Job([666])  # a worker cannot be measured
    assert meter.measure() == {"backend_bytes": None, "frontend_bytes": 14}
    meter.job = None  # the server is not running
    assert meter.backend() is None

    for pids in (None, [], [666]):  # not ready or gone, nothing listed, unmeasurable
        meter = MemoryMeter(lambda p=pids: p)
        meter.job = _Job([5])
        assert meter.measure() == {"backend_bytes": 7 * 2, "frontend_bytes": None}


@pytest.fixture
def server(tmp_path: Path, scatter_path: Path) -> Iterator[TestClient]:
    """Serve `scatter_path` as in a browser (``--port``): no WebView2 processes."""
    (tmp_path / "run").mkdir()
    app = create_app(
        [str(scatter_path)],
        False,
        tmp_path / "run",
        tmp_path / "cache",
        tmp_path / "history",
        Settings(),
        TOKEN,
    )
    with TestClient(app) as started:
        yield started


def test_in_a_browser_only_the_backend_is_measured(server: TestClient) -> None:
    """``--port`` has no frontend; the backend is known on Windows only; never cached."""
    server.cookies.set(COOKIE, TOKEN)
    response = server.get("/api/memory")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body.keys() == {"backend_bytes", "frontend_bytes"}
    assert body["frontend_bytes"] is None
    if sys.platform == "win32":
        assert isinstance(body["backend_bytes"], int)
        assert body["backend_bytes"] > 0
    else:
        assert body["backend_bytes"] is None


@windows
def test_the_window_hands_over_its_frontend(
    tmp_path: Path, scatter_path: Path
) -> None:
    """The ids the window hands over are measured as the frontend."""
    (tmp_path / "run").mkdir()
    app = create_app(
        [str(scatter_path)],
        False,
        tmp_path / "run",
        tmp_path / "cache",
        tmp_path / "history",
        Settings(),
        TOKEN,
        lambda: [os.getpid()],
    )
    with TestClient(app) as client:
        client.cookies.set(COOKIE, TOKEN)
        body = client.get("/api/memory").json()
    assert body["frontend_bytes"] > 0
    assert body["backend_bytes"] >= body["frontend_bytes"]


def test_without_the_token_it_is_refused(server: TestClient) -> None:
    """The memory needs the token like every API."""
    assert server.get("/api/memory").status_code == 403
