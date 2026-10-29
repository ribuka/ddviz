"""Tests of the task broker with fake pools that end their tasks at once."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path

from ddviz.server.broker import TaskBroker


class _FakePool:
    """A pool that ends each task from another thread, before or after `submit` returns."""

    def __init__(
        self, root: Path, on_event: Callable[[int, dict], None], *_: object
    ) -> None:
        self.root = root
        self.on_event = on_event
        self.next_id = 0
        self.cancelled = 0
        self.closed = False

    def submit(self, task: dict) -> int:
        self.next_id += 1
        task_id = self.next_id
        messages = [{"type": "progress", "stage": "x"}, task["end"]]
        if task.get("early"):
            for m in messages:
                self.on_event(task_id, m)
        else:
            threading.Timer(
                0.05, lambda: [self.on_event(task_id, m) for m in messages]
            ).start()
        return task_id

    def cancel(self) -> None:
        self.cancelled += 1

    def close(self) -> None:
        self.closed = True


def _started(tmp_path: Path) -> tuple[TaskBroker, dict[str, _FakePool]]:
    """Return a broker started on fake pools, and the pools by name."""
    pools: dict[str, _FakePool] = {}

    def make(root: Path, on_event: Callable, *rest: object) -> _FakePool:
        pools[root.name] = _FakePool(root, on_event, *rest)
        return pools[root.name]

    broker = TaskBroker(tmp_path)
    broker.start(None, None, make)
    return broker, pools


def test_run_waits_for_the_end(tmp_path: Path) -> None:
    """A task's end reaches its request, whether it comes before or after the wait."""

    async def main() -> None:
        broker, pools = _started(tmp_path)
        late = await broker.run({"end": {"type": "done"}})
        early = await broker.run({"end": {"type": "done"}, "early": True})
        failed = await broker.run(
            {"end": {"type": "error", "message": "boom"}}, "table"
        )
        assert (late.task_id, late.type) == (1, "done")
        assert late.out == tmp_path / "tasks" / "1"
        assert (early.task_id, early.type) == (2, "done")
        assert (failed.type, failed.error) == ("error", "boom")
        assert failed.out == tmp_path / "table" / "1"
        await broker.cancel("summary")
        assert pools["summary"].cancelled == 1
        broker.close()
        assert all(p.closed for p in pools.values())

    asyncio.run(main())


def test_listeners_get_the_plot_pool_messages(tmp_path: Path) -> None:
    """Progress listeners get every message of the plot pool and none of the others."""

    async def main() -> None:
        broker, _ = _started(tmp_path)
        queue = broker.listen()
        await broker.run({"end": {"type": "done"}}, "table")
        await broker.run({"end": {"type": "done"}})
        got = [queue.get_nowait() for _ in range(queue.qsize())]
        assert got == [
            {"task": 1, "type": "progress", "stage": "x"},
            {"task": 1, "type": "done"},
        ]
        broker.unlisten(queue)
        await broker.run({"end": {"type": "done"}})
        assert queue.empty()

    asyncio.run(main())


def test_events_after_the_loop_closed_are_dropped(tmp_path: Path) -> None:
    """A worker killed at shutdown reports into a closed loop without raising."""

    async def main() -> Callable[[int, dict], None]:
        _, pools = _started(tmp_path)
        return pools["tasks"].on_event

    on_event = asyncio.run(main())
    on_event(1, {"type": "error", "message": "worker exited with code 1"})
