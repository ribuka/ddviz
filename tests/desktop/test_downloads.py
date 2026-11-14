"""Tests of saving the window's downloads of the plot's data to Downloads (Issue #182).

WebView2 is replaced by fakes with the same members that `Downloads` uses:
the test writes the file where the handler pointed WebView2, as WebView2
streams it, and raises ``StateChanged``.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Self

import pytest

from ddviz.desktop import downloads
from ddviz.desktop.downloads import (
    TEMP_PREFIX,
    Downloads,
    downloads_folder,
    numbered,
    publish,
    suggested_name,
)

ORIGIN = "http://127.0.0.1:50123"
NAME = "sample_20261114-120000.csv"


class _Event:
    """A .NET event: handlers come and go with ``+=`` and ``-=``."""

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler: object) -> Self:
        self.handlers.append(handler)
        return self

    def __isub__(self, handler: object) -> Self:
        self.handlers.remove(handler)
        return self

    def fire(self, *args: object) -> None:
        for handler in list(self.handlers):
            handler(*args)


class _Operation:
    """``CoreWebView2DownloadOperation``."""

    def __init__(self, uri: str, disposition: str) -> None:
        self.Uri = uri
        self.ContentDisposition = disposition
        self.State = "InProgress"
        self.InterruptReason = "None"
        self.ResultFilePath: str | None = None
        self.StateChanged = _Event()


class _Args:
    """``CoreWebView2DownloadStartingEventArgs``."""

    def __init__(self, operation: _Operation, default: str) -> None:
        self.DownloadOperation = operation
        self.ResultFilePath = default
        self.Cancel = False
        self.Handled = False


class _Core:
    """``CoreWebView2``: the page's URL, and the scripts run in it with what Downloads held then."""

    def __init__(self, folder: Path, source: str = f"{ORIGIN}/") -> None:
        self.Source = source
        self.folder = folder
        self.told: list[tuple[dict, list[str]]] = []
        self.DownloadStarting = _Event()

    def ExecuteScriptAsync(self, script: str) -> None:
        prefix, suffix = "window.ddvizSaved?.(", ");"
        assert script.startswith(prefix) and script.endswith(suffix)
        listed = sorted(p.name for p in self.folder.iterdir()) if self.folder.is_dir() else []
        self.told.append((json.loads(script[len(prefix) : -len(suffix)]), listed))


def _start(
    saver: Downloads,
    core: _Core,
    name: str = NAME,
    uri: str = f"{ORIGIN}/api/plot-data/file/abc",
) -> _Args:
    operation = _Operation(uri, f'attachment; filename="{name}"')
    args = _Args(operation, rf"C:\Users\someone\Downloads\{name}")
    saver.starting(core, args)
    return args


def _transfer(args: _Args, content: bytes, state: str = "Completed", reason: str = "None") -> None:
    """Write what WebView2 streams, then end the download as `state`."""
    Path(args.ResultFilePath).write_bytes(content)
    operation = args.DownloadOperation
    operation.ResultFilePath = args.ResultFilePath
    operation.State = state
    operation.InterruptReason = reason
    operation.StateChanged.fire(operation, None)


def _saver(folder: Path) -> Downloads:
    return Downloads(lambda: folder)


def test_a_download_is_saved_in_the_resolved_folder_under_its_name(tmp_path: Path) -> None:
    """The file goes, without a dialog or WebView2's panel, into the folder resolved, under the server's name."""
    folder = tmp_path / "moved downloads"  # created when missing
    core = _Core(folder)
    saver = _saver(folder)
    args = _start(saver, core)

    assert args.Handled and not args.Cancel
    temp = Path(args.ResultFilePath)
    assert temp.name == NAME
    assert temp.parent.parent == folder and temp.parent.name.startswith(TEMP_PREFIX)
    assert core.told == []

    _transfer(args, b"a,b\n1,2\n")
    assert (folder / NAME).read_bytes() == b"a,b\n1,2\n"
    assert sorted(p.name for p in folder.iterdir()) == [NAME]
    assert args.DownloadOperation.StateChanged.handlers == []


