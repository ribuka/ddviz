"""The app as a window: pywebview shows the UI server running in a thread of the same process.

The server and the window live and die together: closing the window stops the
server, and a server that stops by itself closes the window. The server
listens on a port the OS picks and serves only clients with the token of the
run, which the window hands over in the first URL it opens. The window has no
address bar, so the user sees an app, not a web page.
"""

from __future__ import annotations

import ctypes
import importlib.metadata
import json
import logging
import secrets
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import uvicorn
import webview
from webview.dom import DOMEventHandler

from ddviz.desktop.runlog import RunLog, app_data_dir
from ddviz.desktop.single_instance import IN_USE_MESSAGE, Outcome, claim, record_window
from ddviz.desktop.titlebar import TitleBar
from ddviz.desktop.webview2_access import (
    denied_message,
    ensure_access,
    installed_runtime_version,
    windows_build,
)
from ddviz.desktop.webview2_processes import FrontendProcesses

_log = logging.getLogger(__name__)

#: The window's title before an input is open; with one, ``ddviz - <input>``.
TITLE = "ddviz"

# The title bar of the UI server's page, which the window's own pages embed:
# the server does not serve them, and file URLs are not allowed.
_STATIC = Path(__file__).parents[1] / "static"
_TITLEBAR_CSS = (_STATIC / "titlebar.css").read_text(encoding="utf-8")
_TITLEBAR_JS = (_STATIC / "js" / "titlebar.js").read_text(encoding="utf-8")


def _page(screen: str, style: str, body: str) -> str:
    """Return one of the window's own pages, with the title bar above `body`.

    Parameters
    ----------
    screen : str
        ``<html data-screen>``: which screen it is, for the title bar's menu
        (`New` is enabled on the UI server's "graph" only).
    style : str
        The page's CSS.
    body : str
        The page's content below the title bar.

    Returns
    -------
    str
        The HTML.
    """
    return (
        f'<!doctype html><html lang="ja" class="desktop" data-screen="{screen}">'
        f'<head><meta charset="utf-8"><title>{TITLE}</title>'
        f"<style>{_TITLEBAR_CSS}{style}</style></head>"
        f"<body><script>{_TITLEBAR_JS}</script>{body}</body></html>"
    )


_MESSAGE_STYLE = """html,body{height:100%}body{margin:0;display:flex;
flex-direction:column;font-family:sans-serif;color:#555}
main{flex:1;display:flex;align-items:center;justify-content:center}"""

_LOADING = _page("loading", _MESSAGE_STYLE, "<main>起動しています…</main>")

# Shown while `New` stops the open input's server, before the chooser.
_CLOSING = _page("loading", _MESSAGE_STYLE, "<main>前のデータを閉じています…</main>")

# Shown when no input was given, and after `New`: the OS has no dialog that
# picks a file or a folder, so the user first picks which (several files may
# be picked); a folder's subfolders are read only when ticked. The buttons
# call `_Api` through pywebview's JS API. Parquet files dropped from Explorer
# anywhere below the title bar (`#drop`) open too: the page only highlights
# while files are dragged there and keeps WebView2 from navigating to what is
# dropped anywhere; `_App.drop` receives the drop on `#drop` through
# pywebview's DOM events, which alone carry the files' full paths.
_CHOOSER = _page(
    "chooser",
    """html,body{height:100%}body{margin:0;display:flex;flex-direction:column;
font-family:sans-serif;color:#333}
#drop{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;
background:#f6f6f6;box-sizing:border-box;border:3px solid transparent}
#drop.dragging{background:#e8f0fe;border:3px dashed #1a73e8}
main{display:flex;flex-direction:column;gap:14px;padding:28px 36px;
background:#fff;border:1px solid #ddd;border-radius:6px;min-width:320px}
h1{font-size:16px;margin:0 0 4px}main button{font-size:14px;padding:8px 14px}
.row{display:flex;gap:10px}label,p{font-size:13px}p{margin:0;color:#666}
#error{color:#c5221f}#error:empty{display:none}""",
    """<div id="drop"><main><h1>開く Parquet を選んでください</h1>
<div class="row"><button type="button" id="file">ファイルを開く…</button>
<button type="button" id="folder">フォルダを開く…</button></div>
<p>ファイルは複数選べます。選んだファイルを縦につなげて 1 つの表にします。</p>
<p>Parquet ファイルをこの画面にドラッグ＆ドロップできます。</p>
<label><input type="checkbox" id="recursive"> フォルダのサブフォルダの Parquet も読む</label>
<p id="error" role="alert"></p>
<div class="row"><button type="button" id="cancel">キャンセル</button></div></main></div>
<script>
const drop = document.getElementById("drop");
const recursive = document.getElementById("recursive");
const error = document.getElementById("error");
const buttons = drop.querySelectorAll("button");
async function call(name, ...args) {
  error.textContent = "";
  for (const b of buttons) b.disabled = true;
  try { await window.pywebview.api[name](...args); }
  finally { for (const b of buttons) b.disabled = false; }
}
document.getElementById("file").onclick = () => call("choose", "file", false);
document.getElementById("folder").onclick = () => call("choose", "folder", recursive.checked);
document.getElementById("cancel").onclick = () => call("cancel");
window.ddvizDropError = (text) => { error.textContent = text; };
// Entering a child fires dragenter before the parent's dragleave, so a
// count of the elements entered stays above 0 until the drag leaves the
// area, is cancelled, or drops: the highlight does not flicker.
let entered = 0;
const files = (e) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
function idle() { entered = 0; drop.classList.remove("dragging"); }
drop.addEventListener("dragenter", (e) => {
  if (!files(e)) return;
  if (entered++ === 0) { error.textContent = ""; drop.classList.add("dragging"); }
});
drop.addEventListener("dragleave", (e) => {
  if (files(e) && entered > 0 && --entered === 0) idle();
});
document.addEventListener("dragenter", (e) => e.preventDefault());
document.addEventListener("dragover", (e) => {
  e.preventDefault();
  e.dataTransfer.dropEffect = files(e) && drop.contains(e.target) ? "copy" : "none";
});
document.addEventListener("drop", (e) => { e.preventDefault(); idle(); });
window.addEventListener("blur", idle);
</script>""",
)

