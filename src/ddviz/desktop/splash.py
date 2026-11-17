"""The exe's splash screen, shown by PyInstaller's bootloader until the window shows.

The bootloader shows it before Python loads (``Splash`` in
``packaging/ddviz.spec``) and sets ``_PYI_SPLASH_IPC`` for the app; a run
without the bootloader (``uv run -m ddviz``) has neither the splash nor the
variable. A worker is started with ``PYINSTALLER_SUPPRESS_SPLASH_SCREEN=1``
(`ddviz.workers.runner`), so it shows no splash.
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

#: The variable the bootloader sets when it shows the splash.
_IPC = "_PYI_SPLASH_IPC"

_closed = False


def close_splash() -> None:
    """Close the splash screen, if there is one.

    Does nothing on a second call, without the splash (development, a
    worker) or after it was closed; a failure is logged, not raised.
    """
    global _closed
    if _closed or _IPC not in os.environ:
        return
    _closed = True
    try:
        import pyi_splash

        pyi_splash.close()
    except Exception:  # noqa: BLE001 - logged; the splash must not stop the app
        _log.exception("the splash screen could not be closed")
