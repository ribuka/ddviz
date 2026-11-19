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
    CHOOSE_ONE_DRAW_FILE,
    DROP_NOT_PARQUET,
    DROP_ONE_DRAW_FILE,
    DROP_UNREADABLE,
    TITLE,
    _Api,
    _App,
    dropped_paths,
)
from ddviz.server.preferences import Preferences
from ddviz.server.settings import load_settings
from ddviz.server.settings_store import SettingsStore
from ddviz.shared.drawfile import DrawFileIO, build
from ddviz.shared.inputs import input_label
from tests.shared.test_drawfile import SETTINGS


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


def _hello(
    paths: list[str], recursive: bool, token: str, initial_draw: dict | None = None
) -> FastAPI:
    """Return an app that answers with the input and token it was built for, and with the drawing settings at `/initial-draw`."""
    app = FastAPI()

    @app.get("/")
    async def index(token: str) -> list:
        return [paths, recursive, token]

    @app.get("/initial-draw")
    async def initial() -> dict | None:
        return initial_draw

    return app


def test_the_window_shows_the_server_and_closing_stops_it(tmp_path: Path) -> None:
    """The window loads the server's page; stopping after the window closes is no failure."""
    window = _FakeWindow()
    app = _App(window, [str(tmp_path)], False, _hello, input_label, DrawFileIO())
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
    app = _App(window, ["data.parquet"], False, broken, input_label, DrawFileIO())
    app.start()
    app.stop()
    assert app.failed
    assert window.destroyed
    assert window.url is None


def test_without_an_input_the_chooser_waits() -> None:
    """Without an input, starting opens nothing; cancelling closes the window normally."""
    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
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
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.choose("file", True)
    app.stop()
    assert window.dialogs == [(webview.FileDialog.OPEN, True)]
    assert window.url is None
    assert not window.destroyed
    assert not app.failed


def test_a_chosen_folder_opens_with_its_subfolders_on_request(tmp_path: Path) -> None:
    """A folder dialog's choice starts the server once, reading subfolders when ticked."""
    window = _FakeWindow(chosen=[str(tmp_path)])
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
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
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
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
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
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
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
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
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
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
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.watch_drops()
    app.watch_drops()
    assert window.dom.selectors == ["#drop"]
    (handler,) = window.dom.area.events.drop
    assert handler.callback == app.drop
    assert handler.prevent_default

    given = _FakeWindow()
    given.dom = _Dom()
    _App(given, [str(tmp_path)], False, _hello, input_label, DrawFileIO()).watch_drops()
    assert given.dom.selectors == []
    assert given.dom.area.events.drop == []


def test_a_page_without_the_drop_area_subscribes_later() -> None:
    """A load whose page is not the chooser yet leaves the subscription to the chooser's load."""
    window = _FakeWindow()
    window.dom = _Dom(area=False)
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.watch_drops()
    window.dom.has_area = True
    app.watch_drops()
    assert len(window.dom.area.events.drop) == 1


def _recording(log: list[tuple]) -> Callable[[list[str], bool, str, dict | None], FastAPI]:
    """Return a factory of `_hello` apps that log their shutdown into `log`."""

    def make(
        paths: list[str], recursive: bool, token: str, initial_draw: dict | None = None
    ) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            yield
            log.append(("shutdown", paths))

        app = _hello(paths, recursive, token, initial_draw)
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
    app = _App(window, [str(tmp_path)], False, _recording(window.log), input_label, DrawFileIO())
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
    app = _App(window, [str(first_input)], False, _hello, input_label, DrawFileIO())
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
    _App(idle, None, False, _hello, input_label, DrawFileIO()).new()
    assert idle.log == []

    class _Renewing(_FakeWindow):
        def load_html(self, content: str) -> None:
            super().load_html(content)
            app.new()  # again, while the first is under way

    window = _Renewing()
    app = _App(window, [str(tmp_path)], False, _recording(window.log), input_label, DrawFileIO())
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
    app = _App(window, [str(tmp_path)], False, _hello, input_label, DrawFileIO())
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
    app = _App(window, [str(tmp_path)], False, _hello, input_label, DrawFileIO())
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
    app = _App(window, [str(tmp_path)], False, _hello, input_label, DrawFileIO())
    app.start()
    app.quit()
    app.stop()
    assert window.destroyed
    assert not app.failed


