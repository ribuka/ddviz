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
from ddviz.desktop.single_instance import IN_USE_MESSAGE, Outcome, claim, record_window
from ddviz.desktop.webview2_access import (
    denied_message,
    ensure_access,
    installed_runtime_version,
    windows_build,
)
from ddviz.desktop.webview2_processes import FrontendProcesses

_log = logging.getLogger(__name__)

_LOADING = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>body{margin:0;height:100vh;display:flex;align-items:center;
justify-content:center;font-family:sans-serif;color:#555}</style></head>
<body>起動しています…</body></html>"""

# Shown when no input was given: the OS has no dialog that picks a file or a
# folder, so the user first picks which (several files may be picked); a folder's subfolders are read only
# when ticked. The buttons call `_Chooser` through pywebview's JS API.
_CHOOSER = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>body{margin:0;height:100vh;display:flex;align-items:center;
justify-content:center;font-family:sans-serif;color:#333;background:#f6f6f6}
main{display:flex;flex-direction:column;gap:14px;padding:28px 36px;
background:#fff;border:1px solid #ddd;border-radius:6px;min-width:320px}
h1{font-size:16px;margin:0 0 4px}button{font-size:14px;padding:8px 14px}
.row{display:flex;gap:10px}label,p{font-size:13px}p{margin:0;color:#666}</style></head>
<body><main><h1>開く Parquet を選んでください</h1>
<div class="row"><button type="button" id="file">ファイルを開く…</button>
<button type="button" id="folder">フォルダを開く…</button></div>
<p>ファイルは複数選べます。選んだファイルを縦につなげて 1 つの表にします。</p>
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

NO_RUNTIME_MESSAGE = (
    "WebView2 のランタイムが見つかりません。\n\n"
    "次のどちらかを行ってから、もう一度起動してください。\n"
    "- Microsoft Edge WebView2 Runtime（Evergreen 版）をインストールする。\n"
    "- WebView2 の固定版ランタイムを Microsoft のページから取り、展開したフォルダを"
    "「webview2」という名前で ddviz.exe と同じフォルダに置く。\n\n"
    "https://developer.microsoft.com/microsoft-edge/webview2/"
)


def fixed_runtime() -> Path | None:
    """Return where an administrator may place a WebView2 fixed-version runtime.

    Returns
    -------
    pathlib.Path or None
        The ``webview2`` folder next to the exe, which may not exist; None in
        development, where the installed (Evergreen) runtime is used.
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
        paths: list[str] | None,
        recursive: bool,
        make_app: Callable[[list[str], bool, str], object],
        label: Callable[[list[str]], str],
    ) -> None:
        self._window = window
        self._paths = paths
        self._recursive = recursive
        self._make_app = make_app
        self._label = label
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._closing = False
        self._opened = threading.Lock()
        self.failed = False

    def start(self) -> None:
        """Start the server for the input given, if any; otherwise the chooser page waits for one.

        Runs in pywebview's thread once the window is shown.
        """
        if self._paths:
            self._open(self._paths, self._recursive)

    def choose(self, kind: str, recursive: bool) -> None:
        """Ask for Parquet files or a folder with the OS dialog, then start the server for them.

        Parameters
        ----------
        kind : str
            ``"file"`` (one or several files, read one after another as one
            table) or ``"folder"``.
        recursive : bool
            For a folder, also read the files in its subfolders.
        """
        if kind == "folder":
            chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            chosen = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=("Parquet (*.parquet)", "すべてのファイル (*.*)"),
            )
        if not chosen:
            return
        if kind == "folder":
            self._open([chosen[0]], recursive)
        else:
            self._open(list(chosen), False)

    def cancel(self) -> None:
        """Close the window without an input; the run ends normally."""
        self._closing = True
        self._window.destroy()

    def _open(self, paths: list[str], recursive: bool) -> None:
        """Start the server for an input and show it in the window; only the first call does."""
        if not self._opened.acquire(blocking=False):
            return
        try:
            paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
            self._window.title = f"ddviz - {self._label(paths)}"
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            token = secrets.token_urlsafe(32)
            config = uvicorn.Config(
                self._make_app(paths, recursive, token),
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


#: Builds the UI server's app for an input, whether to read its subfolders,
#: the token, and what returns the ids of the window's WebView2 processes.
MakeApp = Callable[[list[str], bool, str, Callable[[], list[int] | None]], object]


def run_window(
    paths: list[str] | None,
    recursive: bool,
    make_app: MakeApp,
    label: Callable[[list[str]], str],
) -> int:
    """Run the app in its own window until the window closes.

    Parameters
    ----------
    paths : list of str or None
        Parquet file or folder, or several Parquet files, to plot; None
        shows a page that asks whether to open files or a folder, then the
        OS dialog for it.
    recursive : bool
        For a folder, also read the files in its subfolders.
    make_app : callable
        Builds the ASGI app of the UI server for an input, whether to read
        its subfolders, the token that requests must carry, and what returns
        the ids of the window's WebView2 processes (for the memory in the
        footer).
    label : callable
        Names an input in the window's title
        (`ddviz.shared.inputs.input_label`; the window does not import it).

    Returns
    -------
    int
        Exit code: 0 when the run ended normally, or when the window of
        another run in this Windows session was brought to the front (the
        input given here is ignored).
    """
    # Before the window and the server: a second run opens neither. The
    # claim keeps the mutex for the whole process.
    instance = claim()
    if instance.outcome is Outcome.FRONT:
        return 0
    if instance.outcome is Outcome.IN_USE:
        show_warning(IN_USE_MESSAGE)
        return 1
    # Before the run log: a run that stops here did not end abnormally.
    runtime = _choose_runtime()
    if runtime is None:
        return 1
    log = RunLog()
    try:
        if log.start():
            show_warning(
                "前回の ddviz は正常に終了しませんでした。\n"
                f"ログ：{log.path}\n\n"
                "問題が続く場合は、このログを開発者に送ってください。"
            )
        _log.info("using %s", runtime)
        if not _run(paths, recursive, make_app, label):
            return 1
        log.finish()
        return 0
    finally:
        log.close()


def _choose_runtime() -> str | None:
    """Pick the WebView2 runtime: the fixed version next to the exe, else the installed one.

    Returns
    -------
    str or None
        The runtime picked, for the run log (which opens only later), e.g.
        ``"the installed WebView2 Runtime 156.0.4314.58"``. None when neither
        is there, or the fixed version lacks the access that the Windows 10
        line needs and the user cannot grant it; the user has been told why.
        In development pywebview finds the installed runtime by itself.
    """
    runtime = fixed_runtime()
    if runtime is None:
        return "the WebView2 Runtime that pywebview finds"
    if runtime.is_dir():
        if not ensure_access(runtime, windows_build()):
            show_warning(denied_message(runtime))
            return None
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(runtime)
        return f"the WebView2 Runtime in {runtime}"
    version = installed_runtime_version()
    if version is None:
        show_warning(NO_RUNTIME_MESSAGE)
        return None
    return f"the installed WebView2 Runtime {version}"


def _record(window: webview.Window) -> None:
    """Write the handle of the shown window for a second run; pywebview calls this in a thread of its own."""
    try:
        from System import Func, Int64

        form = window.native
        record_window(int(form.Invoke(Func[Int64](lambda: form.Handle.ToInt64()))))
    except Exception:  # noqa: BLE001 - logged; a second run then reports the app in use
        _log.exception("cannot record the window")


class _Chooser:
    """What the chooser page may call through pywebview's JS API, and nothing else of `_App`."""

    def __init__(self) -> None:
        self.app: _App | None = None

    def choose(self, kind: str, recursive: bool) -> None:
        """Open the OS dialog for files or a folder (`_App.choose`)."""
        self.app.choose(kind, bool(recursive))

    def cancel(self) -> None:
        """Close the window (`_App.cancel`)."""
        self.app.cancel()


def _run(
    paths: list[str] | None,
    recursive: bool,
    make_app: MakeApp,
    label: Callable[[list[str]], str],
) -> bool:
    """Show the window until it closes; return whether everything went well."""
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    # The plot's data is saved as a download; pywebview cancels downloads
    # unless allowed, and asks where to save them with the OS dialog.
    webview.settings["ALLOW_DOWNLOADS"] = True
    chooser = _Chooser()
    window = webview.create_window(
        "ddviz",
        html=_CHOOSER if paths is None else _LOADING,
        js_api=chooser,
        width=1280,
        height=860,
        min_size=(800, 600),
    )
    frontend = FrontendProcesses()
    frontend.attach(window)
    window.events.shown += lambda: _record(window)
    app = _App(
        window,
        paths,
        recursive,
        lambda p, r, t: make_app(p, r, t, frontend.pids),
        label,
    )
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
