"""Tests of the window app running the UI server in a thread."""

from __future__ import annotations

import importlib.metadata
import json
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Self

import pytest
import webview
from fastapi import FastAPI

from ddviz.desktop.window import (
    _CHOOSER,
    _CLOSING,
    DROP_NOT_PARQUET,
    DROP_UNREADABLE,
    TITLE,
    _App,
    dropped_paths,
)
from ddviz.shared.inputs import input_label


class _FakeWindow:
    """Records what the app does to its window."""

    def __init__(self, chosen: list[str] | None = None) -> None:
        self.title = ""
        self.url: str | None = None
        self.destroyed = False
        self.dialogs: list[object] = []
        self.scripts: list[str] = []
        # What the window was told to show, in order, with what the servers did.
        self.log: list[tuple] = []
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
        self.log.append(("url", url))

    def load_html(self, content: str) -> None:
        self.log.append(("html", content))

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


class _Element:
    def __init__(self) -> None:
        self.events = _Events()


class _Dom:
    """Answers `get_element` with one area, present or not (another page)."""

    def __init__(self, area: bool = True) -> None:
        self.area = _Element()
        self.has_area = area
        self.selectors: list[str] = []

    def get_element(self, selector: str) -> _Element | None:
        self.selectors.append(selector)
        return self.area if self.has_area else None


def test_only_the_choosers_load_subscribes_to_drops(tmp_path: Path) -> None:
    """The chooser subscribes once, below the title bar; with an input given, nothing subscribes."""
    window = _FakeWindow()
    window.dom = _Dom()
    app = _App(window, None, False, _hello, input_label)
    app.watch_drops()
    app.watch_drops()
    assert window.dom.selectors == ["#drop"]
    (handler,) = window.dom.area.events.drop
    assert handler.callback == app.drop
    assert handler.prevent_default

    given = _FakeWindow()
    given.dom = _Dom()
    _App(given, [str(tmp_path)], False, _hello, input_label).watch_drops()
    assert given.dom.selectors == []
    assert given.dom.area.events.drop == []


def test_a_page_without_the_drop_area_subscribes_later() -> None:
    """A load whose page is not the chooser yet leaves the subscription to the chooser's load."""
    window = _FakeWindow()
    window.dom = _Dom(area=False)
    app = _App(window, None, False, _hello, input_label)
    app.watch_drops()
    window.dom.has_area = True
    app.watch_drops()
    assert len(window.dom.area.events.drop) == 1


def _recording(log: list[tuple]) -> Callable[[list[str], bool, str], FastAPI]:
    """Return a factory of `_hello` apps that log their shutdown into `log`."""

    def make(paths: list[str], recursive: bool, token: str) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            yield
            log.append(("shutdown", paths))

        app = _hello(paths, recursive, token)
        app.router.lifespan_context = lifespan
        return app

    return make


def _get(url: str) -> list:
    """Return the JSON a `_hello` app answers at `url`."""
    with urllib.request.urlopen(url) as response:
        return json.load(response)


def test_new_stops_the_server_and_shows_the_chooser_in_the_same_window(
    tmp_path: Path,
) -> None:
    """`New` shows the closing page, stops the server, then loads the chooser; the window stays."""
    window = _FakeWindow()
    app = _App(window, [str(tmp_path)], False, _recording(window.log), input_label)
    app.start()
    first = window.url
    assert _get(first)[0] == [str(tmp_path)]
    app.new()
    try:
        assert window.log == [
            ("url", first),
            ("html", _CLOSING),
            ("shutdown", [str(tmp_path)]),
            ("html", _CHOOSER),
        ]
        assert window.title == TITLE
        with pytest.raises(urllib.error.URLError):
            urllib.request.urlopen(first, timeout=5)
    finally:
        app.stop()
    assert not window.destroyed
    assert not app.failed


def test_after_new_another_input_opens_on_a_new_server(tmp_path: Path) -> None:
    """The chooser shown by `New` opens another input with a new port and token."""
    first_input, other = tmp_path / "a", tmp_path / "other"
    first_input.mkdir()
    other.mkdir()
    window = _FakeWindow(chosen=[str(other)])
    app = _App(window, [str(first_input)], False, _hello, input_label)
    app.start()
    first = window.url
    _, _, first_token = _get(first)
    app.new()
    app.choose("folder", False)
    try:
        assert window.url != first
        paths, _, token = _get(window.url)
        assert paths == [str(other)]
        assert token != first_token
        assert window.title == "ddviz - other"
    finally:
        app.stop()
    assert not window.destroyed
    assert not app.failed


def test_new_runs_once_and_only_with_an_input_shown(tmp_path: Path) -> None:
    """`New` before an input, twice in a row, or during another `New` stops and loads once."""
    idle = _FakeWindow()
    _App(idle, None, False, _hello, input_label).new()
    assert idle.log == []

    class _Renewing(_FakeWindow):
        def load_html(self, content: str) -> None:
            super().load_html(content)
            app.new()  # again, while the first is under way

    window = _Renewing()
    app = _App(window, [str(tmp_path)], False, _recording(window.log), input_label)
    app.start()
    app.new()
    app.new()
    app.stop()
    assert [entry[0] for entry in window.log] == ["url", "html", "shutdown", "html"]
    assert not window.destroyed
    assert not app.failed


def test_cancelling_the_dialog_after_new_keeps_the_chooser(tmp_path: Path) -> None:
    """After `New`, a cancelled OS dialog starts no server."""
    window = _FakeWindow(chosen=None)
    app = _App(window, [str(tmp_path)], False, _hello, input_label)
    app.start()
    first = window.url
    app.new()
    app.choose("file", False)
    app.stop()
    assert window.url == first
    assert window.log[-1] == ("html", _CHOOSER)
    assert window.title == TITLE
    assert not window.destroyed
    assert not app.failed


def test_files_dropped_on_the_chooser_after_new_open(tmp_path: Path) -> None:
    """Started with an input, the chooser that `New` shows subscribes to drops, which open."""
    (good,) = _files(tmp_path, "data.parquet")
    window = _FakeWindow()
    window.dom = _Dom()
    app = _App(window, [str(tmp_path)], False, _hello, input_label)
    app.start()
    app.watch_drops()
    assert window.dom.area.events.drop == []
    first = window.url
    app.new()
    app.watch_drops()
    (handler,) = window.dom.area.events.drop
    handler.callback(_drop(good))
    try:
        assert window.url != first
        assert _get(window.url)[0] == [str(good)]
        assert window.title == "ddviz - data.parquet"
    finally:
        app.stop()
    assert not app.failed


def test_quit_closes_the_window_as_the_close_button_does(tmp_path: Path) -> None:
    """`Quit` closes the window; stopping afterwards is no failure."""
    window = _FakeWindow()
    app = _App(window, [str(tmp_path)], False, _hello, input_label)
    app.start()
    app.quit()
    app.stop()
    assert window.destroyed
    assert not app.failed


def test_version_is_the_packages_from_the_version_file() -> None:
    """`Version` is the installed package's version, which is the repository's VERSION."""
    app = _App(_FakeWindow(), None, False, _hello, input_label)
    version = (Path(__file__).parents[2] / "VERSION").read_text(encoding="utf-8")
    assert app.version() == importlib.metadata.version("ddviz") == version.strip()
