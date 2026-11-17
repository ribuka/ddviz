"""The app's message box, with no import of pywebview or pythonnet.

Shown before the window module is imported too: when the DLLs that it loads
cannot be unblocked (`ddviz.desktop.dll_access`).
"""

from __future__ import annotations

import ctypes
import logging
import sys

from ddviz.desktop.splash import close_splash

_log = logging.getLogger(__name__)

_MB_ICONWARNING = 0x30


def show_warning(text: str) -> None:
    """Show a modal message box; off Windows, only log the text.

    Parameters
    ----------
    text : str
        The message.

    The splash screen is closed first, so that it does not cover the box.
    """
    close_splash()
    _log.warning(text)
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, text, "ddviz", _MB_ICONWARNING)
