"""Keeps the window's WebView2 from reaching outside ddviz (Issue #377).

ddviz runs offline, and nothing it shows needs another host. Once WebView2
is ready, `OfflineGuard`:

- cancels a top-level navigation (``NavigationStarting``) to anything but
  the UI server of the open input (``http://127.0.0.1:<port>``, which changes
  with every input) and the window's own pages, which pywebview shows with
  ``NavigateToString`` (`OWN_PAGES`);
- takes ``NewWindowRequested`` from pywebview, whose handler
  (``edgechromium.py``, ``on_new_window_request``) would open the URL in the
  default browser or in the window, and opens nothing;
- turns off SmartScreen (``CoreWebView2Settings.IsReputationCheckingRequired``),
  which may ask Microsoft about navigations and downloads. A runtime too old
  for the setting is logged, and the window works without it.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from urllib.parse import urlsplit

from ddviz.desktop.webview2 import on_ui, when_ready

_log = logging.getLogger(__name__)

#: How the URIs of the pages pywebview shows with ``NavigateToString``
#: (``html=``, ``load_html``: the chooser and the waiting pages) start: WebView2
#: navigates to them as a data URI of the page (seen in ``NavigationStarting``,
#: Issue #377), and the page's ``location`` is ``about:blank``.
OWN_PAGES = "data:text/html;charset=utf-8;base64,"
#: How much of a refused URI is logged; a data URI holds a whole page.
LOGGED_LENGTH = 200


def allowed(uri: str, port: int | None) -> bool:
    """Return whether the window may navigate to `uri` while the UI server listens on `port`.

    Parameters
    ----------
    uri : str
        Where the navigation goes.
    port : int or None
        The port of the UI server on 127.0.0.1, or None while there is none
        (the chooser, `New`).

    Returns
    -------
    bool
        Whether `uri` is one of the window's own pages or on the UI server.
    """
    if uri.startswith(OWN_PAGES):
        return True
    parts = urlsplit(uri)
    try:
        uri_port = parts.port
    except ValueError:
        return False
    return (
        port is not None
        and parts.scheme == "http"
        and parts.hostname == "127.0.0.1"
        and uri_port == port
    )


class OfflineGuard:
    """Keeps a pywebview window's WebView2 on ddviz's pages, without new windows or SmartScreen.

    Parameters
    ----------
    port : callable
        Returns the port of the open input's UI server, or None while there
        is none (`ddviz.desktop.window._App.port`).
    """

    def __init__(self, port: Callable[[], int | None]) -> None:
        self._port = port
        self._window = None

    def attach(self, window: object) -> None:
        """Guard the window once WebView2 is ready; off Windows, nothing.

        Parameters
        ----------
        window : webview.Window
            The window, not started yet.
        """
        if sys.platform != "win32":
            return
        self._window = window
        window.events.before_show += self._before_show

    def _before_show(self) -> None:
        """Guard WebView2 on the UI thread; pywebview calls this in a thread of its own."""
        on_ui(self._window, self._hook, _log, "cannot keep the window offline")

    def _hook(self) -> None:
        """Guard WebView2, now or once it is ready; on the UI thread."""
        browser = self._window.native.browser
        # After pywebview's own handler of the initialization, which
        # subscribes the handler of new windows replaced here.
        when_ready(browser.webview, lambda core: self.guard(core, browser.on_new_window_request))

    def guard(self, core: object, previous: object) -> None:
        """Subscribe `starting` and `new_window` in place of `previous`, and turn off SmartScreen.

        Parameters
        ----------
        core : Microsoft.Web.WebView2.Core.CoreWebView2
            The window's WebView2.
        previous : callable
            pywebview's handler of ``NewWindowRequested``
            (``EdgeChrome.on_new_window_request``).
        """
        core.NavigationStarting += self.starting
        core.NewWindowRequested -= previous
        core.NewWindowRequested += self.new_window
        try:
            core.Settings.IsReputationCheckingRequired = False
        except Exception:  # noqa: BLE001 - logged; a runtime too old for it (a .NET error) keeps SmartScreen
            _log.exception("cannot turn off SmartScreen")

    def starting(self, sender: object, args: object) -> None:  # noqa: ARG002 - the event's signature
        """Handle ``NavigationStarting``: cancel a navigation that `allowed` refuses.

        Parameters
        ----------
        sender : CoreWebView2
            The window's WebView2.
        args : CoreWebView2NavigationStartingEventArgs
            Its ``Uri``, and ``Cancel``, set to cancel.
        """
        uri = str(args.Uri)
        if allowed(uri, self._port()):
            return
        args.Cancel = True
        _log.warning("cancelled a navigation to %s", uri[:LOGGED_LENGTH])

    def new_window(self, sender: object, args: object) -> None:  # noqa: ARG002 - the event's signature
        """Handle ``NewWindowRequested``: open nothing, neither a window nor the default browser.

        Parameters
        ----------
        sender : CoreWebView2
            The window's WebView2.
        args : CoreWebView2NewWindowRequestedEventArgs
            Its ``Uri``, and ``Handled``, set so that WebView2 opens no window.
        """
        args.Handled = True
        _log.warning("refused a new window for %s", str(args.Uri)[:LOGGED_LENGTH])