#: Shown on the chooser when a drop has a folder or another kind of file.
DROP_NOT_PARQUET = ".parquet ファイルだけをドロップしてください。"
#: Shown on the chooser when a dropped file's path is unknown or the file is gone.
DROP_UNREADABLE = "ドロップしたファイルを確認できませんでした。ファイルを確認して、もう一度試してください。"


def dropped_paths(event: dict) -> tuple[list[str], str | None]:
    """Check the files of a drop on the chooser; all must be existing Parquet files.

    Parameters
    ----------
    event : dict
        The ``drop`` event as pywebview's DOM events hand it over: each item
        of ``dataTransfer.files`` has its ``name`` and, on WebView2, the full
        path as ``pywebviewFullPath``.

    Returns
    -------
    paths : list of str
        The files' paths in the order dropped, or empty when the drop is to
        be refused or carried no files (a link or text, which is ignored).
    error : str or None
        Why the whole drop is refused: `DROP_NOT_PARQUET` when any item is a
        folder (even one named ``*.parquet``) or does not end in ``.parquet``
        (in any case), else `DROP_UNREADABLE` when any item's absolute path is
        unknown or no file is there any more; None otherwise.
    """
    items = (event.get("dataTransfer") or {}).get("files") or []
    paths: list[str] = []
    wrong = unknown = False
    for item in items:
        full = item.get("pywebviewFullPath") or ""
        path = Path(full) if full else None
        name = path.name if path is not None else str(item.get("name") or "")
        if not name.lower().endswith(".parquet"):
            wrong = True
        elif path is None or not path.is_absolute():
            unknown = True
        elif path.is_dir():
            wrong = True
        elif not path.is_file():
            unknown = True
        else:
            paths.append(full)
    if wrong:
        return [], DROP_NOT_PARQUET
    if unknown:
        return [], DROP_UNREADABLE
    return paths, None


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
    """Runs the UI server in a thread and points the window at it.

    `New` (`new`) stops the server of the open input and shows the chooser
    again in the same window, for another input.
    """

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
        # Held from opening an input until `New` lets the chooser open another.
        self._opened = threading.Lock()
        # One input at a time from the chooser: a dialog, a drop.
        self._choosing = threading.Lock()
        # One `New` at a time.
        self._renewing = threading.Lock()
        # Whether the window shows the open input's page, which `New` leaves.
        self._serving = False
        # How many times the chooser was loaded, and the load whose drops are
        # received: each load subscribes once.
        self._chooser_loads = 0 if paths else 1
        self._watched = 0
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
        if not self._choosing.acquire(blocking=False):
            return
        try:
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
        finally:
            self._choosing.release()

    def drop(self, event: dict) -> None:
        """Open the Parquet files dropped on the chooser, as files picked in the dialog are.

        A drop with anything else opens nothing and tells why on the page; a
        drop without files (a link or text) is ignored, and so is one made
        while a dialog is open or an input is being opened.

        Parameters
        ----------
        event : dict
            The ``drop`` event from pywebview's DOM events (`dropped_paths`).
        """
        if not self._choosing.acquire(blocking=False):
            return
        try:
            paths, error = dropped_paths(event)
            if error is not None:
                self._window.run_js(f"window.ddvizDropError({json.dumps(error)})")
            elif paths:
                self._open(paths, False)
        finally:
            self._choosing.release()

    def watch_drops(self) -> None:
        """Receive drops on the chooser; pywebview calls this when a page has loaded.

        Each load of the chooser subscribes once, to the area below the title
        bar (``#drop``): at the start without an input, and after `New`. The
        other pages (loading, the UI server's) subscribe to nothing.
        """
        load = self._chooser_loads
        if load == self._watched or self._opened.locked():
            return
        area = self._window.dom.get_element("#drop")
        if area is None:  # another page is still loaded
            return
        self._watched = load
        area.events.drop += DOMEventHandler(self.drop, prevent_default=True)

    def cancel(self) -> None:
        """Close the window; the run ends normally, as with the close button."""
        self._closing = True
        self._window.destroy()

    def quit(self) -> None:
        """Close the window from the app menu's `Quit` (`cancel`)."""
        self.cancel()

    def version(self) -> str:
        """Return ddviz's version for the app menu's `Version`.

        Returns
        -------
        str
            The installed package's version, which is the ``VERSION`` of the
            source it was built from (the exe carries the package's metadata).
        """
        return importlib.metadata.version("ddviz")

    def new(self) -> None:
        """Stop the open input's server and show the chooser again, in the same window.

        The app menu's `New`, after the user confirmed it. Does nothing while
        no input's page is shown (the chooser, starting) or another `New` is
        under way. The server's shutdown stops its workers and removes its
        task outputs; the window keeps its place, size and maximized state.
        """
        if not self._renewing.acquire(blocking=False):
            return
        try:
            if not self._serving:
                return
            self._serving = False
            self._window.load_html(_CLOSING)
            server, thread = self._server, self._thread
            self._server = None
            server.should_exit = True
            thread.join()
            if self._closing:
                return
            self._thread = None
            self._paths = None
            self._window.title = TITLE
            self._chooser_loads += 1
            self._opened.release()
            self._window.load_html(_CHOOSER)
        finally:
            self._renewing.release()

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
            server = uvicorn.Server(config)
            thread = threading.Thread(
                target=self._serve, args=(server, sock), name="server", daemon=True
            )
            self._server, self._thread = server, thread
            thread.start()
            while not server.started and thread.is_alive():
                thread.join(0.02)
            if server.started:
                _log.info("serving on port %d", port)
                self._serving = True
                self._window.load_url(f"http://127.0.0.1:{port}/?token={token}")
        except Exception:  # noqa: BLE001 - logged; the run fails and the window closes
            _log.exception("failed to start")
            self.failed = True
            self._window.destroy()

    def _serve(self, server: uvicorn.Server, sock: socket.socket) -> None:
        """Run the server; when it ends without the window closing or `New`, close the window."""
        try:
            server.run(sockets=[sock])
        except BaseException:  # noqa: BLE001 - logged; the window closes below
            _log.exception("the server failed")
        finally:
            if not self._closing and server is self._server:
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
#: the token, what returns the ids of the window's WebView2 processes, and
#: whether the page is the desktop window's (with its title bar).
MakeApp = Callable[
    [list[str], bool, str, Callable[[], list[int] | None], bool], object
]


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


