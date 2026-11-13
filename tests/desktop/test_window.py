"""Tests of the window app running the UI server in a thread."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Self

import pytest
import webview
from fastapi import FastAPI

from ddviz.desktop.window import DROP_NOT_PARQUET, DROP_UNREADABLE, _App, dropped_paths
from ddviz.shared.inputs import input_label


class _FakeWindow:
    """Records what the app does to its window."""

    def __init__(self, chosen: list[str] | None = None) -> None:
        self.title = ""
        self.url: str | None = None
        self.destroyed = False
        self.dialogs: list[object] = []
        self.scripts: list[str] = []
        self._chosen = chosen

    def create_file_dialog(
        self, kind: object, allow_multiple: bool = False, **__: object
    ) -> list[str] | None:
        self.dialogs.append((kind, allow_multiple))
        return self._chosen

    def run_js(self, script: str) -> None:
        self.scripts.append(script)

    def load_url(self, url: str) -> None:
        self.url = url

    def destroy(self) -> None:
        self.destroyed = True


def _hello(paths: list[str], recursive: bool, token: str) -> FastAPI:
    """Return an app that answers with the input and token it was built for."""
    app = FastAPI()

    @app.get("/")
    async def index(token: str) -> list:
        return [paths, recursive, token]

    return app


def test_the_window_shows_the_server_and_closing_stops_it(tmp_path: Path) -> None:
    """The window loads the server's page; stopping after the window closes is no failure."""
    window = _FakeWindow()
    app = _App(window, [str(tmp_path)], False, _hello, input_label)
    app.start()
    try:
        assert window.url is not None
        assert window.url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(window.url) as response:
            paths, recursive, token = json.load(response)
        assert paths == [str(tmp_path)]
        assert recursive is False
        assert window.url.endswith(f"/?token={token}")
        assert len(token) >= 32
        assert window.title == f"ddviz - {tmp_path.name}"
    finally:
        app.stop()
    assert not app.failed
    assert not window.destroyed


def test_a_server_that_stops_by_itself_closes_the_window() -> None:
    """A server that fails to start fails the run and closes the window."""

    def broken(*_: str) -> Callable:
        async def app(scope: dict, receive: Callable, send: Callable) -> None:
            if scope["type"] == "lifespan":
                await receive()
                await send({"type": "lifespan.startup.failed", "message": "boom"})

        return app

    window = _FakeWindow()
    app = _App(window, ["data.parquet"], False, broken, input_label)
    app.start()
    app.stop()
    assert app.failed
    assert window.destroyed
    assert window.url is None


def test_without_an_input_the_chooser_waits() -> None:
    """Without an input, starting opens nothing; cancelling closes the window normally."""
    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label)
    app.start()
    assert window.url is None
    assert window.dialogs == []
    app.cancel()
    app.stop()
    assert window.destroyed
    assert not app.failed


def test_cancelling_the_os_dialog_keeps_the_chooser() -> None:
    """Without a file chosen, the window stays on the chooser."""
    window = _FakeWindow(chosen=None)
    app = _App(window, None, False, _hello, input_label)
    app.choose("file", True)
    app.stop()
    assert window.dialogs == [(webview.FileDialog.OPEN, True)]
    assert window.url is None
    assert not window.destroyed
    assert not app.failed


def test_a_chosen_folder_opens_with_its_subfolders_on_request(tmp_path: Path) -> None:
    """A folder dialog's choice starts the server once, reading subfolders when ticked."""
    window = _FakeWindow(chosen=[str(tmp_path)])
    app = _App(window, None, False, _hello, input_label)
    app.choose("folder", True)
    try:
        with urllib.request.urlopen(window.url) as response:
            paths, recursive, _ = json.load(response)
        assert window.dialogs == [(webview.FileDialog.FOLDER, False)]
        assert (paths, recursive) == ([str(tmp_path)], True)
        first = window.url
        app.choose("folder", False)
        assert window.url == first
    finally:
        app.stop()
    assert not app.failed


def test_several_chosen_files_open_as_one_input(tmp_path: Path) -> None:
    """Files picked together start the server for all of them, without subfolders.

    The title names the first in reading order and how many more.
    """
    names = ["data_10.parquet", "data_1.parquet", "data_2.parquet"]
    window = _FakeWindow(chosen=[str(tmp_path / n) for n in names])
    app = _App(window, None, False, _hello, input_label)
    app.choose("file", True)
    try:
        with urllib.request.urlopen(window.url) as response:
            paths, recursive, _ = json.load(response)
        assert window.dialogs == [(webview.FileDialog.OPEN, True)]
        assert paths == [str(tmp_path / n) for n in names]
        assert recursive is False
        assert window.title == "ddviz - data_1.parquet and 2 more"
    finally:
        app.stop()
    assert not app.failed


def _drop(*paths: Path | str | None, names: list[str] | None = None) -> dict:
    """Return a drop event as pywebview hands it over, with each path as its full path."""
    files = []
    for i, path in enumerate(paths):
        name = names[i] if names else Path(path).name
        item: dict = {"name": name, "size": 1, "type": ""}
        if path is not None:
            item["pywebviewFullPath"] = str(path)
        files.append(item)
    return {"type": "drop", "dataTransfer": {"files": files}}


def _files(folder: Path, *names: str) -> list[Path]:
    """Create empty files in a folder and return their paths."""
    for name in names:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).touch()
    return [folder / name for name in names]


