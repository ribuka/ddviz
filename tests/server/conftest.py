"""Fixtures with which the tests in `tests/server` start the UI server."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from itertools import count
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ddviz.server.app import create_app
from ddviz.server.settings import Settings
from ddviz.server.settings_store import SettingsStore


@pytest.fixture
def token() -> str:
    """Return the token of the run that the served pages need."""
    return "secret-of-the-run"


@pytest.fixture
def serve(
    tmp_path: Path, token: str
) -> Callable[..., AbstractContextManager[TestClient]]:
    """Return a function that starts the UI server for an input under `tmp_path`.

    Each call writes the task output under its own folder: ``run`` for the
    first, then ``run2``, ``run3`` and so on. All calls share the column
    cache ``cache`` and the history ``history``, so a server started after
    another one finds what that one kept.
    """
    calls = count(1)

    @contextmanager
    def start(
        paths: Sequence[Path | str],
        *,
        settings: Settings | SettingsStore | None = None,
        recursive: bool = False,
        visit: bool = True,
        **options: object,
    ) -> Iterator[TestClient]:
        """Serve `paths` until the block ends.

        Parameters
        ----------
        paths : Sequence[Path | str]
            The input: files, folders or both.
        settings : Settings | SettingsStore | None
            The settings, as they are or already in a store; the defaults when None.
        recursive : bool
            Whether folders are read with their subfolders.
        visit : bool
            Whether to open the page with the token first, so the client
            sends it in a cookie; when False the client has never used it.
        **options : object
            The keyword arguments of `create_app` after the token.

        Yields
        ------
        TestClient
            The client of the started server.
        """
        call = next(calls)
        root = tmp_path / ("run" if call == 1 else f"run{call}")
        root.mkdir()
        if isinstance(settings, SettingsStore):
            store = settings
        else:
            store = SettingsStore(Settings() if settings is None else settings)
        app = create_app(
            [str(p) for p in paths],
            recursive,
            root,
            tmp_path / "cache",
            tmp_path / "history",
            store,
            token,
            **options,
        )
        with TestClient(app) as client:
            if visit:
                assert client.get("/", params={"token": token}).status_code == 200
            yield client

    return start