def test_version_is_the_packages_from_the_version_file() -> None:
    """`Version` is the installed package's version, which is the repository's VERSION."""
    app = _App(_FakeWindow(), None, False, _hello, input_label, DrawFileIO())
    version = (Path(__file__).parents[2] / "VERSION").read_text(encoding="utf-8")
    assert app.version() == importlib.metadata.version("ddviz") == version.strip()


def _settings_app(store: SettingsStore) -> Callable[[list[str], bool, str, dict | None], FastAPI]:
    """Return what builds an app answering with its input and the opacity of `store` in effect, as the UI server reads it."""

    def make(
        paths: list[str], recursive: bool, token: str, initial_draw: dict | None = None
    ) -> FastAPI:
        app = FastAPI()

        @app.get("/")
        async def index(token: str) -> list:
            return [paths, store.current.plot.legend.inactive_opacity]

        return app

    return make


def test_the_preferences_are_read_and_saved_through_the_window(tmp_path: Path) -> None:
    """The page's API gives the dialog's items and values, and a save writes the local file and returns the new values; a wrong one returns the error."""
    shared = tmp_path / "config" / "settings.toml"
    shared.parent.mkdir()
    store = SettingsStore.load(shared)
    api = _Api(Preferences(store))
    state = api.settings()
    assert state["items"][0]["key"] == "plot.legend.inactive_opacity"
    assert state["values"]["plot.legend.inactive_opacity"] == 0.15
    saved = api.save_settings({"plot.legend.inactive_opacity": 0.4})
    assert saved["values"]["plot.legend.inactive_opacity"] == 0.4
    assert load_settings(shared).plot.legend.inactive_opacity == 0.4
    assert "error" in api.save_settings({"plot.max_levels": 0})
    assert api.settings()["values"]["plot.max_levels"] == 100


def test_preferences_saved_on_the_chooser_last_across_loads_and_new(
    tmp_path: Path,
) -> None:
    """A value saved on the chooser reaches the input loaded next; one saved on the graph's page reaches the input loaded after `New`."""
    first_input, other = tmp_path / "a", tmp_path / "other"
    first_input.mkdir()
    other.mkdir()
    shared = tmp_path / "config" / "settings.toml"
    shared.parent.mkdir()
    store = SettingsStore.load(shared)
    api = _Api(Preferences(store))
    window = _FakeWindow(chosen=[str(first_input)])
    app = _App(window, None, False, _settings_app(store), input_label, DrawFileIO())
    api.app = app
    app.start()
    try:
        assert "error" not in api.save_settings({"plot.legend.inactive_opacity": 0.3})
        app.choose("folder", False)
        assert _get(window.url) == [[str(first_input)], 0.3]
        assert "error" not in api.save_settings({"plot.legend.inactive_opacity": 0.7})
        assert _get(window.url) == [[str(first_input)], 0.7]
        app.new()
        assert api.settings()["values"]["plot.legend.inactive_opacity"] == 0.7
        window._chosen = [str(other)]
        app.choose("folder", False)
        assert _get(window.url) == [[str(other)], 0.7]
    finally:
        app.stop()
    assert SettingsStore.load(shared).current.plot.legend.inactive_opacity == 0.7
    assert not app.failed


# ---- the file of the drawing settings (Issue #287) ----



