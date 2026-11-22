"""E2E fixtures: the UI server on a free port, opened in a browser with its token.

Every page of a test may reach only the UI server: a request elsewhere is
aborted, and fails the test with its URL (`context`, Issue #377).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import polars as pl
import pytest
import uvicorn
from fastapi import FastAPI
from playwright.sync_api import APIResponse, BrowserContext, Page, Route

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


def is_local(url: str) -> bool:
    """Return whether a page may request `url`: the UI server (``http://127.0.0.1:<port>``), ``data:`` or ``blob:``."""
    parts = urlsplit(url)
    if parts.scheme in ("data", "blob"):
        return True
    return parts.scheme == "http" and parts.hostname == "127.0.0.1"


def fail_on_external(urls: list[str]) -> None:
    """Fail the test when its pages requested any of `urls`, named in the message."""
    if urls:
        pytest.fail("requests outside the UI server: " + ", ".join(urls), pytrace=False)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    """Fail a test whose pages requested outside the UI server by its end; later requests fail its teardown (`context`)."""
    result = yield
    urls = getattr(item, "funcargs", {}).get("external_requests")
    if urls:
        found = list(urls)
        urls.clear()
        fail_on_external(found)
    return result


@pytest.fixture
def external_requests() -> list[str]:
    """Return the URLs outside the UI server that the test's pages requested, in order."""
    return []


@pytest.fixture
def context(
    context: BrowserContext, external_requests: list[str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[BrowserContext]:
    """Return pytest-playwright's context, whose requests outside the UI server are aborted and recorded.

    Every page of the test is in it (`page`, `app_page`); a recorded URL fails
    the test at its end. What a test's own ``page.route`` fulfills or aborts
    is sent nowhere and is not recorded. Its routes run before the context's,
    and its ``route.continue_()`` or ``route.fetch()`` would send the request
    without them: those stop an external request too.
    """

    def stop(route: Route) -> None:
        external_requests.append(route.request.url)
        route.abort()

    def guard(route: Route) -> None:
        if is_local(route.request.url):
            route.fallback()
        else:
            stop(route)

    send, fetch = Route.continue_, Route.fetch

    def continue_(route: Route, **overrides: object) -> None:
        if is_local(overrides.get("url") or route.request.url):
            send(route, **overrides)
        else:
            stop(route)

    def fetch_(route: Route, **overrides: object) -> APIResponse:
        url = overrides.get("url") or route.request.url
        if not is_local(url):
            stop(route)
            pytest.fail(f"route.fetch() outside the UI server: {url}", pytrace=False)
        return fetch(route, **overrides)

    monkeypatch.setattr(Route, "continue_", continue_)
    monkeypatch.setattr(Route, "fetch", fetch_)
    context.route("**/*", guard)
    yield context
    fail_on_external(external_requests)


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


@pytest.fixture
def join_paths(tmp_path: Path) -> list[Path]:
    """Write a table to join to `scatter_path` (Issue #344): two files of 1,500 rows, labels r0 to r1499, a color repeated and a score."""
    folder = tmp_path / "join"
    folder.mkdir()
    paths = []
    for name, start, stop in [("a.parquet", 0, 1000), ("b.parquet", 1000, 1500)]:
        n = range(start, stop)
        frame = pl.DataFrame(
            {
                "label": [f"r{i}" for i in n],
                "color": [["a", "b", "c"][i % 3] for i in n],
                "score": [i / 10 for i in n],
            }
        )
        paths.append(folder / name)
        frame.write_parquet(paths[-1])
    return paths


@pytest.fixture
def equal_paths(tmp_path: Path, scatter_frame: pl.DataFrame) -> list[Path]:
    """Write a table to join to `scatter_path` by ``label``: two files of its first 1,500 rows, ``color`` the same, ``facet`` another, and a score."""
    folder = tmp_path / "equal"
    folder.mkdir()
    paths = []
    for name, start, stop in [("a.parquet", 0, 1000), ("b.parquet", 1000, 1500)]:
        frame = scatter_frame.slice(start, stop - start).select(
            "label", "color", facet=pl.lit("z"), score=pl.col("x") * 10
        )
        paths.append(folder / name)
        frame.write_parquet(paths[-1])
    return paths