def test_success_is_told_once_after_the_final_name_holds_the_file(tmp_path: Path) -> None:
    """The page hears of the save once, when the file is already there under its final name."""
    core = _Core(tmp_path)
    args = _start(_saver(tmp_path), core)
    operation = args.DownloadOperation
    operation.StateChanged.fire(operation, None)  # still in progress
    assert core.told == []
    _transfer(args, b"x")
    assert core.told == [({"saved": NAME}, [NAME])]


def test_a_name_in_use_by_a_file_or_a_folder_takes_the_lowest_free_number(tmp_path: Path) -> None:
    """A file and a folder of the same names are kept; the save takes ` (2)` before the extension."""
    (tmp_path / NAME).write_bytes(b"old")
    (tmp_path / "sample_20261114-120000 (1).csv").mkdir()
    core = _Core(tmp_path)
    _transfer(_start(_saver(tmp_path), core), b"new")
    saved = "sample_20261114-120000 (2).csv"
    assert core.told[0][0] == {"saved": saved}
    assert (tmp_path / saved).read_bytes() == b"new"
    assert (tmp_path / NAME).read_bytes() == b"old"
    assert (tmp_path / "sample_20261114-120000 (1).csv").is_dir()


def test_two_saves_of_the_same_name_both_stay(tmp_path: Path) -> None:
    """Two downloads in progress at once, of one name, end in two files."""
    core = _Core(tmp_path)
    saver = _saver(tmp_path)
    first, second = _start(saver, core), _start(saver, core)
    assert Path(first.ResultFilePath).parent != Path(second.ResultFilePath).parent
    _transfer(second, b"second")
    _transfer(first, b"first")
    assert [told for told, _ in core.told] == [
        {"saved": NAME},
        {"saved": "sample_20261114-120000 (1).csv"},
    ]
    assert (tmp_path / NAME).read_bytes() == b"second"
    assert (tmp_path / "sample_20261114-120000 (1).csv").read_bytes() == b"first"


def test_saves_racing_for_one_name_never_overwrite(tmp_path: Path) -> None:
    """Saves of one name published at the same moment (other windows, other processes) each keep their content."""
    sources = []
    for i in range(16):
        source = tmp_path / f"temp{i}" / NAME
        source.parent.mkdir()
        source.write_text(str(i))
        sources.append(source)
    folder = tmp_path / "Downloads"
    folder.mkdir()
    barrier = threading.Barrier(len(sources))
    names: list[str] = []

    def save(source: Path) -> None:
        barrier.wait()
        names.append(publish(source, folder, NAME))

    threads = [threading.Thread(target=save, args=(s,)) for s in sources]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(names)) == len(sources)
    assert sorted(p.read_text() for p in folder.iterdir()) == sorted(str(i) for i in range(16))
    assert set(names) == {numbered(NAME, n) for n in range(16)}


def test_a_folder_that_cannot_be_resolved_is_told_once(tmp_path: Path) -> None:
    """Without the Downloads folder the download is cancelled and the page told why, once."""

    def missing() -> Path:
        raise OSError("ダウンロードのフォルダーが見つかりません。")

    core = _Core(tmp_path)
    args = _start(Downloads(missing), core)
    assert args.Cancel
    assert core.told == [({"error": "ダウンロードのフォルダーが見つかりません。"}, [])]


def test_a_folder_that_cannot_be_created_is_told_once(tmp_path: Path) -> None:
    """A Downloads folder that cannot be made (a file is in its place) is told once."""
    blocker = tmp_path / "Downloads"
    blocker.write_text("")
    core = _Core(tmp_path)
    args = _start(_saver(blocker), core)
    assert args.Cancel
    assert len(core.told) == 1 and "error" in core.told[0][0]


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("FileNoSpace", "ディスクの空きが足りません。"),
        ("FileAccessDenied", "ダウンロードのフォルダーに書き込めません。"),
        ("NetworkFailed", "転送が中断されました（NetworkFailed）。"),
        ("UserShutdown", "保存の途中でアプリが終了しました。"),
    ],
)
def test_an_interrupted_save_is_told_once_and_leaves_nothing(
    tmp_path: Path, reason: str, message: str
) -> None:
    """A write that failed or a transfer that stopped is told once; neither the final name nor the partial file stays."""
    core = _Core(tmp_path)
    _transfer(_start(_saver(tmp_path), core), b"part", state="Interrupted", reason=reason)
    assert core.told == [({"error": message}, [])]
    assert list(tmp_path.iterdir()) == []