def _draw_file(json_path: Path, paths: list[Path], recursive: bool = False) -> dict:
    """Write a file of the drawing settings for `paths` at `json_path`; return its content."""
    content = build(
        SETTINGS, {"a": "numeric"}, [str(p) for p in paths], recursive, json_path, "0.0.0"
    )
    json_path.write_text(json.dumps(content), encoding="utf-8")
    return content


def _initial_draw(window: _FakeWindow) -> dict | None:
    """Return the drawing settings the server shown was built with."""
    return _get(window.url.replace("/?token=", "/initial-draw?token="))


def test_a_dropped_draw_file_alone_is_accepted(tmp_path: Path) -> None:
    """One `.json` file, in any case, is taken as it is."""
    (drawn,) = _files(tmp_path, "graph.ddviz.JSON")
    assert dropped_paths(_drop(drawn)) == ([str(drawn)], None)


@pytest.mark.parametrize(
    "names",
    [["a.json", "b.json"], ["a.json", "data.parquet"], ["data.parquet", "a.json"]],
    ids=["two", "with-parquet", "after-parquet"],
)
def test_a_draw_file_with_anything_else_is_refused(tmp_path: Path, names: list[str]) -> None:
    """Two `.json` files, or one with Parquet files, refuse the whole drop."""
    files = _files(tmp_path, *names)
    assert dropped_paths(_drop(*files)) == ([], DROP_ONE_DRAW_FILE)


def test_a_dropped_draw_file_opens_its_data_with_its_settings(tmp_path: Path) -> None:
    """The data at the file's absolute paths opens, with the file's subfolder setting, and the server gets the file."""
    data = tmp_path / "data"
    data.mkdir()
    content = _draw_file(tmp_path / "graph.json", [data], recursive=True)
    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.drop(_drop(tmp_path / "graph.json"))
    try:
        paths, recursive, _ = _get(window.url)
        assert paths == [str(data)]
        assert recursive is True
        assert _initial_draw(window) == content
    finally:
        app.stop()
    assert window.scripts == []


def test_a_moved_draw_file_finds_its_data_from_where_it_is(tmp_path: Path) -> None:
    """Moved with its data, the file finds the data at its path from the file, and opens it from the dialog."""
    old, new = tmp_path / "old", tmp_path / "new"
    _files(old, "sub/a.parquet", "sub/b.parquet")
    _draw_file(old / "graph.json", [old / "sub" / "a.parquet", old / "sub" / "b.parquet"])
    old.rename(new)
    window = _FakeWindow(chosen=[str(new / "graph.json")])
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.choose("file", False)
    try:
        paths, _, _ = _get(window.url)
        assert paths == [str(new / "sub" / "a.parquet"), str(new / "sub" / "b.parquet")]
        assert _initial_draw(window)["settings"] == SETTINGS
    finally:
        app.stop()


def test_data_not_found_waits_for_other_data_or_is_dropped(tmp_path: Path) -> None:
    """Without its data, the chooser says so; the data picked next opens with the settings, unless they were dropped."""
    (gone,) = _files(tmp_path, "gone.parquet")
    content = _draw_file(tmp_path / "graph.json", [gone])
    gone.unlink()
    (other,) = _files(tmp_path, "other.parquet")
    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.drop(_drop(tmp_path / "graph.json"))
    assert window.url is None
    text = f"描画設定「graph.json」のデータが見つかりません：{gone}。データを選んでください。"
    assert window.scripts == [f"window.ddvizPendingDraw({json.dumps(text)})"]
    app.drop(_drop(other))
    try:
        assert _get(window.url)[0] == [str(other)]
        assert _initial_draw(window) == content
    finally:
        app.stop()

    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.drop(_drop(tmp_path / "graph.json"))
    app.forget_draw()
    app.drop(_drop(other))
    try:
        assert _initial_draw(window) is None
    finally:
        app.stop()


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("{", "描画設定のファイルを読めませんでした：JSON ではありません"),
        (
            '{"format": "x"}',
            "描画設定のファイルを読めませんでした：format が ddviz-draw-settings ではありません",
        ),
        (
            '{"format": "ddviz-draw-settings", "version": 2}',
            "この描画設定は読めません（版 2。この ddviz は版 1 を読みます）",
        ),
    ],
    ids=["json", "format", "version"],
)
def test_an_unreadable_draw_file_tells_why_and_keeps_the_chooser(
    tmp_path: Path, text: str, error: str
) -> None:
    """A file that cannot be read opens nothing and shows why."""
    (tmp_path / "bad.json").write_text(text, encoding="utf-8")
    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.drop(_drop(tmp_path / "bad.json"))
    assert window.url is None
    (script,) = window.scripts
    shown = json.loads(script.removeprefix("window.ddvizDropError(").removesuffix(")"))
    assert shown.startswith(error)


