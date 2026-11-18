"""Tests of saved settings reaching a running UI server: the next request or task uses them, without building the server again."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ddviz.server import source as source_module
from ddviz.server.app import create_app
from ddviz.server.settings import Settings
from ddviz.server.settings_store import SettingsStore
from ddviz.server.source import Source
from tests.server.test_app import ENCODING, HIDE_NULLS, SIZE, TOKEN


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    """Return the settings of a shared file in a folder of its own, which saves write beside."""
    path = tmp_path / "config" / "settings.toml"
    path.parent.mkdir()
    path.write_text("[columns]\nmax_listed = 2\nmax_history = 3\n", encoding="utf-8")
    return SettingsStore.load(path)


def _serve(tmp_path: Path, scatter_path: Path, store: SettingsStore) -> TestClient:
    """Return a server of `scatter_path` reading `store`."""
    app = create_app(
        [str(scatter_path)],
        False,
        tmp_path / "run",
        tmp_path / "cache",
        tmp_path / "history",
        store,
        TOKEN,
    )
    (tmp_path / "run").mkdir()
    return TestClient(app)


@pytest.fixture
def client(
    tmp_path: Path, scatter_path: Path, store: SettingsStore
) -> Iterator[TestClient]:
    """Serve `scatter_path` with `store`, the token already used."""
    with _serve(tmp_path, scatter_path, store) as started:
        started.get("/", params={"token": TOKEN})
        yield started


def _plot(client: TestClient, encoding: dict = ENCODING) -> object:
    """Draw `encoding` and return the response."""
    return client.post("/api/plot", json={"encoding": encoding, **SIZE, **HIDE_NULLS})


def test_the_page_settings_follow_a_save(client: TestClient, store: SettingsStore) -> None:
    """``GET /api/settings`` gives the values saved since the server started."""
    assert client.get("/api/settings").json()["inactive_opacity"] == 0.15
    store.save({"plot.legend.inactive_opacity": 0.6, "plot.max_levels": 9})
    found = client.get("/api/settings").json()
    assert (found["inactive_opacity"], found["max_levels"]) == (0.6, 9)


def test_the_column_list_follows_a_save(client: TestClient, store: SettingsStore) -> None:
    """The next search lists as many columns as ``columns.max_listed`` saved."""
    assert len(client.get("/api/columns").json()["columns"]) == 2
    store.save({"columns.max_listed": 4})
    assert len(client.get("/api/columns").json()["columns"]) == 4


def test_the_history_follows_a_save_without_cutting_the_file(
    client: TestClient, store: SettingsStore, tmp_path: Path
) -> None:
    """A lower ``columns.max_history`` shows fewer keywords at once but cuts the file only at the next write, with the new limit."""
    for word in ("a", "b", "c"):
        client.post("/api/search-history", json={"word": word})
    assert client.get("/api/search-history").json()["words"] == ["c", "b", "a"]
    (file,) = (tmp_path / "history").iterdir()
    written = file.read_text(encoding="utf-8")
    store.save({"columns.max_history": 2})
    assert client.get("/api/search-history").json()["words"] == ["c", "b"]
    assert file.read_text(encoding="utf-8") == written
    assert client.post("/api/search-history", json={"word": "d"}).json()["words"] == ["d", "c"]
    store.save({"columns.max_history": 5})
    assert client.get("/api/search-history").json()["words"] == ["d", "c"]


def test_the_limit_of_levels_follows_a_save_and_keeps_the_drawn_plot(
    client: TestClient, store: SettingsStore
) -> None:
    """A lower ``plot.max_levels`` refuses the next plot of a color of 3 levels; the drawn results stay, and a higher limit draws again."""
    first = _plot(client)
    assert first.status_code == 200, first.text
    task = first.json()["meta"]["task"]
    store.save({"plot.max_levels": 2})
    assert _plot(client).status_code != 200
    # The results drawn before stay: their images are still served.
    assert client.get(f"/api/images/{task}").status_code == 200
    assert client.post("/api/view", json={**SIZE, "x_ranges": [[-1, 1]], "y_ranges": [[-1, 1]]}).status_code == 200
    store.save({"plot.max_levels": 3})
    assert _plot(client).status_code == 200


def _filtered_plot(client: TestClient, levels: list[str]) -> object:
    """Draw `ENCODING` with the filter keeping the color `levels` and return the response."""
    filters = [{"column": "color", "levels": levels}]
    return client.post(
        "/api/plot", json={"encoding": ENCODING, **SIZE, **HIDE_NULLS, "filters": filters}
    )


def test_a_higher_limit_of_levels_reaches_a_new_filter_of_the_drawn_plot(
    client: TestClient, store: SettingsStore
) -> None:
    """A plot drawn under ``plot.max_levels = 2`` with 2 color levels takes, after a save of 3, the filter of all 3."""
    store.save({"plot.max_levels": 2})
    drawn = _filtered_plot(client, ["a", "b"])
    assert drawn.status_code == 200, drawn.text
    assert drawn.json()["meta"]["series"] == ["a", "b"]
    store.save({"plot.max_levels": 3})
    overview = client.post("/api/overview", json={**SIZE, "filters": []})
    assert overview.status_code == 200, overview.text
    assert overview.json()["meta"]["series"] == ["a", "b", "c"]


def test_a_lower_limit_of_levels_refuses_a_new_filter_of_the_drawn_plot(
    client: TestClient, store: SettingsStore
) -> None:
    """A plot drawn under ``plot.max_levels = 3`` with 2 color levels refuses, after a save of 2, a filter of 3 levels with the new limit."""
    store.save({"plot.max_levels": 3})
    drawn = _filtered_plot(client, ["a", "b"])
    assert drawn.status_code == 200, drawn.text
    store.save({"plot.max_levels": 2})
    filters = [{"column": "color", "levels": ["a", "b", "c"]}]
    refused = client.post("/api/overview", json={**SIZE, "filters": filters})
    assert refused.status_code == 400
    assert refused.json()["error"] == "filtered_levels"
    assert "上限 2 個" in refused.json()["detail"]


def test_the_limit_of_axis_levels_follows_a_save(
    client: TestClient, store: SettingsStore
) -> None:
    """A lower ``plot.max_axis_levels`` refuses the next plot of a categorical x of 3 levels."""
    encoding = {"x": ["color"], "y": ["y"]}
    assert _plot(client, encoding).status_code == 200
    store.save({"plot.max_axis_levels": 2})
    assert _plot(client, encoding).status_code != 200
    store.save({"plot.max_axis_levels": 3})
    assert _plot(client, encoding).status_code == 200


def test_the_hover_limit_follows_a_save_and_keeps_the_open_hover(
    client: TestClient, store: SettingsStore
) -> None:
    """A tiny ``hover.max_temp_gb`` gives the next view no hover files, while the overview drawn before keeps its own; the room left is never below 0."""
    meta = _plot(client).json()["meta"]
    assert meta["hover"]["files"]
    store.save({"hover.max_temp_gb": 1 / 2**30})
    body = {**SIZE, "x_ranges": [[-1, 1]], "y_ranges": [[-1, 1]]}
    view = client.post("/api/view", json=body).json()["meta"]
    assert view["hover"]["files"] is False
    assert view["hover"]["limit_gb"] == 1 / 2**30
    params = {"task": meta["task"], "panel": 0, "fx": 0, "fy": 0, "sx": 1, "sy": 1}
    assert client.get("/api/hover", params=params).status_code == 200
    store.save({"hover.max_temp_gb": 2})
    assert _plot(client).json()["meta"]["hover"]["files"]


class _Switching(SettingsStore):
    """Settings that a save replaces right after the first read, as when the user applies while a plot runs."""

    def __init__(self, first: Settings, then: Settings) -> None:
        super().__init__(first)
        self.then = then
        self.reads = 0

    @property
    def current(self) -> Settings:
        """The first snapshot once; `then` afterwards."""
        self.reads += 1
        return self._settings if self.reads == 1 else self.then


def test_a_plot_uses_one_snapshot_from_its_start(
    tmp_path: Path, scatter_path: Path
) -> None:
    """A plot started before a save checks its levels and sizes its hover with the settings it started with; the next plot takes the new ones."""
    tiny = 1 / 2**30
    first = Settings()
    then = Settings(
        plot=type(first.plot)(max_levels=1),
        hover=type(first.hover)(max_temp_gb=tiny),
    )
    switching = _Switching(first, then)
    with _serve(tmp_path, scatter_path, switching) as client:
        client.get("/", params={"token": TOKEN})
        # Load reads the cache's limits; the plot's read is the next one.
        client.get("/api/schema")
        switching.reads = 0
        response = _plot(client)
        assert response.status_code == 200, response.text
        hover = response.json()["meta"]["hover"]
        assert hover["files"]
        assert hover["limit_gb"] == first.hover.max_temp_gb
        assert _plot(client).status_code != 200


def test_the_next_cleaning_of_the_cache_takes_the_saved_limits(
    tmp_path: Path, store: SettingsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each cleaning of the column cache reads the limits in effect when it starts, and keeps the files in use."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        source_module, "evict", lambda root, size, days, keep: calls.append((size, days, keep))
    )
    source = Source(
        [str(tmp_path / "none.parquet")],
        False,
        tmp_path / "cache",
        tmp_path / "index",
        lambda: store.current.cache,
        None,
    )
    kept = [tmp_path / "in-use.arrow"]
    source.evict(kept)
    store.save({"cache.max_gb": 0.5, "cache.max_unused_days": 0})
    assert calls == [(10 * 2**30, 30, kept)]
    source.evict(kept)
    assert calls == [(10 * 2**30, 30, kept), (2**29, 0, kept)]
