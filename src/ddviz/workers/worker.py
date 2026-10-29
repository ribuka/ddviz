"""Entry point of a worker: a process that runs one task and exits.

Protocol: the worker imports polars, writes ``ready`` to
stdout, then reads one task as a JSON line from stdin. While running it writes
JSON lines to stdout (``progress``, then ``done`` or ``error``). Anything else
printed goes to stderr, so stdout carries the protocol only.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable
from typing import TextIO


def _emitter(out: TextIO) -> Callable[[dict], None]:
    """Return a function that writes one protocol message to `out`."""

    def emit(message: dict) -> None:
        out.write(json.dumps(message) + "\n")
        out.flush()

    return emit


def main() -> int:
    """Run as a standby worker until one task is done.

    Returns
    -------
    int
        Exit code: 0 after ``done``, 1 after ``error``.
    """
    protocol = sys.stdout
    sys.stdout = sys.stderr
    emit = _emitter(protocol)

    from ddviz.compute.tasks.run import run_task  # imports polars

    emit({"type": "ready"})
    line = sys.stdin.readline()
    if not line:
        return 0
    try:
        run_task(json.loads(line), emit)
    except Exception as exc:  # noqa: BLE001 - every failure is reported to the UI
        traceback.print_exc()
        emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1
    emit({"type": "done"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