def test_settings_the_page_cannot_apply_keep_the_chooser(tmp_path: Path) -> None:
    """A saved file whose settings lack a key the page reads opens no data and tells which (review of PR #336)."""
    (data,) = _files(tmp_path, "data.parquet")
    content = _draw_file(tmp_path / "graph.json", [data])
    del content["settings"]["elements"]
    (tmp_path / "graph.json").write_text(json.dumps(content), encoding="utf-8")
    window = _FakeWindow()
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.drop(_drop(tmp_path / "graph.json"))
    assert window.url is None
    error = "描画設定のファイルを読めませんでした：キー settings.elements がありません"
    assert window.scripts == [f"window.ddvizDropError({json.dumps(error)})"]


def test_the_dialog_offers_draw_files_and_takes_one_alone(tmp_path: Path) -> None:
    """The file dialog lists the drawing settings beside Parquet; one with other files is refused."""
    drawn, data = _files(tmp_path, "graph.json", "data.parquet")
    kinds: list[object] = []

    class _Kinds(_FakeWindow):
        def create_file_dialog(self, *args: object, **kwargs: object) -> list[str] | None:
            kinds.append(kwargs.get("file_types"))
            return super().create_file_dialog(*args, **kwargs)

    window = _Kinds(chosen=[str(drawn), str(data)])
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    app.choose("file", False)
    assert kinds == [("Parquet (*.parquet)", "描画設定 (*.json)", "すべてのファイル (*.*)")]
    assert window.url is None
    assert window.scripts == [f"window.ddvizDropError({json.dumps(CHOOSE_ONE_DRAW_FILE)})"]


def test_saving_a_draw_file_writes_it_with_the_paths_from_it(tmp_path: Path) -> None:
    """The settings sent are written where the dialog says, with the input's paths from there; a closed dialog writes nothing."""
    (data,) = _files(tmp_path, "data/sales.parquet")
    content = build(SETTINGS, {}, [str(data)], False, None, "0.0.0")
    target = tmp_path / "graphs" / "mine.json"
    target.parent.mkdir()
    asked: list[dict] = []

    class _Saving(_FakeWindow):
        def create_file_dialog(self, *args: object, **kwargs: object) -> list[str] | None:
            asked.append(kwargs)
            return super().create_file_dialog(*args, **kwargs)

    window = _Saving(chosen=[str(target)])
    app = _App(window, None, False, _hello, input_label, DrawFileIO())
    assert app.save_draw_file(json.dumps(content)) == {"saved": "mine.json"}
    assert window.dialogs == [(webview.FileDialog.SAVE, False)]
    assert asked[0]["save_filename"] == "sales.ddviz.json"
    assert asked[0]["directory"] == str(data.parent)
    assert asked[0]["file_types"] == ("描画設定 (*.json)",)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["source"]["relative"] == [str(Path("..") / "data" / "sales.parquet")]
    assert saved["settings"] == SETTINGS

    window._chosen = None
    assert app.save_draw_file(json.dumps(content)) is None
    window._chosen = [str(tmp_path / "missing" / "x.json")]
    assert "error" in app.save_draw_file(json.dumps(content))
