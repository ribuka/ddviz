"""Routes of the file of the drawing settings (`ddviz.server.api_drawfile`, Issue #287, #345)."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable, Iterator
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from ddviz.server.app import create_app
from ddviz.server.settings import Settings
from ddviz.server.settings_store import SettingsStore

TOKEN = "secret-of-the-run"
SETTINGS = {"zones": {"encoding": {"x": ["x"], "y": ["color"]}}}

Serve = Callable[[dict | None], TestClient]


@pytest.fixture
def serve(tmp_path: Path, scatter_path: Path) -> Iterator[Serve]:
    """Return what serves `scatter_path` with a file of the drawing settings opened with it, already past the token."""
    started: list[TestClient] = []

    def make(initial_draw: dict | None) -> TestClient:
        root = tmp_path / f"run{len(started)}"
        root.mkdir()
        app = create_app(
            [str(scatter_path)],
            False,
            root,
            tmp_path / "cache",
            tmp_path / "history",
            SettingsStore(Settings()),
            TOKEN,
            initial_draw=initial_draw,
        )
        client = TestClient(app)
        client.__enter__()
        started.append(client)
        assert client.get("/", params={"token": TOKEN}).status_code == 200
        return client

    yield make
    for client in started:
        client.__exit__(None, None, None)


def test_the_draw_file_holds_the_input_and_the_kinds_of_the_columns(
    serve: Serve, scatter_path: Path
) -> None:
    """The file has the format's version, the input loaded, no relative paths, and the kind of each column named."""
    response = serve(None).post(
        "/api/draw-file", json={"settings": SETTINGS, "columns": ["color", "x"]}
    )
    assert response.status_code == 200
    content = response.json()
    assert content["format"] == "ddviz-draw-settings"
    assert content["version"] == 2
    assert content["app_version"] == importlib.metadata.version("ddviz")
    assert content["source"] == {
        "paths": [str(scatter_path)],
        "relative": None,
        "recursive": False,
        "join": None,
    }
    assert content["columns"] == {"color": "categorical", "x": "numeric"}
    assert content["settings"] == SETTINGS
    assert (
        response.headers["content-disposition"]
        == "attachment; filename*=UTF-8''scatter.ddviz.json"
    )


@pytest.mark.parametrize(
    ("kind", "keys", "recursive"),
    [("key", [{"left": "label", "right": "name"}], True), ("rows", [], False)],
    ids=["key", "rows"],
)
def test_the_draw_file_holds_the_join_given(
    serve: Serve, tmp_path: Path, scatter_frame: pl.DataFrame, kind: str, keys: list[dict], recursive: bool
) -> None:
    """After a join, ``source.join`` holds what the join was given (Issue #345): the table's absolute paths, its subfolders' choice, the kind and the keys; no relative paths."""
    folder = tmp_path / "lots"
    # Found only with its subfolders when they are read.
    held = folder / "sub" if recursive else folder
    held.mkdir(parents=True)
    labels = scatter_frame["label"].to_list()
    pl.DataFrame({"name": labels, "score": [float(i) for i in range(len(labels))]}).write_parquet(
        held / "a.parquet"
    )
    client = serve(None)
    loaded = client.post("/api/join/source", json={"paths": [str(folder)], "recursive": recursive})
    assert loaded.status_code == 200, loaded.text
    joined = client.post("/api/join", json={"kind": kind, "keys": keys})
    assert joined.status_code == 200, joined.text
    assert "score" in joined.json()["added"]
    response = client.post("/api/draw-file", json={"settings": SETTINGS, "columns": ["x", "score"]})
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["source"]["join"] == {
        "paths": [str(folder)],
        "recursive": recursive,
        "relative": None,
        "kind": kind,
        "keys": keys,
    }
    assert content["columns"] == {"x": "numeric", "score": "numeric"}


def test_the_draw_file_refuses_a_column_the_input_lacks(serve: Serve) -> None:
    """A column the input does not have cannot be saved."""
    response = serve(None).post("/api/draw-file", json={"settings": SETTINGS, "columns": ["nope"]})
    assert response.status_code == 400
    assert "nope" in response.json()["detail"]


def test_the_initial_draw_is_the_file_given_or_null(serve: Serve) -> None:
    """The page gets the file opened with the input, or null without one."""
    content = {"format": "ddviz-draw-settings", "settings": SETTINGS}
    assert serve(content).get("/api/initial-draw").json() == content
    assert serve(None).get("/api/initial-draw").json() is None


def test_column_kinds_tell_a_missing_column_apart(serve: Serve) -> None:
    """The kinds asked for are the page's three, null for a column the input lacks."""
    kinds = serve(None).post("/api/column-kinds", json={"names": ["x", "label", "nope"]}).json()
    assert kinds == {"x": "numeric", "label": "categorical", "nope": None}
