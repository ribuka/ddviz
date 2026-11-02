"""E2E fixtures: the UI server on a free port, opened in a browser with its token."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Page

from ddviz.server.app import create_app
from ddviz.server.settings import Settings

TOKEN = "secret-of-the-e2e-run"


@pytest.fixture
def settings() -> Settings:
    """Return the settings of the served app; a test parametrizes it to change them."""
    return Settings()


@pytest.fixture
def app_url(tmp_path: Path, scatter_path: Path, settings: Settings) -> Iterator[str]:
    """Serve `scatter_path` in a thread on a free port and return its URL."""
    root = tmp_path / "run"
    root.mkdir()
    app = create_app(
        [str(scatter_path)], False, root, tmp_path / "cache", settings, TOKEN
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("the UI server did not start")
        thread.join(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(30)


@pytest.fixture
def app_page(page: Page, app_url: str) -> Iterator[Page]:
    """Open the first URL with the token, which moves it into a cookie.

    The page closes before the server stops, so that its open event stream
    does not hold the server's shutdown.
    """
    page.goto(f"{app_url}/?token={TOKEN}")
    yield page
    page.close()
