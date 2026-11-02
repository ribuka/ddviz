"""Tests of the UI server's HTTP API, with real worker processes."""

from __future__ import annotations

import io
import re
import time
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from ddviz.server.app import create_app
from ddviz.server.auth import COOKIE
from ddviz.server.settings import ColumnsSettings, HoverSettings, Settings
from ddviz.shared.scatter import POINT_SIZE

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


def test_columns_carry_their_non_null_rows(
    client: TestClient, scatter_frame: pl.DataFrame
) -> None:
    """Once counted after Load, each column carries its rows with a value and their share."""
    deadline = time.monotonic() + 30
    found = client.get("/api/columns").json()
    while found["shares"] == "pending" and time.monotonic() < deadline:
        time.sleep(0.1)
        found = client.get("/api/columns").json()
    assert found["shares"] == "done"
    rows = scatter_frame.height
    assert found["rows"] == rows
    counts = {c: rows - scatter_frame[c].null_count() for c in scatter_frame.columns}
    for column in found["columns"]:
        assert column["nonnull"] == counts[column["name"]]
        assert column["share"] == counts[column["name"]] / rows


def test_columns_list_as_many_as_the_settings_allow(
    tmp_path: Path, scatter_path: Path
) -> None:
    """The search returns ``columns.max_listed`` columns at most, whatever the page asks."""
    settings = Settings(columns=ColumnsSettings(max_listed=2))
    app = create_app(
        str(scatter_path), False, tmp_path / "run", tmp_path / "cache", settings, TOKEN
    )
    (tmp_path / "run").mkdir()
    with TestClient(app) as started:
        started.get("/", params={"token": TOKEN})
        found = started.get("/api/columns", params={"limit": 200}).json()
    assert found["matched"] == 5
    assert [c["name"] for c in found["columns"]] == ["x", "y"]


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
        ({"x": ["x"], "y": ["y"], "elements": []}, "elements"),
        ({"x": ["x"], "y": ["y"], "elements": "points"}, "elements"),
        ({"x": ["x"]}, "x and y"),
        ({"y": ["color"]}, "x and y"),
        ({"y": ["y", "color"]}, "x and y"),
        ({"x": "x", "y": ["y"]}, "list"),
        ({"x": ["x"], "y": ["y"], "wrap": "facet", "col": "color"}, "wrap"),
        ({"x": ["x", "y"], "y": ["y"], "wrap": "facet"}, "n-th axes"),
    ],
)
def test_plot_refuses_bad_encodings(
    client: TestClient, encoding: dict, detail: str
) -> None:
    """A plot with an unknown or missing axis column, no element, or wrap beside a facet or an n-th axis, is refused."""
    response = client.post("/api/plot", json={"encoding": encoding, **SIZE})
    assert response.status_code == 400
    assert detail in response.json()["detail"]


def test_plot_wraps_a_column_and_refuses_a_bad_wrap_cols(client: TestClient) -> None:
    """A wrapped column makes a panel per level; wrap_cols must be a positive int."""
    encoding = {"x": ["x"], "y": ["y"], "wrap": "facet"}
    response = client.post(
        "/api/plot", json={"encoding": encoding, **SIZE, "wrap_cols": 1}
    )
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert [p["facet"] for p in meta["panels"]] == [[None, "p"], [None, "q"]]
    assert meta["ncol"] == 1
    assert meta["encoding"]["wrap"] == "facet"
    bad = client.post("/api/plot", json={"encoding": encoding, **SIZE, "wrap_cols": 0})
    assert bad.status_code == 400


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


def test_a_graph_without_x_draws_one_band(client: TestClient) -> None:
    """Without an x column, numeric y columns have their boxes in one band; a box selects rows of it."""
    encoding = {"y": ["y"], "color": "color", "elements": ["box"]}
    response = client.post("/api/plot", json={"encoding": encoding, **SIZE})
    assert response.status_code == 200, response.text
    body = response.json()
    meta = body["meta"]
    assert meta["one_band"] is True
    assert meta["undrawn"] == []
    assert meta["x_ranges"] == [[-0.5, 0.5]]
    assert {b[1] for p in meta["panels"] for b in p["boxes"]} == {0, 1, 2}
    assert body["figure"]["layout"]["xaxis"]["ticktext"] == ["a", "b", "c"]
    box = {"task": meta["task"], "panel": 0, "x_range": [-0.5, 0.5], "y_range": [-1, 1]}
    selected = client.post("/api/selection", json=box).json()
    assert 0 < selected["rows"]
    table = client.get("/api/table").json()
    assert table["rows"] == selected["rows"]
    assert [c["name"] for c in table["columns"]][:2] == ["y", "color"]


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


