"""Tests of the UI server's HTTP API, with real worker processes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from ddviz.server.app import create_app
from ddviz.server.auth import COOKIE
from ddviz.server.settings import HoverSettings, Settings

ENCODING = {"x": ["x"], "y": ["y"], "color": "color", "col": "facet"}
SIZE = {"width": 400, "height": 300}
TOKEN = "secret-of-the-run"


@pytest.fixture
def server(tmp_path: Path, scatter_path: Path) -> Iterator[TestClient]:
    """Serve `scatter_path` with its task outputs and column cache under `tmp_path`; no token yet."""
    app = create_app(
        str(scatter_path),
        False,
        tmp_path / "run",
        tmp_path / "cache",
        Settings(),
        TOKEN,
    )
    (tmp_path / "run").mkdir()
    with TestClient(app) as started:
        yield started


@pytest.fixture
def client(server: TestClient) -> TestClient:
    """Open the first URL on the server, which moves the token into a cookie."""
    assert server.get("/", params={"token": TOKEN}).status_code == 200
    return server


@pytest.mark.parametrize(
    "path", ["/", "/static/js/app.js", "/api/schema", "/api/events", "/api/images/1"]
)
def test_requests_without_the_token_are_refused(server: TestClient, path: str) -> None:
    """Without the cookie, every page, file and API answers 403, SSE included."""
    assert server.get(path).status_code == 403
    server.cookies.set(COOKIE, "wrong")
    assert server.get(path).status_code == 403
    assert server.post("/api/plot", json={}).status_code == 403


def test_the_token_only_opens_the_first_page(server: TestClient) -> None:
    """The token is accepted only on `/`, and only when it is right."""
    assert server.get("/api/schema", params={"token": TOKEN}).status_code == 403
    assert server.get("/", params={"token": "wrong"}).status_code == 403
    assert server.get("/", params={"token": "é"}).status_code == 403


def test_the_token_moves_into_a_strict_httponly_cookie(server: TestClient) -> None:
    """The first URL sets the cookie and redirects to `/` without the token."""
    response = server.get("/", params={"token": TOKEN}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"].lower()
    assert f"{COOKIE}={TOKEN}" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert server.get("/").status_code == 200
    assert server.get("/api/schema").status_code == 200


def _plot(client: TestClient, **extra: object) -> dict:
    """Draw `ENCODING` and return the response body."""
    response = client.post("/api/plot", json={"encoding": ENCODING, **SIZE, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_schema_and_columns(client: TestClient) -> None:
    """The schema lists the columns, and the search finds them by name."""
    schema = client.get("/api/schema").json()
    assert [c["name"] for c in schema] == ["x", "y", "label", "color", "facet"]
    found = client.get("/api/columns", params={"q": "co"}).json()
    assert "color" in [c["name"] for c in found["columns"]]
    assert found["shares"] in ("pending", "done")


def test_plot_draws_and_serves_images(client: TestClient) -> None:
    """A plot returns its figure; its images and hovers are served by task."""
    result = _plot(client)
    meta = result["meta"]
    assert meta["encoding"]["x"] == ["x"]
    assert meta["series"] == ["a", "b", "c"]
    assert len(meta["panels"]) == 2
    images = client.get(f"/api/images/{meta['task']}")
    assert images.status_code == 200
    assert len(images.content) == sum(size for _, size in filter(None, meta["images"]))
    hover = client.get(
        "/api/hover",
        params={"task": meta["task"], "panel": 0, "fx": 0, "fy": 0, "sx": 1, "sy": 1},
    ).json()
    assert "hit" in hover
    assert client.get(
        "/api/hover",
        params={
            "task": meta["task"] + 99,
            "panel": 0,
            "fx": 0,
            "fy": 0,
            "sx": 1,
            "sy": 1,
        },
    ).json() == {"stale": True}
    assert client.get(f"/api/images/{meta['task'] + 99}").status_code == 404


@pytest.mark.parametrize(
    ("encoding", "detail"),
    [
        ({"x": ["nope"], "y": ["y"]}, "unknown columns"),
        ({"x": ["label"], "y": ["y"]}, "numeric"),
        ({"x": ["x"]}, "x and y"),
        ({"x": "x", "y": ["y"]}, "list"),
    ],
)
def test_plot_refuses_bad_encodings(
    client: TestClient, encoding: dict, detail: str
) -> None:
    """A plot with an unknown, text or missing axis column is refused."""
    response = client.post("/api/plot", json={"encoding": encoding, **SIZE})
    assert response.status_code == 400
    assert detail in response.json()["detail"]


def test_view_and_overview_need_a_plot(client: TestClient) -> None:
    """Zooming or resizing before a plot is refused."""
    body = {**SIZE, "x_ranges": [[0, 1]], "y_ranges": [[0, 1]]}
    assert client.post("/api/view", json=body).status_code == 409
    assert client.post("/api/overview", json=SIZE).status_code == 409


def test_view_zooms_and_reuses_an_unchanged_result(client: TestClient) -> None:
    """A zoomed view aggregates again; the same view at the same size does not."""
    _plot(client)
    body = {**SIZE, "x_ranges": [[-1, 1]], "y_ranges": [[-1, 1]]}
    first = client.post("/api/view", json=body).json()["meta"]
    assert first["x_ranges"] == [[-1, 1]]
    again = client.post("/api/view", json=body).json()["meta"]
    assert again["task"] == first["task"]
    assert again["task_seconds"] == 0.0
    bad = {**SIZE, "x_ranges": [], "y_ranges": [[-1, 1]]}
    assert client.post("/api/view", json=bad).status_code == 400


def test_overview_at_another_size(client: TestClient) -> None:
    """The overview at another size aggregates again; at its own size it does not."""
    plotted = _plot(client)["meta"]
    same = client.post("/api/overview", json=SIZE).json()["meta"]
    assert same["task"] == plotted["task"]
    larger = client.post("/api/overview", json={"width": 800, "height": 600})
    resized = larger.json()["meta"]
    assert resized["task"] != plotted["task"]
    assert resized["x_ranges"] == plotted["x_ranges"]


def test_filter_narrows_the_rows(client: TestClient) -> None:
    """A local filter keeps only the matching rows."""
    every = _plot(client)["meta"]["rows"]
    filters = [{"column": "color", "levels": ["a"]}]
    narrowed = _plot(client, filters=filters)["meta"]
    assert narrowed["rows"] < every
    assert narrowed["filters"][0]["column"] == "color"
    bad = client.post(
        "/api/plot",
        json={"encoding": ENCODING, **SIZE, "filters": [{"column": "nope"}]},
    )
    assert bad.status_code == 400


def test_selection_and_table(client: TestClient) -> None:
    """A box selects rows as a layer; the table pages them; a new plot forgets them."""
    meta = _plot(client)["meta"]
    assert client.post("/api/selection", json={"task": meta["task"]}).status_code == 409
    box = {"task": meta["task"], "panel": 0, "x_range": [5, -5], "y_range": [-5, 5]}
    selected = client.post("/api/selection", json=box).json()
    assert selected["base"] == meta["task"]
    assert selected["selection"]["x_range"] == [-5, 5]
    assert selected["selection"]["col"] == "p"
    assert 0 < selected["rows"] < meta["rows"]
    layer = client.get(f"/api/images/{selected['task']}")
    assert layer.status_code == 200

    again = client.post("/api/selection", json={"task": meta["task"]}).json()
    assert again["rows"] == selected["rows"]

    table = client.get("/api/table").json()
    assert table["rows"] == selected["rows"]
    assert table["plot_columns"] == 4
    assert [c["name"] for c in table["columns"]][:4] == ["x", "y", "color", "facet"]
    assert table["total_columns"] == 5

    no_panel = {**box, "panel": 9}
    assert client.post("/api/selection", json=no_panel).status_code == 400
    assert client.delete("/api/selection").json() == {}
    assert client.get("/api/table").status_code == 409


def test_summary(client: TestClient) -> None:
    """The filter pane's summary of a column; an unknown column is refused."""
    summary = client.get("/api/summary", params={"column": "color"}).json()
    assert summary["column"] == "color"
    assert client.get("/api/summary", params={"column": "nope"}).status_code == 400


