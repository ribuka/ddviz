"""The dry run or the join running now, if any, which the page may cancel (Issue #379).

A dry run (``POST /api/join/check``) and a join (``POST /api/join``) run one
at a time, under the lock of the conversions (`ddviz.server.source.Source`),
as several tasks in the plot pool one after another: the conversions of the
keys, the join task, the summary or the comparison of the columns named
alike. ``POST /api/join/cancel`` marks the one running cancelled: a task
given to the pool is killed (plots are refused meanwhile, so the pool runs
no other task), and no further task is given. The tasks it gave go through
`Joining.run`.
"""

from __future__ import annotations

from fastapi import HTTPException

from ddviz.server.broker import Pool, TaskBroker, TaskEnd
from ddviz.shared.tasks import Task


class Joining:
    """Whether a dry run or a join runs, whether it was cancelled, and whether a task of it is in the pool."""

    def __init__(self) -> None:
        self.running = False
        self.cancelled = False
        self.submitted = False

    def begin(self) -> None:
        """Start a dry run or a join."""
        self.running = True
        self.cancelled = False
        self.submitted = False

    def end(self) -> None:
        """End it, whatever its end."""
        self.running = False
        self.cancelled = False
        self.submitted = False

    def cancel(self) -> bool:
        """Mark the one running cancelled; return whether a task of it is in the pool to kill.

        Returns
        -------
        bool
            True when its task runs in the pool, so that the caller kills
            the pool's task; False between its tasks (it stops before the
            next) or when none runs.
        """
        if not self.running:
            return False
        self.cancelled = True
        return self.submitted

    async def run(self, broker: TaskBroker, task: Task, pool: Pool) -> TaskEnd:
        """Run a task of the dry run or the join; any other task as `broker` runs it.

        Parameters
        ----------
        broker : TaskBroker
            Runs the task.
        task : Task
            The task.
        pool : str
            The pool to run it in.

        Returns
        -------
        TaskEnd
            Its end, when it was not cancelled.

        Raises
        ------
        fastapi.HTTPException
            409 ``cancelled`` when the one running was cancelled before the
            task was given, or its task was killed for it; the output of a
            task killed is removed.
        """
        if not self.running:
            return await broker.run(task, pool)
        if self.cancelled:
            raise HTTPException(409, "cancelled")
        self.submitted = True
        try:
            end = await broker.run(task, pool)
        finally:
            self.submitted = False
        if self.cancelled and end.type == "cancelled":
            end.discard()
            raise HTTPException(409, "cancelled")
        return end