def test_a_categorical_axis_plots_zooms_filters_and_selects(client: TestClient) -> None:
    """A text column on x is drawn in bands; a view, another filter, a box and the table follow them."""
    encoding = {"x": ["color"], "y": ["y"], "col": "facet"}
    plotted = client.post("/api/plot", json={"encoding": encoding, **SIZE}).json()
    meta = plotted["meta"]
    assert meta["x_ranges"] == [[-0.5, 2.5]]
    assert plotted["figure"]["layout"]["xaxis"]["ticktext"] == ["a", "b", "c"]
    assert meta["rows"] == 2002

    view = {**SIZE, "x_ranges": [[0.5, 1.5]], "y_ranges": meta["y_ranges"]}
    zoomed = client.post("/api/view", json=view).json()["meta"]
    assert 0 < zoomed["rows"] < meta["rows"]
    filters = [{"column": "facet", "levels": ["p"]}]
    narrowed = client.post("/api/overview", json={**SIZE, "filters": filters})
    narrowed = narrowed.json()["meta"]
    assert 0 < narrowed["rows"] < meta["rows"]

    box = {
        "task": narrowed["task"],
        "panel": 0,
        "x_range": [0.5, 1.5],
        "y_range": [-5, 5],
    }
    selected = client.post("/api/selection", json=box).json()
    assert 0 < selected["rows"]
    table = client.get("/api/table").json()
    assert table["rows"] == selected["rows"]
    assert {
        v for c in table["columns"] if c["name"] == "color" for v in c["values"]
    } == {"b"}


def test_box_plots_plot_zoom_filter_and_select(client: TestClient) -> None:
    """Box plots of y by a text column: the figure holds them, a zoom keeps them, a filter finds them again, and a box selects by level."""
    encoding = {"x": ["color"], "y": ["y"], "elements": ["box"]}
    plotted = client.post("/api/plot", json={"encoding": encoding, **SIZE}).json()
    meta = plotted["meta"]
    assert meta["undrawn"] == []
    (panel,) = meta["panels"]
    assert panel["points"] is False
    assert [b[0] for b in panel["boxes"]] == [0, 1, 2]
    assert sum(b[2] for b in panel["boxes"]) == 2002
    # Only the outliers are drawn as points.
    assert 0 < meta["rows"] < 2002
    # A box over part of the band of b selects its rows, inside the box plot too.
    box = {"task": meta["task"], "panel": 0, "x_range": [0.7, 1.1], "y_range": [-9, 9]}
    selected = client.post("/api/selection", json=box).json()
    assert selected["rows"] == panel["boxes"][1][2]

    view = {**SIZE, "x_ranges": [[0.5, 2.5]], "y_ranges": meta["y_ranges"]}
    zoomed = client.post("/api/view", json=view).json()["meta"]
    assert zoomed["panels"][0]["boxes"] == panel["boxes"]
    filters = [{"column": "facet", "levels": ["p"]}]
    narrowed = client.post("/api/overview", json={**SIZE, "filters": filters})
    boxes = narrowed.json()["meta"]["panels"][0]["boxes"]
    assert 0 < sum(b[2] for b in boxes) < 2002

    numeric_x = {"x": ["x"], "y": ["y"], "elements": ["box"]}
    plotted = client.post("/api/plot", json={"encoding": numeric_x, **SIZE}).json()
    assert plotted["meta"]["undrawn"] == ["box"]
    assert plotted["meta"]["panels"][0]["points"] is True