@pytest.fixture
def folder_client(tmp_path: Path, folder_path: Path) -> Iterator[TestClient]:
    """Serve the folder `folder_path` with the token in a cookie."""
    app = create_app(
        str(folder_path),
        False,
        tmp_path / "run",
        tmp_path / "cache",
        Settings(),
        TOKEN,
    )
    (tmp_path / "run").mkdir()
    with TestClient(app) as started:
        assert started.get("/", params={"token": TOKEN}).status_code == 200
        yield started


def test_a_folder_plots_selects_and_lists_as_one_table(
    folder_client: TestClient, folder_frame: pl.DataFrame
) -> None:
    """A folder's files read as one table: its casts are told, and plot, table and summary work."""
    client = folder_client
    source = client.get("/api/source").json()
    assert source["files"] == 3
    assert source["rows"] == folder_frame.height
    assert source["casts"] == [
        {"name": "n", "dtypes": ["Int32", "Int64"], "dtype": "Int64"}
    ]
    schema = client.get("/api/schema").json()
    assert [c["name"] for c in schema] == folder_frame.columns
    meta = _plot(client)["meta"]
    assert (
        meta["rows"]
        == folder_frame.filter(
            pl.col("x").is_finite(), pl.col("color").is_not_null()
        ).height
    )
    box = {"task": meta["task"], "panel": 0, "x_range": [-5, 5], "y_range": [-5, 5]}
    selected = client.post("/api/selection", json=box).json()
    table = client.get("/api/table").json()
    assert table["rows"] == selected["rows"]
    names = [c["name"] for c in table["columns"]]
    assert names == ["x", "y", "color", "facet", "label", "n"]
    rows = folder_frame[table["index"]]
    columns = {c["name"]: c["values"] for c in table["columns"]}
    assert columns["label"] == rows["label"].to_list()
    assert columns["n"] == rows["n"].to_list()
    summary = client.get("/api/summary", params={"column": "n"}).json()
    assert summary["nulls"] == folder_frame["n"].null_count()


