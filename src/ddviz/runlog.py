r"""Log file of the app and the marker that tells an abnormal end of the last run.

Both live in ``%LOCALAPPDATA%\ddviz``: the app writes every exception to
``logs\ddviz.log``, and places ``running`` while it runs. A marker left by the
last run means that run did not end normally, however it ended (an exception,
a kill, a crash inside WebView2 or pythonnet).
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
from pathlib import Path
from typing import IO

_log = logging.getLogger(__name__)


def app_data_dir() -> Path:
    r"""Return the per-user directory of the app, ``%LOCALAPPDATA%\ddviz``.

    Returns
    -------
    pathlib.Path
        The directory, which may not exist.
    """
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".cache") / "ddviz"


class RunLog:
    """The log file and the running marker of one run.

    Parameters
    ----------
    base : pathlib.Path, optional
        Directory holding both; `app_data_dir` by default.
    """

    def __init__(self, base: Path | None = None) -> None:
        base = base or app_data_dir()
        self.path = base / "logs" / "ddviz.log"
        self.marker = base / "running"
        self._file: IO[str] | None = None
        self._handler: logging.Handler | None = None

    def start(self) -> bool:
        """Open the log, route exceptions into it, and place the marker.

        Returns
        -------
        bool
            True when the last run left its marker, that is, ended abnormally.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a", encoding="utf-8")  # noqa: SIM115 - open for the whole run
        self._handler = logging.StreamHandler(self._file)
        self._handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger()
        root.addHandler(self._handler)
        root.setLevel(logging.INFO)
        # Native crashes (WebView2, pythonnet) never reach Python's handlers.
        faulthandler.enable(self._file)
        sys.excepthook = _log_exception
        threading.excepthook = _log_thread_exception
        crashed = self.marker.exists()
        if crashed:
            _log.warning("the last run did not end normally")
        self.marker.write_text(str(os.getpid()), encoding="utf-8")
        _log.info("started, pid %d", os.getpid())
        return crashed

    def finish(self) -> None:
        """Remove the marker: call only when the run ends normally."""
        self.marker.unlink(missing_ok=True)
        _log.info("ended normally")

    def close(self) -> None:
        """Stop writing to the log file and close it."""
        if self._file is None:
            return
        faulthandler.disable()
        logging.getLogger().removeHandler(self._handler)
        self._file.close()
        self._file = None


def _log_exception(kind: type, value: BaseException, tb: object) -> None:
    """Log an uncaught exception of the main thread."""
    _log.critical("uncaught exception", exc_info=(kind, value, tb))


def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
    """Log an uncaught exception of another thread."""
    _log.critical(
        "uncaught exception in thread %s",
        args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
