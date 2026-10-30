"""The app as a window: pywebview shows the UI server running in a thread of the same process.

The server and the window live and die together: closing the window stops the
server, and a server that stops by itself closes the window. The server
listens on a port the OS picks and serves only clients with the token of the
run, which the window hands over in the first URL it opens. The window has no
address bar, so the user sees an app, not a web page.
"""

from __future__ import annotations

import ctypes
import logging
import secrets
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import uvicorn
import webview

from ddviz.desktop.runlog import RunLog, app_data_dir

_log = logging.getLogger(__name__)

_LOADING = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>body{margin:0;height:100vh;display:flex;align-items:center;
justify-content:center;font-family:sans-serif;color:#555}</style></head>
<body>起動しています…</body></html>"""

# Shown when no input was given: the OS has no dialog that picks a file or a
# folder, so the user first picks which; a folder's subfolders are read only
# when ticked. The buttons call `_Chooser` through pywebview's JS API.
_CHOOSER = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>body{margin:0;height:100vh;display:flex;align-items:center;
justify-content:center;font-family:sans-serif;color:#333;background:#f6f6f6}
main{display:flex;flex-direction:column;gap:14px;padding:28px 36px;
background:#fff;border:1px solid #ddd;border-radius:6px;min-width:320px}
h1{font-size:16px;margin:0 0 4px}button{font-size:14px;padding:8px 14px}
.row{display:flex;gap:10px}label{font-size:13px}</style></head>
<body><main><h1>開く Parquet を選んでください</h1>
<div class="row"><button type="button" id="file">ファイルを開く…</button>
<button type="button" id="folder">フォルダを開く…</button></div>
<label><input type="checkbox" id="recursive"> フォルダのサブフォルダの Parquet も読む</label>
<div class="row"><button type="button" id="cancel">キャンセル</button></div></main>
<script>
const recursive = document.getElementById("recursive");
const buttons = document.querySelectorAll("button");
async function call(name, ...args) {
  for (const b of buttons) b.disabled = true;
  try { await window.pywebview.api[name](...args); }
  finally { for (const b of buttons) b.disabled = false; }
}
document.getElementById("file").onclick = () => call("choose", "file", false);
document.getElementById("folder").onclick = () => call("choose", "folder", recursive.checked);
document.getElementById("cancel").onclick = () => call("cancel");
</script></body></html>"""

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
        recursive: bool,
        make_app: Callable[[str, bool, str], object],
    ) -> None:
        self._window = window
        self._path = path
        self._recursive = recursive
        self._make_app = make_app
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._closing = False
        self._opened = threading.Lock()
        self.failed = False

    def start(self) -> None:
        """Start the server for the input given, if any; otherwise the chooser page waits for one.

        Runs in pywebview's thread once the window is shown.
        """
        if self._path is not None:
            self._open(self._path, self._recursive)

    def choose(self, kind: str, recursive: bool) -> None:
        """Ask for a Parquet file or folder with the OS dialog, then start the server for it.

        Parameters
        ----------
        kind : str
            ``"file"`` or ``"folder"``.
        recursive : bool
            For a folder, also read the files in its subfolders.
        """
        if kind == "folder":
            chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            chosen = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=("Parquet (*.parquet)", "すべてのファイル (*.*)"),
            )
        if chosen:
            self._open(chosen[0], recursive and kind == "folder")

    def cancel(self) -> None:
        """Close the window without an input; the run ends normally."""
        self._closing = True
        self._window.destroy()

    def _open(self, path: str, recursive: bool) -> None:
        """Start the server for an input and show it in the window; only the first call does."""
        if not self._opened.acquire(blocking=False):
            return
        try:
            path = str(Path(path).resolve())
            self._window.title = f"ddviz - {Path(path).name}"
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            token = secrets.token_urlsafe(32)
            config = uvicorn.Config(
                self._make_app(path, recursive, token),
                log_config=None,
                access_log=False,
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
                self._window.load_url(f"http://127.0.0.1:{port}/?token={token}")
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


def run_window(
    path: str | None, recursive: bool, make_app: Callable[[str, bool, str], object]
) -> int:
    """Run the app in its own window until the window closes.

    Parameters
    ----------
    path : str or None
        Parquet file or folder to plot; None shows a page that asks whether
        to open a file or a folder, then the OS dialog for it.
    recursive : bool
        For a folder, also read the files in its subfolders.
    make_app : callable
        Builds the ASGI app of the UI server for an input, whether to read
        its subfolders, and the token that requests must carry.

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
        if not _run(path, recursive, make_app):
            return 1
        log.finish()
        return 0
    finally:
        log.close()


class _Chooser:
    """What the chooser page may call through pywebview's JS API, and nothing else of `_App`."""

    def __init__(self) -> None:
        self.app: _App | None = None

    def choose(self, kind: str, recursive: bool) -> None:
        """Open the OS dialog for a file or a folder (`_App.choose`)."""
        self.app.choose(kind, bool(recursive))

    def cancel(self) -> None:
        """Close the window (`_App.cancel`)."""
        self.app.cancel()


def _run(
    path: str | None, recursive: bool, make_app: Callable[[str, bool, str], object]
) -> bool:
    """Show the window until it closes; return whether everything went well."""
    runtime = bundled_runtime()
    if runtime is not None:
        if not runtime.is_dir():
            show_warning(f"WebView2 のランタイムが見つかりません：{runtime}")
            return False
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(runtime)
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    chooser = _Chooser()
    window = webview.create_window(
        "ddviz",
        html=_CHOOSER if path is None else _LOADING,
        js_api=chooser,
        width=1280,
        height=860,
        min_size=(800, 600),
    )
    app = _App(window, path, recursive, make_app)
    chooser.app = app
    # Not private: private mode deletes the WebView2 user data on every exit.
    webview.start(
        app.start,
        gui="edgechromium",
        private_mode=False,
        storage_path=str(app_data_dir() / "webview2"),
    )
    app.stop()
    return not app.failed