def test_the_hover_limit_is_shared_by_the_overview_and_the_view(
    client: TestClient, tmp_path: Path, scatter_path: Path
) -> None:
    """A view gets the room the overview leaves; without room for x and y it has no hover.

    The results a task replaces count too: they go only once the new one
    is open, so they are on disk while it is written.
    """
    unlimited = _plot(client)["meta"]["hover"]
    assert unlimited["files"] and unlimited["dropped"] == []
    settings = Settings(hover=HoverSettings(max_temp_bytes=unlimited["bytes"] + 1000))
    app = create_app(
        str(scatter_path),
        False,
        tmp_path / "limited",
        tmp_path / "cache",
        settings,
        TOKEN,
    )
    (tmp_path / "limited").mkdir()
    with TestClient(app) as limited:
        limited.get("/", params={"token": TOKEN})
        meta = _plot(limited)["meta"]
        assert meta["hover"]["files"] and meta["hover"]["dropped"] == []
        assert meta["hover"]["kept"] == ["x", "y", "color", "facet"]
        body = {**SIZE, "x_ranges": [[-1, 1]], "y_ranges": [[-1, 1]]}
        view = limited.post("/api/view", json=body).json()["meta"]
        assert view["hover"]["files"] is False
        assert view["hover"]["dropped"] == ["x", "y", "color", "facet"]
        assert view["hover"]["limit_gb"] == settings.hover.max_temp_bytes / 2**30
        params = {"task": view["task"], "panel": 0, "fx": 0, "fy": 0, "sx": 1, "sy": 1}
        assert limited.get("/api/hover", params=params).json() == {"hit": None}
        # A new plot is written beside the old overview, which leaves no room.
        again = _plot(limited)["meta"]["hover"]
        assert again["files"] is False
        assert meta["hover"]["bytes"] + again["bytes"] <= settings.hover.max_temp_bytes
        # The old results are gone now, so the next plot has the whole limit.
        assert _plot(limited)["meta"]["hover"]["files"]
