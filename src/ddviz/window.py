"""The app as a window: pywebview shows the UI server running in a thread of the same process.

The server and the window live and die together: closing the window stops the
server, and a server that stops by itself closes the window. The server
listens on a port the OS picks, and the window has no address bar, so the
user sees an app, not a web page.
"""

from __future__ import annotations

import ctypes
import logging
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import uvicorn
import webview

from ddviz.runlog import RunLog, app_data_dir

_log = logging.getLogger(__name__)

_LOADING = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>body{margin:0;height:100vh;display:flex;align-items:center;
justify-content:center;font-family:sans-serif;color:#555}</style></head>
<body>起動しています…</body></html>"""

_MB_ICONWARNING = 0x30


def bundled_runtime() -> Path | None:
    """Return the WebView2 fixed-version runtime shipped next to the exe.

    Returns
    -------
    pathlib.Path or None
        The runtime folder; None in development, where the installed
        (Evergreen) runtime is used.
    """
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).parent / "webview2"


def show_warning(text: str) -> None:
    """Show a modal message box; off Windows, only log the text.

    Parameters
    ----------
    text : str
        The message.
    """
    _log.warning(text)
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, text, "ddviz", _MB_ICONWARNING)


class _App:
    """Runs the UI server in a thread and points the window at it."""

    def __init__(
        self,
        window: webview.Window,
        path: str | None,
        make_app: Callable[[str], object],
    ) -> None:
        self._window = window
        self._path = path
        self._make_app = make_app
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._closing = False
        self.failed = False

    def start(self) -> None:
        """Ask for the Parquet file if none was given, then start the server.

        Runs in pywebview's thread once the window is shown.
        """
        try:
            if self._path is None:
                chosen = self._window.create_file_dialog(
                    webview.FileDialog.OPEN,
                    file_types=("Parquet (*.parquet)", "すべてのファイル (*.*)"),
                )
                if not chosen:
                    self._closing = True
                    self._window.destroy()
                    return
                self._path = chosen[0]
            path = str(Path(self._path).resolve())
            self._window.title = f"ddviz - {Path(path).name}"
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            config = uvicorn.Config(
                self._make_app(path), log_config=None, access_log=False
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(
                target=self._serve, args=(sock,), name="server", daemon=True
            )
            self._thread.start()
            while not self._server.started and self._thread.is_alive():
                self._thread.join(0.02)
            if self._server.started:
                _log.info("serving on port %d", port)
                self._window.load_url(f"http://127.0.0.1:{port}/")
        except Exception:  # noqa: BLE001 - logged; the run fails and the window closes
            _log.exception("failed to start")
            self.failed = True
            self._window.destroy()

    def _serve(self, sock: socket.socket) -> None:
        """Run the server; when it ends without the window closing, close the window."""
        try:
            self._server.run(sockets=[sock])
        except BaseException:  # noqa: BLE001 - logged; the window closes below
            _log.exception("the server failed")
        finally:
            if not self._closing:
                _log.error("the server stopped by itself")
                self.failed = True
                self._window.destroy()

    def stop(self) -> None:
        """Stop the server after the window has closed."""
        self._closing = True
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join()


def run_window(path: str | None, make_app: Callable[[str], object]) -> int:
    """Run the app in its own window until the window closes.

    Parameters
    ----------
    path : str or None
        Parquet file to plot; None asks for it with a file dialog.
    make_app : callable
        Builds the ASGI app of the UI server for a Parquet file.

    Returns
    -------
    int
        Exit code: 0 when the run ended normally.
    """
    log = RunLog()
    try:
        if log.start():
            show_warning(
                "前回の ddviz は正常に終了しませんでした。\n"
                f"ログ：{log.path}\n\n"
                "問題が続く場合は、このログを開発者に送ってください。"
            )
        if not _run(path, make_app):
            return 1
        log.finish()
        return 0
    finally:
        log.close()


def _run(path: str | None, make_app: Callable[[str], object]) -> bool:
    """Show the window until it closes; return whether everything went well."""
    runtime = bundled_runtime()
    if runtime is not None:
        if not runtime.is_dir():
            show_warning(f"WebView2 のランタイムが見つかりません：{runtime}")
            return False
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(runtime)
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window(
        "ddviz", html=_LOADING, width=1280, height=860, min_size=(800, 600)
    )
    app = _App(window, path, make_app)
    # Not private: private mode deletes the WebView2 user data on every exit.
    webview.start(
        app.start,
        gui="edgechromium",
        private_mode=False,
        storage_path=str(app_data_dir() / "webview2"),
    )
    app.stop()
    return not app.failed
