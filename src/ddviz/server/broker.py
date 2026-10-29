"""Runs tasks in the server's worker pools and awaits their ends from the event loop.

The server has three pools, so that one kind of task never kills another:
``"plot"`` (schema, conversion, plots and selections), ``"table"`` (pages of
the selection table) and ``"summary"`` (the filter pane's summaries and the
share of non-null values). Submitting a task to a pool kills the task
running in it.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal

from ddviz.shared.manifest import read_manifest
from ddviz.workers.jobs import WorkerJob
from ddviz.workers.runner import WorkerPool

Pool = Literal["plot", "table", "summary"]
# Directory of each pool's task outputs under the server's root.
DIRS: dict[Pool, str] = {"plot": "tasks", "table": "table", "summary": "summary"}
ENDS = ("done", "error", "cancelled")


@dataclass(frozen=True)
class TaskEnd:
    """The last message of a task and where it wrote its result.

    Parameters
    ----------
    task_id : int
        Id of the task in its pool.
    out : pathlib.Path
        Directory the task wrote into.
    message : dict
        ``{"type": "done" | "error" | "cancelled", ...}``.
    """

    task_id: int
    out: Path
    message: dict

    @property
    def type(self) -> str:
        """Return ``"done"``, ``"error"`` or ``"cancelled"``."""
        return self.message["type"]

    @property
    def error(self) -> str:
        """Return the error message, or the type when there is none."""
        return self.message.get("message", self.type)

    def discard(self) -> None:
        """Remove the task's directory."""
        shutil.rmtree(self.out, ignore_errors=True)

    def take(self) -> dict:
        """Read the task's manifest and remove its directory.

        Returns
        -------
        dict
            The manifest.
        """
        manifest = read_manifest(self.out)
        self.discard()
        return manifest


class TaskBroker:
    """Submits tasks to the worker pools and resolves each request waiting on one.

    Parameters
    ----------
    root : pathlib.Path
        Directory under which each pool writes its task outputs (`DIRS`).
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pools: dict[Pool, WorkerPool] = {}
        self._waiting: dict[tuple[Pool, int], asyncio.Future] = {}
        # Ends that came before their request waited on them.
        self._ended: dict[tuple[Pool, int], dict] = {}
        self._listeners: set[asyncio.Queue] = set()

    def start(
        self,
        job: WorkerJob,
        log: IO[bytes],
        make_pool: Callable[..., WorkerPool] = WorkerPool,
    ) -> None:
        """Start the pools; call from the event loop.

        Parameters
        ----------
        job : WorkerJob
            Job the workers join.
        log : file object
            Where the workers' stderr goes.
        make_pool : callable, optional
            Builds a pool like `WorkerPool`; replaced in tests.
        """
        self._loop = asyncio.get_running_loop()
        self._pools = {
            pool: make_pool(self._root / name, self._on_event(pool), job, log)
            for pool, name in DIRS.items()
        }

    def close(self) -> None:
        """Kill every worker of the pools."""
        for workers in self._pools.values():
            workers.close()

    def _on_event(self, pool: Pool) -> Callable[[int, dict], None]:
        """Return the handler of a pool's worker messages (called from reader threads)."""

        def handle(task_id: int, message: dict) -> None:
            try:
                self._loop.call_soon_threadsafe(self._deliver, pool, task_id, message)
            except RuntimeError:
                # The loop closed: the server stopped and killed the worker.
                pass

        return handle

    def _deliver(self, pool: Pool, task_id: int, message: dict) -> None:
        """Resolve the request waiting on a task and notify the progress listeners of plots."""
        if pool == "plot":
            for queue in self._listeners:
                queue.put_nowait({"task": task_id, **message})
        if message["type"] not in ENDS:
            return
        future = self._waiting.get((pool, task_id))
        if future is None:
            self._ended[pool, task_id] = message
        elif not future.done():
            future.set_result(message)

    async def run(self, task: dict, pool: Pool = "plot") -> TaskEnd:
        """Submit a task to a pool and wait for its end.

        Parameters
        ----------
        task : dict
            The task without ``"out"`` (`ddviz.compute.tasks.run.run_task`).
        pool : {"plot", "table", "summary"}
            The pool to run it in.

        Returns
        -------
        TaskEnd
            The task's end.
        """
        task_id = await asyncio.to_thread(self._pools[pool].submit, task)
        out = self._root / DIRS[pool] / str(task_id)
        # The task may have ended before its future was registered.
        if (pool, task_id) in self._ended:
            return TaskEnd(task_id, out, self._ended.pop((pool, task_id)))
        future = self._loop.create_future()
        self._waiting[pool, task_id] = future
        try:
            return TaskEnd(task_id, out, await future)
        finally:
            self._waiting.pop((pool, task_id), None)

    async def cancel(self, pool: Pool = "plot") -> None:
        """Kill the task running in a pool, if any."""
        await asyncio.to_thread(self._pools[pool].cancel)

    def listen(self) -> asyncio.Queue:
        """Return a queue that receives every message of the plot pool's tasks."""
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def unlisten(self, queue: asyncio.Queue) -> None:
        """Stop sending messages to a queue from `listen`."""
        self._listeners.discard(queue)