def test_a_file_that_cannot_be_moved_to_its_name_is_told_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the final rename fails, the page is told once and the partial file goes."""

    def denied(source: Path, target: Path) -> None:
        raise PermissionError(13, "Permission denied", str(target))

    monkeypatch.setattr(downloads, "_move_new", denied)
    core = _Core(tmp_path)
    _transfer(_start(_saver(tmp_path), core), b"x")
    assert core.told == [({"error": f"Permission denied（{tmp_path / NAME}）"}, [])]
    assert list(tmp_path.iterdir()) == []


def test_other_downloads_are_cancelled(tmp_path: Path) -> None:
    """Only the plot's data from the page's own server is saved."""
    saver = _saver(tmp_path)
    core = _Core(tmp_path)
    for uri in [
        "http://127.0.0.1:50999/api/plot-data/file/abc",  # another server
        f"{ORIGIN}/static/app.css",
        "https://example.com/api/plot-data/file/abc",
    ]:
        args = _start(saver, core, uri=uri)
        assert args.Cancel, uri
    assert core.told == [] and list(tmp_path.iterdir()) == []


def test_a_page_left_is_not_told(tmp_path: Path) -> None:
    """After `New` (another server's page), the save still ends but nothing is told."""
    core = _Core(tmp_path)
    args = _start(_saver(tmp_path), core)
    core.Source = "http://127.0.0.1:50999/"
    _transfer(args, b"x")
    assert core.told == []
    assert (tmp_path / NAME).read_bytes() == b"x"


def test_stop_removes_the_saves_in_progress(tmp_path: Path) -> None:
    """Closing the window removes the folders of the downloads that have not ended."""
    saver = _saver(tmp_path)
    args = _start(saver, _Core(tmp_path))
    Path(args.ResultFilePath).write_bytes(b"part")
    saver.stop()
    assert list(tmp_path.iterdir()) == []


def test_replace_takes_the_place_of_pywebviews_handler(tmp_path: Path) -> None:
    """The handler of pywebview, which opens the save dialog, leaves ``DownloadStarting``."""

    def pywebview(sender: object, args: object) -> None:
        raise AssertionError("the dialog")

    core = _Core(tmp_path)
    core.DownloadStarting += pywebview
    saver = _saver(tmp_path)
    saver.replace(core, pywebview)
    assert core.DownloadStarting.handlers == [saver.starting]


def test_numbered() -> None:
    """The number goes before the last extension, after a space."""
    assert numbered("a.csv", 0) == "a.csv"
    assert numbered("a.b.parquet", 2) == "a.b (2).parquet"
    assert numbered("data", 1) == "data (1)"
    assert numbered(".csv", 1) == ".csv (1)"


def test_suggested_name() -> None:
    """The server's name, with non-ASCII characters (RFC 5987), and never a path."""
    assert suggested_name('attachment; filename="a_1.csv"', "x") == "a_1.csv"
    assert (
        suggested_name("attachment; filename*=utf-8''%E6%97%A5%E6%9C%AC.csv", "x")
        == "日本.csv"
    )
    assert suggested_name('attachment; filename="..\\..\\evil.csv"', "x") == "evil.csv"
    assert suggested_name("", "fallback.csv") == "fallback.csv"


@pytest.mark.skipif(sys.platform != "win32", reason="the known folder is Windows'")
def test_downloads_folder_is_the_users_known_folder() -> None:
    """``FOLDERID_Downloads`` resolves to an absolute folder of the user's."""
    folder = downloads_folder()
    assert folder.is_absolute() and folder.is_dir()