def test_smoothing_lines_plot_zoom_filter_and_select(client: TestClient) -> None:
    """Smoothing lines of y on x: one per facet cell and series, kept by a zoom, fitted again for a filter, and of the method asked for."""
    encoding = {**ENCODING, "elements": ["smooth"]}
    plotted = client.post("/api/plot", json={"encoding": encoding, **SIZE}).json()
    meta = plotted["meta"]
    assert meta["undrawn"] == []
    assert [p["points"] for p in meta["panels"]] == [False, False]
    # Without points, no row is drawn as one.
    assert meta["rows"] == 0
    for panel in meta["panels"]:
        assert sorted(line[0] for line in panel["smooths"]) == [0, 1, 2]
        for _, xs, ys in panel["smooths"]:
            assert len(xs) == len(ys) > 2
            assert xs == sorted(xs)
    lines = meta["panels"][0]["smooths"]
    box = {"task": meta["task"], "panel": 0, "x_range": [-9, 9], "y_range": [-9, 9]}
    selected = client.post("/api/selection", json=box).json()
    assert 0 < selected["rows"] < 2002

    view = {**SIZE, "x_ranges": [[-1, 1]], "y_ranges": meta["y_ranges"]}
    zoomed = client.post("/api/view", json=view).json()["meta"]
    assert zoomed["panels"][0]["smooths"] == lines
    filters = [{"column": "x", "range": [0, 5]}]
    narrowed = client.post("/api/overview", json={**SIZE, "filters": filters})
    narrowed_lines = narrowed.json()["meta"]["panels"][0]["smooths"]
    assert min(x for _, xs, _ in narrowed_lines for x in xs) >= 0

    lowess = client.post(
        "/api/plot",
        json={
            "encoding": {**encoding, "elements": ["points", "smooth"]},
            **SIZE,
            "smooth": {"method": "lowess", "frac": 0.3},
        },
    ).json()["meta"]
    assert lowess["rows"] == 2000
    assert lowess["panels"][0]["smooths"] != lines
    bad = client.post(
        "/api/plot",
        json={"encoding": encoding, **SIZE, "smooth": {"method": "spline"}},
    )
    assert bad.status_code == 400
    banded = {"x": ["color"], "y": ["y"], "elements": ["smooth"]}
    plotted = client.post("/api/plot", json={"encoding": banded, **SIZE}).json()
    assert plotted["meta"]["undrawn"] == ["smooth"]
    assert plotted["meta"]["panels"][0]["points"] is True


