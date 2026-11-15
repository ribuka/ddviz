"""Reaching a pywebview window's WebView2: on its UI thread, once it is ready.

pywebview calls its events in threads of its own, while WinForms and WebView2
are used on the UI thread only (`on_ui`). The control's ``CoreWebView2`` is
None until its initialization completes (`when_ready`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable


def on_ui(window: object, action: Callable[[], None], log: logging.Logger, failure: str) -> bool:
    """Run `action` on the UI thread of a pywebview window and wait for it; log what fails.

    Parameters
    ----------
    window : webview.Window
        The window, with its WinForms form in ``native``.
    action : callable
        What to run, without arguments.
    log : logging.Logger
        The logger of the caller.
    failure : str
        What is logged with ``log.exception`` when `action` or the call fails.

    Returns
    -------
    bool
        Whether `action` ran to its end; a failure (also when pythonnet's
        ``System`` cannot be imported) is logged.
    """
    try:
        from System import Action

        window.native.Invoke(Action(action))
    except Exception:  # logged; the window keeps working without it
        log.exception(failure)
        return False
    return True


def when_ready(control: object, ready: Callable[[object], None]) -> None:
    """Call `ready` with the control's ``CoreWebView2`` now, or once its initialization succeeds; on the UI thread.

    A failed initialization (``IsSuccess`` false) calls nothing.

    Parameters
    ----------
    control : Microsoft.Web.WebView2.WinForms.WebView2
        The window's control, ready or not.
    ready : callable
        Called with the ``CoreWebView2``.
    """
    if control.CoreWebView2 is not None:
        ready(control.CoreWebView2)
        return

    def initialized(sender: object, args: object) -> None:
        if args.IsSuccess:
            ready(sender.CoreWebView2)

    control.CoreWebView2InitializationCompleted += initialized
