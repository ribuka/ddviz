"""HTTP errors of tasks that did not finish."""

from __future__ import annotations

from fastapi import HTTPException

from ddviz.server.broker import TaskEnd


def ensure_done(end: TaskEnd) -> None:
    """Raise unless a task finished: 409 when a newer task killed it, 500 when it failed.

    Parameters
    ----------
    end : TaskEnd
        The task's end.

    Raises
    ------
    fastapi.HTTPException
        409 for a cancelled task, 500 for a failed one.
    """
    if end.type == "cancelled":
        raise HTTPException(409, "cancelled")
    if end.type == "error":
        raise HTTPException(500, end.error)
