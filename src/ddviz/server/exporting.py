"""The export of the plot's data that the table's pool writes now, if any (Issue #194).

The export runs in the table's pool, and a task given to that pool kills the
one running (`ddviz.server.broker`): while an export runs, the pages of the
selection table are refused (``GET /api/table`` answers 409 ``exporting``)
so that the graph can be used without killing it. The page cancels its
export by its token (``POST /api/plot-data/cancel``).
"""

from __future__ import annotations


class Exporting:
    """The token of the export running, whether it was cancelled, and whether its task was given to the pool."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.cancelled = False
        self.submitted = False

    @property
    def active(self) -> bool:
        """Return whether an export runs."""
        return self.token is not None

    def begin(self, token: str) -> None:
        """Start the export of the page's `token`."""
        self.token = token
        self.cancelled = False
        self.submitted = False

    def end(self) -> None:
        """End the export, whatever its end."""
        self.token = None
        self.cancelled = False
        self.submitted = False

    def cancel(self, token: str) -> bool:
        """Mark the export of `token` cancelled; return whether its task is in the pool to kill.

        Parameters
        ----------
        token : str
            The page's token of the export.

        Returns
        -------
        bool
            True when the export of `token` runs in the pool, so that the
            caller kills the pool's task; False when the export has not
            reached the pool (it stops before), or `token` is not the
            export running.
        """
        if token != self.token:
            return False
        self.cancelled = True
        return self.submitted
