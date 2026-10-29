"""Hands tasks to standby worker processes and kills the one a newer task supersedes."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO

from ddviz.workers.jobs import WorkerJob

OnEvent = Callable[[int, dict], None]

_CREATE_NO_WINDOW = 0x08000000


def worker_command() -> list[str]:
    """Return the command that starts a worker: the exe itself when frozen.

    Returns
    -------
    list of str
        The command line.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    return [sys.executable, "-m", "ddviz.workers.worker"]


class _Running:
    """A task handed to a worker process."""

    def __init__(self, task_id: int, out: Path, process: subprocess.Popen) -> None:
        self.task_id = task_id
        self.out = out
        self.process = process
        self.cancelled = False


class WorkerPool:
    """Keeps one standby worker and runs at most one task at a time.

    Submitting a task kills the running one, hands the task to the standby
    worker, which has imported polars already, and starts the next standby.

    Parameters
    ----------
    root : pathlib.Path
        Directory under which each task gets its own output directory.
    on_event : callable
        Called from a reader thread with the task id and each protocol message
        of the task (``progress``, ``done``, ``error``), and with
        ``{"type": "cancelled"}`` when a newer task kills it.
    job : WorkerJob
        Job the workers join.
    log : file object
        Where the workers' stderr goes.
    command : list of str, optional
        Command starting a worker; `worker_command` by default.
    """

    def __init__(
        self,
        root: Path,
        on_event: OnEvent,
        job: WorkerJob,
        log: IO[bytes],
        command: list[str] | None = None,
    ) -> None:
        self._root = root
        self._on_event = on_event
        self._job = job
        self._log = log
        self._command = command or worker_command()
        self._lock = threading.Lock()
        self._next_id = 0
        self._running: _Running | None = None
        self._standby = self._spawn()

    def _spawn(self) -> subprocess.Popen:
        """Start a standby worker inside the job."""
        flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            creationflags=flags | self._job.creationflags,
        )
        try:
            self._job.adopt(process.pid)
        except OSError:
            process.kill()
            raise
        return process

    def _cancel(self, running: _Running) -> None:
        """Kill a running task and remove its output."""
        running.cancelled = True
        running.process.kill()
        running.process.wait()
        shutil.rmtree(running.out, ignore_errors=True)
        self._on_event(running.task_id, {"type": "cancelled"})

    def cancel(self) -> None:
        """Kill the running task, if any; its waiter gets ``{"type": "cancelled"}``."""
        with self._lock:
            if self._running is not None and self._running.process.poll() is None:
                self._cancel(self._running)

    def submit(self, task: dict) -> int:
        """Run a task, killing the running one.

        Parameters
        ----------
        task : dict
            The task without ``"out"``, which the pool fills in.

        Returns
        -------
        int
            The task id; the task writes into ``root / str(id)``.
        """
        with self._lock:
            if self._running is not None and self._running.process.poll() is None:
                self._cancel(self._running)
            self._next_id += 1
            task_id = self._next_id
            out = self._root / str(task_id)
            process, self._standby = self._standby, self._spawn()
            running = _Running(task_id, out, process)
            self._running = running
            process.stdin.write((json.dumps({**task, "out": str(out)}) + "\n").encode())
            process.stdin.flush()
        threading.Thread(target=self._read, args=(running,), daemon=True).start()
        return task_id

    def _read(self, running: _Running) -> None:
        """Forward the protocol messages of a task until its worker exits."""
        finished = False
        for line in running.process.stdout:
            message = json.loads(line)
            if message["type"] == "ready" or running.cancelled:
                continue
            finished |= message["type"] in ("done", "error")
            self._on_event(running.task_id, message)
        code = running.process.wait()
        if not finished and not running.cancelled:
            self._on_event(
                running.task_id,
                {"type": "error", "message": f"worker exited with code {code}"},
            )

    def close(self) -> None:
        """Kill the standby and running workers."""
        with self._lock:
            for process in (self._standby, self._running and self._running.process):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait()