def test_overlay_plots_shapes_selects_and_hovers(client: TestClient) -> None:
    """Overlay beside color draws a series per pair of levels in the size asked; alone, it colors the series."""
    encoding = {"x": ["x"], "y": ["y"], "color": "color", "overlay": "facet"}
    plotted = client.post(
        "/api/plot", json={"encoding": encoding, **SIZE, "shape_size": 9}
    ).json()
    meta = plotted["meta"]
    assert meta["undrawn"] == []
    assert meta["series"] == ["a", "b", "c"]
    assert meta["color"]["shapes"] == 2
    assert meta["overlay"]["column"] == "facet"
    assert meta["overlay"]["levels"] == ["p", "q"]
    assert meta["marker_size"] == 9
    assert [len(k) for k in meta["overlay"]["kernels"]] == [9, 9]
    assert len(meta["images"]) == 6 and all(meta["images"])
    assert meta["grid"]["n_series"] == 6
    hover = client.get(
        "/api/hover",
        params={
            "task": meta["task"],
            "panel": 0,
            "fx": meta["grid"]["width"] / 2,
            "fy": meta["grid"]["height"] / 2,
            "sx": 1,
            "sy": 1,
            "order": ",".join(str(s) for s in range(5, -1, -1)),
        },
    ).json()["hit"]
    assert hover["values"]["color"] == "abc"[hover["series"] // 2]
    assert hover["values"]["facet"] == "pq"[hover["series"] % 2]
    box = {"task": meta["task"], "panel": 0, "x_range": [-5, 5], "y_range": [-5, 5]}
    selected = client.post("/api/selection", json=box).json()
    assert 0 < selected["rows"] <= meta["rows"]
    assert len(selected["images"]) == 6

    alone = {"x": ["x"], "y": ["y"], "overlay": "facet"}
    meta = client.post("/api/plot", json={"encoding": alone, **SIZE}).json()["meta"]
    assert meta["series"] == ["p", "q"]
    assert meta["color"]["column"] == "facet"
    assert meta["overlay"] is None
    # The circles of the points without an overlay take the smaller default.
    assert meta["marker_size"] == POINT_SIZE

    bad = {"encoding": encoding, **SIZE, "shape_size": 8}
    assert client.post("/api/plot", json=bad).status_code == 400

    # A level takes a size of its own; the others keep the size of every series.
    meta = client.post(
        "/api/plot",
        json={"encoding": encoding, **SIZE, "shape_size": 9, "shape_sizes": {"q": 3}},
    ).json()["meta"]
    assert meta["marker_size"] == 9
    assert meta["overlay"]["sizes"] == [9, 3]
    assert [len(k) for k in meta["overlay"]["kernels"]] == [9, 3]
    bad = {"encoding": encoding, **SIZE, "shape_sizes": {"q": 4}}
    assert client.post("/api/plot", json=bad).status_code == 400


def test_plot_data_saves_the_overview_bins(client: TestClient) -> None:
    """The data of a plot is its overview's bins, as CSV or Parquet, whatever the zoom."""
    meta = _plot(client)["meta"]
    url = f"/api/plot-data/{meta['task']}"
    response = client.get(url, params={"format": "parquet"})
    assert response.status_code == 200, response.text
    assert re.fullmatch(
        r'attachment; filename="scatter_\d{8}-\d{6}\.parquet"',
        response.headers["content-disposition"],
    )
    table = pl.read_parquet(io.BytesIO(response.content))
    assert table.columns == [
        "x_column",
        "x_lo",
        "x_hi",
        "y_column",
        "y_lo",
        "y_hi",
        "group_x",
        "color",
        "count",
    ]
    assert table["count"].sum() == meta["rows"]
    assert set(table["x_column"]) == {"x"}
    assert set(table["group_x"]) == {"p", "q"}
    assert set(table["color"]) == {"a", "b", "c"}
    assert (table["x_lo"] < table["x_hi"]).all()
    (lo, hi), width = meta["x_ranges"][0], SIZE["width"]
    assert table["x_lo"].min() >= lo
    assert table["x_hi"].max() <= hi + (hi - lo) / width

    # A zoom does not change it; the CSV holds the same table.
    view = {**SIZE, "x_ranges": [[-1, 1]], "y_ranges": [[-1, 1]]}
    assert client.post("/api/view", json=view).status_code == 200
    csv = client.get(url, params={"format": "csv"})
    assert csv.content.startswith("﻿".encode())
    assert csv.headers["content-disposition"].endswith('.csv"')
    assert pl.read_csv(io.BytesIO(csv.content)).equals(table)

    assert client.get(url, params={"format": "xlsx"}).status_code == 400
    stale = f"/api/plot-data/{meta['task'] + 99}"
    assert client.get(stale, params={"format": "csv"}).status_code == 404


def test_plot_data_of_a_categorical_axis_has_its_levels(client: TestClient) -> None:
    """A categorical x gives each bin's level; a wrapped grid names its levels wrap."""
    encoding = {"x": ["color"], "y": ["y"], "color": "color", "wrap": "facet"}
    meta = client.post("/api/plot", json={"encoding": encoding, **SIZE}).json()["meta"]
    response = client.get(
        f"/api/plot-data/{meta['task']}", params={"format": "parquet"}
    )
    table = pl.read_parquet(io.BytesIO(response.content))
    assert "x_level" in table.columns
    assert "y_level" not in table.columns
    assert set(table["wrap"]) == {"p", "q"}
    assert (table["x_level"] == table["color"]).all()
    assert table["count"].sum() == meta["rows"]


def test_plot_data_needs_the_hover_files(tmp_path: Path, scatter_path: Path) -> None:
    """A result without hover files kept no bins: its data is refused with the reason."""
    settings = Settings(hover=HoverSettings(max_temp_bytes=1))
    app = create_app(
        str(scatter_path), False, tmp_path / "run", tmp_path / "cache", settings, TOKEN
    )
    (tmp_path / "run").mkdir()
    with TestClient(app) as limited:
        limited.get("/", params={"token": TOKEN})
        meta = _plot(limited)["meta"]
        assert meta["hover"]["files"] is False
        response = limited.get(
            f"/api/plot-data/{meta['task']}", params={"format": "csv"}
        )
        assert response.status_code == 409
        assert "ホバー" in response.json()["detail"]
