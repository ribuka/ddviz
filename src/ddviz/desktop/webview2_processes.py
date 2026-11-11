"""The ids of the window's WebView2 processes, for the memory shown in the footer.

WebView2 is used on the WinForms UI thread only: there the processes of the
window's WebView2 environment (browser, renderers, GPU, utilities) are listed
with ``CoreWebView2Environment.GetProcessInfos()`` once WebView2 is ready,
and again on each ``ProcessInfosChanged``. Other threads only read the last
list (`FrontendProcesses.pids`); the UI server measures the processes itself.
The environment is the one of the window's user data folder, so another
ddviz window that shares the folder lists the same processes.
"""

from __future__ import annotations

import logging
import threading

_log = logging.getLogger(__name__)


class FrontendProcesses:
    """The last list of the window's WebView2 processes.

    The list is None before WebView2 is ready, once the window has closed or
    the browser process has exited, and when listing failed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pids: tuple[int, ...] | None = None
        self._ended = False

    def pids(self) -> list[int] | None:
        """Return the ids of the processes, or None when unknown; any thread.

        Returns
        -------
        list of int or None
            The ids.
        """
        pids = self._pids
        return list(pids) if pids is not None else None

    def attach(self, window: object) -> None:
        """Start following a pywebview window once it is shown.

        Parameters
        ----------
        window : webview.Window
            The window, not shown yet.
        """
        window.events.shown += lambda: self._on_shown(window)
        window.events.closed += self.end

    def end(self) -> None:
        """Forget the processes for good: the window or WebView2 is gone."""
        with self._lock:
            self._ended = True
            self._pids = None

    def _on_shown(self, window: object) -> None:
        """Follow WebView2 from the UI thread; pywebview calls this in a thread of its own."""
        try:
            from System import Func, Type

            form = window.native
            form.Invoke(Func[Type](lambda: self.hook(form.browser.webview)))
        except Exception:  # noqa: BLE001 - logged; the frontend's memory stays unknown
            _log.exception("cannot follow the WebView2 processes")

    def hook(self, control: object) -> None:
        """Follow a WebView2 control's processes; on the UI thread.

        Parameters
        ----------
        control : Microsoft.Web.WebView2.WinForms.WebView2
            The window's control, ready or not.
        """
        if control.CoreWebView2 is not None:
            self._ready(control.CoreWebView2)
        else:
            control.CoreWebView2InitializationCompleted += self._on_initialized

    def _on_initialized(self, sender: object, args: object) -> None:
        """Follow the processes once WebView2 is ready."""
        if args.IsSuccess:
            self._ready(sender.CoreWebView2)

    def _ready(self, core: object) -> None:
        """Subscribe to the environment's process changes and list them now."""
        try:
            environment = core.Environment
            environment.ProcessInfosChanged += self._on_changed
            core.ProcessFailed += self._on_failed
            self._list(environment)
        except Exception:  # noqa: BLE001 - logged; e.g. a runtime without the API
            _log.exception("cannot list the WebView2 processes")
            self._set(None)

    def _on_changed(self, sender: object, _: object) -> None:
        """List the processes again: one started or ended."""
        try:
            self._list(sender)
        except Exception:  # noqa: BLE001 - logged; unknown until the next change
            _log.exception("cannot list the WebView2 processes")
            self._set(None)

    def _on_failed(self, _: object, args: object) -> None:
        """Forget the processes when the browser process has exited."""
        if str(args.ProcessFailedKind) == "BrowserProcessExited":
            self.end()

    def _list(self, environment: object) -> None:
        """Read the ids of the environment's processes."""
        infos = environment.GetProcessInfos()
        self._set(tuple(int(info.ProcessId) for info in infos))

    def _set(self, pids: tuple[int, ...] | None) -> None:
        """Keep a new list, unless the processes are gone for good."""
        with self._lock:
            if not self._ended:
                self._pids = pids
