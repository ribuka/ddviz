"""E2E fixtures: the UI server on a free port, opened in a browser with its token."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.sync_api import Page

from ddviz.server.app import create_app
from ddviz.server.settings import Settings
from ddviz.server.settings_store import SettingsStore

TOKEN = "secret-of-the-e2e-run"
# Records the time of the last mouse press on the plot, the presses plotly
# counts for its double click, which `wait_apart` waits from.
LAST_PRESS = """addEventListener("mousedown", (event) => {
  if (event.target.closest?.("#plot")) window.lastPress = performance.now();
}, true);"""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep one shard of the E2E tests when `E2E_SHARD` is `<i>/<n>` (CI's matrix).

    The tests are dealt in turn, in the order collected: the slow ones of a
    file go to different shards.
    """
    shard = os.environ.get("E2E_SHARD")
    if not shard:
        return
    index, count = (int(part) for part in shard.split("/"))
    e2e = [item for item in items if item.get_closest_marker("e2e")]
    dropped = {item for i, item in enumerate(e2e) if i % count != index - 1}
    config.hook.pytest_deselected(items=[item for item in items if item in dropped])
    items[:] = [item for item in items if item not in dropped]


@pytest.fixture
def settings() -> Settings:
    """Return the settings of the served app; a test parametrizes it to change them."""
    return Settings()


@pytest.fixture
def settings_store(settings: Settings) -> SettingsStore:
    """Return the settings store of the served app, holding `settings`; a test overrides it to save to a file."""
    return SettingsStore(settings)


@pytest.fixture
def desktop() -> bool:
    """Return whether the served page is the desktop window's, with its title bar; a test overrides it."""
    return False


@pytest.fixture
def initial_draw() -> dict | None:
    """Return the file of the drawing settings the served app opens with (Issue #287); a test overrides it."""
    return None


@contextmanager
def served(app: FastAPI) -> Iterator[str]:
    """Serve `app` in a thread on a free port and yield its URL; stop it after."""
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
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(30)


def make_app(
    tmp_path: Path,
    scatter_path: Path,
    settings_store: SettingsStore,
    desktop: bool,
    initial_draw: dict | None,
    run: str = "run",
) -> FastAPI:
    """Return the UI server of `scatter_path`, with its task outputs in `tmp_path / run`."""
    root = tmp_path / run
    root.mkdir()
    return create_app(
        [str(scatter_path)],
        False,
        root,
        tmp_path / "cache",
        tmp_path / "history",
        settings_store,
        TOKEN,
        desktop=desktop,
        initial_draw=initial_draw,
    )


@pytest.fixture
def app_url(
    tmp_path: Path,
    scatter_path: Path,
    settings_store: SettingsStore,
    desktop: bool,
    initial_draw: dict | None,
) -> Iterator[str]:
    """Serve `scatter_path` in a thread on a free port and return its URL."""
    app = make_app(tmp_path, scatter_path, settings_store, desktop, initial_draw)
    with served(app) as url:
        yield url


@pytest.fixture
def app_page(page: Page, app_url: str) -> Iterator[Page]:
    """Open the first URL with the token, which moves it into a cookie.

    The page closes before the server stops, so that its open event stream
    does not hold the server's shutdown.
    """
    page.add_init_script(LAST_PRESS)
    page.goto(f"{app_url}/?token={TOKEN}")
    yield page
    page.close()
