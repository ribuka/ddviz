"""Routes of the file of the drawing settings (`ddviz.server.api_drawfile`, Issue #287, #345)."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

SETTINGS = {"zones": {"encoding": {"x": ["x"], "y": ["color"]}}}

ServeWithDraw = Callable[[dict | None], TestClient]


@pytest.fixture
def serve_with_draw(
    serve: Callable[..., AbstractContextManager[TestClient]], scatter_path: Path
) -> Iterator[ServeWithDraw]:
    """Return what serves `scatter_path` with a file of the drawing settings opened with it, already past the token."""
    with ExitStack() as started:

        def make(initial_draw: dict | None) -> TestClient:
            return started.enter_context(
                serve([scatter_path], initial_draw=initial_draw)
            )

        yield make


def test_the_draw_file_holds_the_input_and_the_kinds_of_the_columns(
    serve_with_draw: ServeWithDraw, scatter_path: Path
) -> None:
    """The file has the format's version, the input loaded, no relative paths, and the kind of each column named."""
    response = serve_with_draw(None).post(
        "/api/draw-file", json={"settings": SETTINGS, "columns": ["color", "x"]}
    )
    assert response.status_code == 200
    content = response.json()
    assert content["format"] == "ddviz-draw-settings"
    assert content["version"] == 5
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
    ("kind", "keys", "recursive", "added"),
    [
        ("key", [{"left": "label", "right": "name"}], True, {"columns": ["score"], "same_names": None}),
        ("rows", [], False, {"columns": None, "same_names": "skip"}),
        ("key", [{"left": "label", "right": "name"}], False, {"columns": None, "same_names": "skip_equal"}),
    ],
    ids=["key", "rows", "skip-equal"],
)
def test_the_draw_file_holds_the_join_given(
    serve_with_draw: ServeWithDraw,
    tmp_path: Path,
    scatter_frame: pl.DataFrame,
    kind: str,
    keys: list[dict],
    recursive: bool,
    added: dict,
) -> None:
    """After a join, ``source.join`` holds what the join was given (Issue #345): the table's absolute paths, its subfolders' choice, the kind, the keys and the columns to add (Issue #358); no relative paths."""
    folder = tmp_path / "lots"
    # Found only with its subfolders when they are read.
    held = folder / "sub" if recursive else folder
    held.mkdir(parents=True)
    labels = scatter_frame["label"].to_list()
    pl.DataFrame({"name": labels, "score": [float(i) for i in range(len(labels))]}).write_parquet(
        held / "a.parquet"
    )
    client = serve_with_draw(None)
    loaded = client.post("/api/join/source", json={"paths": [str(folder)], "recursive": recursive})
    assert loaded.status_code == 200, loaded.text
    joined = client.post("/api/join", json={"kind": kind, "keys": keys, **added})
    assert joined.status_code == 200, joined.text
    assert "score" in joined.json()["added"]
    join = client.get("/api/source").json()["join"]
    assert {k: join[k] for k in added} == added
    response = client.post("/api/draw-file", json={"settings": SETTINGS, "columns": ["x", "score"]})
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["source"]["join"] == {
        "paths": [str(folder)],
        "recursive": recursive,
        "relative": None,
        "kind": kind,
        "keys": keys,
        **added,
    }
    assert content["columns"] == {"x": "numeric", "score": "numeric"}


def test_the_draw_file_refuses_a_column_the_input_lacks(serve_with_draw: ServeWithDraw) -> None:
    """A column the input does not have cannot be saved."""
    response = serve_with_draw(None).post("/api/draw-file", json={"settings": SETTINGS, "columns": ["nope"]})
    assert response.status_code == 400
    assert "nope" in response.json()["detail"]


def test_the_initial_draw_is_the_file_given_or_null(serve_with_draw: ServeWithDraw) -> None:
    """The page gets the file opened with the input, or null without one."""
    content = {"format": "ddviz-draw-settings", "settings": SETTINGS}
    assert serve_with_draw(content).get("/api/initial-draw").json() == content
    assert serve_with_draw(None).get("/api/initial-draw").json() is None


def test_column_kinds_tell_a_missing_column_apart(serve_with_draw: ServeWithDraw) -> None:
    """The kinds asked for are the page's three, null for a column the input lacks."""
    kinds = serve_with_draw(None).post("/api/column-kinds", json={"names": ["x", "label", "nope"]}).json()
    assert kinds == {"x": "numeric", "label": "categorical", "nope": None}
