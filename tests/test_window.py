"""Tests of the window app running the UI server in a thread."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from ddviz.window import _App


class _FakeWindow:
    """Records what the app does to its window."""

    def __init__(self, chosen: list[str] | None = None) -> None:
        self.title = ""
        self.url: str | None = None
        self.destroyed = False
        self._chosen = chosen

    def create_file_dialog(self, *_: object, **__: object) -> list[str] | None:
        return self._chosen

    def load_url(self, url: str) -> None:
        self.url = url

    def destroy(self) -> None:
        self.destroyed = True


def _hello(path: str) -> FastAPI:
    """Return an app that answers with the path it was built for."""
    app = FastAPI()

    @app.get("/")
    async def index() -> str:
        return path

    return app


def test_the_window_shows_the_server_and_closing_stops_it(tmp_path: Path) -> None:
    """The window loads the server's page; stopping after the window closes is no failure."""
    window = _FakeWindow()
    app = _App(window, str(tmp_path), _hello)
    app.start()
    try:
        assert window.url is not None
        assert window.url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(window.url) as response:
            assert json.load(response) == str(tmp_path)
        assert window.title == f"ddviz - {tmp_path.name}"
    finally:
        app.stop()
    assert not app.failed
    assert not window.destroyed


def test_a_server_that_stops_by_itself_closes_the_window() -> None:
    """A server that fails to start fails the run and closes the window."""

    def broken(_: str) -> Callable:
        async def app(scope: dict, receive: Callable, send: Callable) -> None:
            if scope["type"] == "lifespan":
                await receive()
                await send({"type": "lifespan.startup.failed", "message": "boom"})

        return app

    window = _FakeWindow()
    app = _App(window, "data.parquet", broken)
    app.start()
    app.stop()
    assert app.failed
    assert window.destroyed
    assert window.url is None


def test_cancelling_the_file_dialog_ends_normally() -> None:
    """Without a file chosen, the window closes and nothing failed."""
    window = _FakeWindow(chosen=None)
    app = _App(window, None, _hello)
    app.start()
    app.stop()
    assert window.destroyed
    assert not app.failed
