"""Tests of the window app running the UI server in a thread."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from pathlib import Path

import webview
from fastapi import FastAPI

from ddviz.desktop.window import _App
from ddviz.shared.inputs import input_label


class _FakeWindow:
    """Records what the app does to its window."""

    def __init__(self, chosen: list[str] | None = None) -> None:
        self.title = ""
        self.url: str | None = None
        self.destroyed = False
        self.dialogs: list[object] = []
        self._chosen = chosen

    def create_file_dialog(
        self, kind: object, allow_multiple: bool = False, **__: object
    ) -> list[str] | None:
        self.dialogs.append((kind, allow_multiple))
        return self._chosen

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
