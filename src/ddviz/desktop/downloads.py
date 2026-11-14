"""Saves the plot's data to the user's Downloads folder, without a dialog (Issue #182).

The page downloads a written file with ``<a download>`` from
``GET /api/plot-data/file/{id}`` (``static/js/datamenu.js``). In the window,
WebView2 raises ``DownloadStarting`` for it: pywebview 6.2.1's handler
(``edgechromium.py``, ``on_download_starting``) would ask where to save with
the OS dialog, so `Downloads` takes its place once WebView2 is ready. It
streams the download into a folder of its own under Downloads
(``FOLDERID_Downloads``, wherever the user moved it), hides WebView2's
download panel (``Handled``), and once the transfer has completed, moves the
file to its final name with a rename that never replaces what is there:
``name.csv``, else ``name (1).csv``, ``name (2).csv`` and so on, the lowest
free. Other windows and processes saving at the same time cannot take or
overwrite the same name. Then the page that started the download is told how
it ended (``window.ddvizSaved``, ``static/js/app.js``), once: the name saved
under, or why it could not be saved. The folder of the download is removed
in every case, and those still in progress when the window closes.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from urllib.parse import urlsplit

_log = logging.getLogger(__name__)

#: ``FOLDERID_Downloads`` (KnownFolders.h).
FOLDERID_DOWNLOADS = uuid.UUID("374DE290-123F-4565-9164-39C4925E467B")
#: The path of the downloads that this saves; others are cancelled.
FILE_PATH = "/api/plot-data/file/"
#: The prefix of the folder of a download in progress, under Downloads.
TEMP_PREFIX = ".ddviz-saving-"
#: How many numbered names `publish` tries before it gives up.
MAX_NUMBER = 9999

#: Why a transfer stopped (``CoreWebView2DownloadInterruptReason``), in words.
INTERRUPTED = {
    "FileAccessDenied": "ダウンロードのフォルダーに書き込めません。",
    "FileNoSpace": "ディスクの空きが足りません。",
    "FileNameTooLong": "ファイル名が長すぎます。",
    "FileTooLarge": "ファイルが大きすぎて、ダウンロードのフォルダーに置けません。",
    "FileBlockedByPolicy": "ポリシーでダウンロードが禁止されています。",
    "UserCanceled": "保存が取り消されました。",
    "UserShutdown": "保存の途中でアプリが終了しました。",
}


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def downloads_folder() -> Path:
    """Return the user's Downloads folder, where the user moved or redirected it.

    Raises
    ------
    OSError
        Windows does not know the folder (``SHGetKnownFolderPath`` failed),
        or this is not Windows.
    """
    if sys.platform != "win32":
        raise OSError("ダウンロードのフォルダーは Windows でだけ使えます。")
    guid = _GUID.from_buffer_copy(FOLDERID_DOWNLOADS.bytes_le)
    path = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))
    try:
        if result != 0:
            raise OSError(
                f"ダウンロードのフォルダーが見つかりません（HRESULT {result & 0xFFFFFFFF:#010x}）。"
            )
        return Path(path.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)


def numbered(name: str, number: int) -> str:
    """Return `name` with `` (number)`` before its extension; `name` itself for 0.

    ``numbered("a_1.csv", 2)`` is ``"a_1 (2).csv"``.
    """
    if number == 0:
        return name
    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem:
        return f"{name} ({number})"
    return f"{stem} ({number}).{suffix}"


def _move_new(source: Path, target: Path) -> None:
    """Move `source` to `target` on the same file system, failing if `target` exists (a file or a folder).

    Raises
    ------
    FileExistsError
        Something is at `target`; nothing was moved.
    """
    if sys.platform == "win32":
        # MoveFileExW without MOVEFILE_REPLACE_EXISTING.
        os.rename(source, target)
    else:
        # rename(2) would replace a file; link(2) does not.
        os.link(source, target)
        os.unlink(source)


def publish(source: Path, folder: Path, name: str) -> str:
    """Move a finished file into `folder` under `name`, or the lowest free numbered name.

    Parameters
    ----------
    source : Path
        The finished file, on the same file system as `folder`.
    folder : Path
        Where it is saved.
    name : str
        The name it is saved under when free.

    Returns
    -------
    str
        The name it was saved under.

    Raises
    ------
    OSError
        It could not be moved; `source` stays where it was.
    """
    for number in range(MAX_NUMBER + 1):
        candidate = numbered(name, number)
        try:
            _move_new(source, folder / candidate)
        except FileExistsError:
            continue
        return candidate
    raise OSError(f"同じ名前のファイルが多すぎます（{name}）。")


def suggested_name(disposition: str, fallback: str) -> str:
    """Return the file name of a ``Content-Disposition``, or `fallback` without one.

    The server names the file (``ddviz.server.plotdata``); only its last part
    is kept, so that it cannot point elsewhere.
    """
    message = Message()
    message["content-disposition"] = disposition or ""
    name = message.get_filename() or fallback
    return Path(name.replace("\\", "/")).name or "ddviz-data"


class _Save:
    """One download in progress: its folder under Downloads and the file in it."""

    def __init__(self, folder: Path, temp: Path, name: str, origin: str) -> None:
        self.folder = folder
        self.temp = temp
        self.name = name
        self.origin = origin
        self.handler: Callable[[object, object], None] | None = None


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class Downloads:
    """Saves the window's downloads of the plot's data to Downloads, in place of pywebview's dialog.

    Parameters
    ----------
    folder : callable
        Returns the folder to save in (`downloads_folder`; a test passes its
        own).
    """

    def __init__(self, folder: Callable[[], Path] = downloads_folder) -> None:
        self._folder = folder
        self._window = None
        self._lock = threading.Lock()
        self._saves: list[_Save] = []

    def attach(self, window: object) -> None:
        """Take over the window's downloads once WebView2 is ready; off Windows, nothing.

        Parameters
        ----------
        window : webview.Window
            The window, not started yet.
        """
        if sys.platform != "win32":
            return
        self._window = window
        window.events.before_show += self._before_show
        window.events.closed += self.stop

    def _before_show(self) -> None:
        """Take over WebView2 on the UI thread; pywebview calls this in a thread of its own."""
        try:
            from System import Action

            self._window.native.Invoke(Action(self._hook))
        except Exception:  # noqa: BLE001 - logged; downloads then go to pywebview
            _log.exception("cannot take over the downloads")

    def _hook(self) -> None:
        """Replace pywebview's handler, now or once WebView2 is ready; on the UI thread."""
        browser = self._window.native.browser
        control = browser.webview
        if control.CoreWebView2 is not None:
            self.replace(control.CoreWebView2, browser.on_download_starting)
        else:

            def initialized(sender: object, args: object) -> None:
                if args.IsSuccess:
                    self.replace(sender.CoreWebView2, browser.on_download_starting)

            # After pywebview's own handler of this event, which subscribes
            # the handler replaced here.
            control.CoreWebView2InitializationCompleted += initialized

    def replace(self, core: object, previous: object) -> None:
        """Unsubscribe `previous` from ``DownloadStarting`` and subscribe `starting`.

        Parameters
        ----------
        core : Microsoft.Web.WebView2.Core.CoreWebView2
            The window's WebView2.
        previous : callable
            pywebview's handler (``EdgeChrome.on_download_starting``).
        """
        core.DownloadStarting -= previous
        core.DownloadStarting += self.starting

    def starting(self, sender: object, args: object) -> None:
        """Handle ``DownloadStarting``: save into a folder of its own under Downloads, without a dialog.

        Parameters
        ----------
        sender : CoreWebView2
            The WebView2 of the page that started the download; told how
            the save ended.
        args : CoreWebView2DownloadStartingEventArgs
        """
        operation = args.DownloadOperation
        uri = str(operation.Uri)
        parts = urlsplit(uri)
        if (
            parts.scheme != "http"
            or parts.hostname != "127.0.0.1"
            or not parts.path.startswith(FILE_PATH)
            or _origin(uri) != _origin(str(sender.Source))
        ):
            _log.warning("cancelled a download that is not the plot's data: %s", uri)
            args.Cancel = True
            return
        name = suggested_name(
            str(operation.ContentDisposition or ""),
            Path(str(args.ResultFilePath or "")).name,
        )
        try:
            folder = self._folder()
            folder.mkdir(parents=True, exist_ok=True)
            temp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=folder))
        except Exception as error:  # noqa: BLE001 - told to the page
            _log.exception("cannot prepare the save of %s", name)
            args.Cancel = True
            args.Handled = True
            self._tell(sender, {"error": _reason(error)})
            return
        save = _Save(folder, temp, name, _origin(uri))
        with self._lock:
            self._saves.append(save)
        save.handler = lambda op, _: self._changed(sender, op, save)
        operation.StateChanged += save.handler
        args.ResultFilePath = str(temp / name)
        args.Handled = True

    def _changed(self, sender: object, operation: object, save: _Save) -> None:
        """Handle a download's ``StateChanged``: publish it once completed, or tell why it stopped."""
        state = str(operation.State)
        if state == "InProgress":
            return
        operation.StateChanged -= save.handler
        try:
            if state == "Completed":
                result = self._publish(operation, save)
            else:
                reason = str(operation.InterruptReason)
                _log.warning("the save of %s was interrupted: %s", save.name, reason)
                result = {"error": INTERRUPTED.get(reason, f"転送が中断されました（{reason}）。")}
        finally:
            self._remove(save)
        if _origin(str(sender.Source)) == save.origin:
            self._tell(sender, result)

    def _publish(self, operation: object, save: _Save) -> dict:
        """Move a completed download to its final name; return what to tell the page."""
        written = operation.ResultFilePath
        source = Path(str(written)) if written else save.temp / save.name
        try:
            name = publish(source, save.folder, save.name)
        except Exception as error:  # noqa: BLE001 - told to the page
            _log.exception("cannot save %s", save.name)
            return {"error": _reason(error)}
        _log.info("saved %s", save.folder / name)
        return {"saved": name}

    def _remove(self, save: _Save) -> None:
        """Remove a download's folder, with what is left in it."""
        with self._lock:
            if save in self._saves:
                self._saves.remove(save)
        shutil.rmtree(save.temp, ignore_errors=True)

    def stop(self) -> None:
        """Remove the folders of the downloads still in progress: the window has closed."""
        with self._lock:
            saves, self._saves = self._saves, []
        for save in saves:
            shutil.rmtree(save.temp, ignore_errors=True)

    def _tell(self, core: object, result: dict) -> None:
        """Tell the page how a save ended (``window.ddvizSaved``, ``static/js/app.js``)."""
        try:
            core.ExecuteScriptAsync(f"window.ddvizSaved?.({json.dumps(result)});")
        except Exception:  # noqa: BLE001 - logged; the page is gone
            _log.exception("cannot tell the page how the save ended")


def _reason(error: BaseException) -> str:
    """Return why a save failed, for the page."""
    if isinstance(error, OSError) and error.strerror:
        where = f"（{error.filename}）" if error.filename else ""
        return f"{error.strerror}{where}"
    return str(error) or type(error).__name__