def test_dropped_parquet_files_are_accepted_in_the_order_dropped(
    tmp_path: Path,
) -> None:
    """One or several Parquet files, in any case and with spaces or Japanese in the path."""
    files = _files(tmp_path, "日本語 フォルダ/data_10.parquet", "data_2.PARQUET")
    assert dropped_paths(_drop(files[0])) == ([str(files[0])], None)
    assert dropped_paths(_drop(*files)) == ([str(f) for f in files], None)


@pytest.mark.parametrize(
    ("make", "error"),
    [
        (lambda d: d / "sub", DROP_NOT_PARQUET),
        (lambda d: d / "folder.parquet", DROP_NOT_PARQUET),
        (lambda d: d / "data.csv", DROP_NOT_PARQUET),
        (lambda d: d / "gone.parquet", DROP_UNREADABLE),
        (lambda _: "relative.parquet", DROP_UNREADABLE),
        (lambda _: None, DROP_UNREADABLE),
    ],
    ids=["folder", "folder-named-parquet", "csv", "missing", "relative", "no-path"],
)
def test_one_bad_item_refuses_the_whole_drop(
    tmp_path: Path, make: Callable[[Path], Path | str | None], error: str
) -> None:
    """A folder or another kind of file, or a path unknown or gone, refuses every item."""
    (good,) = _files(tmp_path, "good.parquet")
    _files(tmp_path, "data.csv")
    (tmp_path / "sub").mkdir()
    (tmp_path / "folder.parquet").mkdir()
    bad = make(tmp_path)
    names = ["good.parquet", "unknown.parquet"] if bad is None else None
    assert dropped_paths(_drop(good, bad, names=names)) == ([], error)


def test_another_kind_of_file_outweighs_an_unknown_path(tmp_path: Path) -> None:
    """A drop that is both wrong and unreadable asks for Parquet files only."""
    (csv,) = _files(tmp_path, "data.csv")
    event = _drop(tmp_path / "gone.parquet", csv)
    assert dropped_paths(event) == ([], DROP_NOT_PARQUET)


def test_a_drop_without_files_is_ignored() -> None:
    """A dropped link or text has no files: nothing opens and nothing is shown."""
    assert dropped_paths({"type": "drop", "dataTransfer": {"files": []}}) == ([], None)
    assert dropped_paths({"type": "drop"}) == ([], None)


def test_dropped_files_open_as_files_chosen_in_the_dialog_are(tmp_path: Path) -> None:
    """Valid files open once in natural order, without subfolders; later drops do nothing."""
    files = _files(tmp_path, "data_10.parquet", "data_2.parquet")
    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label)
    app.drop(_drop(*files))
    try:
        with urllib.request.urlopen(window.url) as response:
            paths, recursive, _ = json.load(response)
        assert paths == [str(f) for f in files]
        assert recursive is False
        assert window.title == "ddviz - data_2.parquet and 1 more"
        first = window.url
        app.drop(_drop(*files))
        assert window.url == first
    finally:
        app.stop()
    assert window.scripts == []
    assert window.dialogs == []
    assert not app.failed


def test_a_refused_drop_shows_why_and_a_later_drop_opens(tmp_path: Path) -> None:
    """A mixed drop opens nothing and tells why on the page; a valid drop after it opens."""
    good, csv = _files(tmp_path, "data.parquet", "data.csv")
    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label)
    app.drop(_drop(good, csv))
    assert window.url is None
    assert window.scripts == [f"window.ddvizDropError({json.dumps(DROP_NOT_PARQUET)})"]
    app.drop(_drop(good))
    try:
        with urllib.request.urlopen(window.url) as response:
            paths, _, _ = json.load(response)
        assert paths == [str(good)]
    finally:
        app.stop()
    assert not app.failed


def test_a_drop_while_the_dialog_is_open_is_ignored(tmp_path: Path) -> None:
    """Only one input at a time: a drop during the OS dialog does nothing."""
    (good,) = _files(tmp_path, "data.parquet")

    class _Dropping(_FakeWindow):
        def create_file_dialog(
            self, *args: object, **kwargs: object
        ) -> list[str] | None:
            app.drop(_drop(good))
            return super().create_file_dialog(*args, **kwargs)

    window = _Dropping(chosen=None)
    app = _App(window, None, False, _hello, input_label)
    app.choose("file", False)
    assert window.url is None
    app.drop(_drop(good))
    try:
        assert window.url is not None
    finally:
        app.stop()


class _Handlers(list):
    """Records handlers added with ``+=``, as pywebview's DOM events take them."""

    def __iadd__(self, handler: object) -> Self:
        self.append(handler)
        return self


class _Events:
    def __init__(self) -> None:
        self.drop = _Handlers()


class _Document:
    def __init__(self) -> None:
        self.events = _Events()


class _Dom:
    def __init__(self) -> None:
        self.document = _Document()


def test_only_the_choosers_load_subscribes_to_drops(tmp_path: Path) -> None:
    """The chooser subscribes once; with an input given, or once it is open, nothing subscribes."""
    window = _FakeWindow()
    window.dom = _Dom()
    app = _App(window, None, False, _hello, input_label)
    app.watch_drops()
    app.watch_drops()
    (handler,) = window.dom.document.events.drop
    assert handler.callback == app.drop
    assert handler.prevent_default

    given = _FakeWindow()
    given.dom = _Dom()
    _App(given, [str(tmp_path)], False, _hello, input_label).watch_drops()
    assert given.dom.document.events.drop == []
