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
# Exit code of a fail-fast abort on Windows (STATUS_STACK_BUFFER_OVERRUN):
# polars (Rust) ends so when an allocation fails, as past the job's memory cap.
_FAIL_FAST = 0xC0000409


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


def exit_message(code: int, memory_limit: int | None) -> str:
    """Return the error shown for a worker that exited before ending its task.

    Parameters
    ----------
    code : int
        Exit code of the worker.
    memory_limit : int or None
        Cap on the workers' memory in bytes (`WorkerJob.memory_limit`).

    Returns
    -------
    str
        The message, in Japanese.
    """
    if code == _FAIL_FAST:
        cause = (
            f"メモリの上限（{memory_limit / 2**30:.1f}GB。物理メモリの半分）を超えたとみられる"
            if memory_limit
            else "メモリが足りなかったとみられる"
        )
        return (
            f"処理のプロセスが異常終了した（終了コード 0x{code:08X}）。{cause}。"
            "行数の多いデータでは、集約がメモリの上限を超えることがある"
        )
    shown = f"0x{code:08X}" if code >= 0x80000000 else str(code)
    return f"処理のプロセスが異常終了した（終了コード {shown}）"


class _Running:
    """A task handed to a worker process."""

    def __init__(self, task_id: int, out: Path, process: subprocess.Popen) -> None:
        self.task_id = task_id
        self.out = out
        self.process = process
        self.cancelled = False
        # Whether it reported done or error: its worker may still be exiting.
        self.finished = False

    def live(self) -> bool:
        """Return whether the task is still running: not finished, and its worker alive."""
        return not self.finished and self.process.poll() is None


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
            if self._running is not None and self._running.live():
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
            # A finished task keeps its output, though its worker still exits.
            if self._running is not None and self._running.live():
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
        for line in running.process.stdout:
            message = json.loads(line)
            # Under the lock, so that a task is either cancelled or finished.
            with self._lock:
                if message["type"] == "ready" or running.cancelled:
                    continue
                running.finished |= message["type"] in ("done", "error")
                self._on_event(running.task_id, message)
        code = running.process.wait()
        if not running.finished and not running.cancelled:
            self._on_event(
                running.task_id,
                {
                    "type": "error",
                    "message": exit_message(code, self._job.memory_limit),
                },
            )

    def close(self) -> None:
        """Kill the standby and running workers."""
        with self._lock:
            for process in (self._standby, self._running and self._running.process):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait()
