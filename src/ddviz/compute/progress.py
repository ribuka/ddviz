"""Progress messages a task sends to the UI server while it runs."""

from __future__ import annotations

from collections.abc import Callable

# Receives each protocol message of a task (``{"type": "progress", ...}``).
Emit = Callable[[dict], None]