class _Api:
    """What the window's pages may call through pywebview's JS API, and nothing else of `_App`.

    The chooser calls `choose` and `cancel`; the title bar's app menu
    (`static/js/titlebar.js`) calls `new`, `quit` and `version`, on every page.
    """

    def __init__(self) -> None:
        self.app: _App | None = None

    def choose(self, kind: str, recursive: bool) -> None:
        """Open the OS dialog for files or a folder (`_App.choose`)."""
        self.app.choose(kind, bool(recursive))

    def cancel(self) -> None:
        """Close the window (`_App.cancel`)."""
        self.app.cancel()

    def new(self) -> None:
        """Go back to the chooser for another input (`_App.new`), once this call is answered.

        pywebview runs this in a thread of its own and then, in the same
        thread, hands the result to the page that called: `_App.new` starts
        only after that thread has ended, while the graph's page is still
        there to receive it.
        """
        caller = threading.current_thread()

        def renew() -> None:
            caller.join()
            self.app.new()

        threading.Thread(target=renew, name="new", daemon=True).start()

    def quit(self) -> None:
        """Close the window (`_App.quit`)."""
        self.app.quit()

    def version(self) -> str:
        """Return ddviz's version (`_App.version`)."""
        return self.app.version()


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
    api = _Api()
    window = webview.create_window(
        TITLE,
        html=_CHOOSER if paths is None else _LOADING,
        js_api=api,
        width=1280,
        height=860,
        min_size=(800, 600),
    )
    frontend = FrontendProcesses()
    frontend.attach(window)
    window.events.shown += lambda: _record(window)
    TitleBar().attach(window)
    app = _App(
        window,
        paths,
        recursive,
        lambda p, r, t: make_app(p, r, t, frontend.pids, True),
        label,
    )
    api.app = app
    window.events.loaded += app.watch_drops
    # Not private: private mode deletes the WebView2 user data on every exit.
    webview.start(
        app.start,
        gui="edgechromium",
        private_mode=False,
        storage_path=str(app_data_dir() / "webview2"),
    )
    app.stop()
    return not app.failed
