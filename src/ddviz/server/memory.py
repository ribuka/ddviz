"""The memory shown in the footer: the working sets of the backend and the frontend.

The backend is this process (the UI server, and pywebview's host in the
window) with every process in the workers' Job Object. The frontend is the
WebView2 processes of the window, whose ids the window hands over; there are
none in a browser (``--port``).
"""

from __future__ import annotations

import os
from collections.abc import Callable

from ddviz.workers.jobs import WorkerJob
from ddviz.workers.workingset import total_working_set

#: Returns the ids of the window's WebView2 processes, or None when unknown.
FrontendPids = Callable[[], list[int] | None]


class MemoryMeter:
    """Measures the working sets of the backend and the frontend.

    Parameters
    ----------
    frontend_pids : callable or None
        Returns the ids of the window's WebView2 processes, or None when
        they are unknown; None in a browser.
    """

    def __init__(self, frontend_pids: FrontendPids | None) -> None:
        self._frontend_pids = frontend_pids
        #: The workers' job, set while the server runs.
        self.job: WorkerJob | None = None

    def backend(self) -> int | None:
        """Return the working set of this process and the workers, in bytes.

        Returns
        -------
        int or None
            None when the workers cannot be listed or measured, or off Windows.
        """
        job = self.job
        pids = job.process_ids() if job is not None else None
        if pids is None:
            return None
        return total_working_set([os.getpid(), *pids])

    def frontend(self) -> int | None:
        """Return the working set of the window's WebView2 processes, in bytes.

        Returns
        -------
        int or None
            None in a browser, before WebView2 is ready, after it is gone,
            when a process cannot be measured, or off Windows.
        """
        if self._frontend_pids is None:
            return None
        pids = self._frontend_pids()
        if not pids:
            return None
        return total_working_set(pids)

    def measure(self) -> dict[str, int | None]:
        """Return both working sets, as ``GET /api/memory`` answers them.

        Returns
        -------
        dict
            ``{"backend_bytes": ..., "frontend_bytes": ...}``; each an int or None.
        """
        return {"backend_bytes": self.backend(), "frontend_bytes": self.frontend()}
