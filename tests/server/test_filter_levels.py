"""`GET /api/filter-levels`: the search of a categorical column's levels for a filter card, with real worker processes."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from ddviz.server.app import create_app
from ddviz.server.broker import TaskBroker, TaskEnd
from ddviz.server.settings import Settings
from ddviz.shared.tasks import LevelIndexTask, Task

TOKEN = "secret-of-the-run"


def _serve(tmp_path: Path, paths: list[Path]) -> Iterator[TestClient]:
    """Serve an input with the token in a cookie."""
    run = tmp_path / "run"
    run.mkdir()
    app = create_app(
        [str(p) for p in paths],
        False,
        run,
        tmp_path / "cache",
        tmp_path / "history",
        Settings(),
        TOKEN,
    )
    with TestClient(app) as client:
        assert client.get("/", params={"token": TOKEN}).status_code == 200
        yield client


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Serve a file of a categorical column ``id`` of 150 levels, a number and a date."""
    ids = [f"ID{i}" for i in range(150)] + ["ID7"] * 3 + ["ABC", "abc", "ABC-123", None]
    frame = pl.DataFrame(
        {
            "id": ids,
            "n": list(range(len(ids))),
            "d": [dt.date(2026, 1, 1)] * len(ids),
        }
    )
    path = tmp_path / "levels.parquet"
    frame.write_parquet(path)
    yield from _serve(tmp_path, [path])


@pytest.fixture
def tasks(monkeypatch: pytest.MonkeyPatch) -> list[Task]:
    """Record the tasks sent to the levels pool."""
    sent: list[Task] = []
    run = TaskBroker.run

    async def spy(self: TaskBroker, task: Task, pool: str = "plot") -> TaskEnd:
        if pool == "levels":
            sent.append(task)
        return await run(self, task, pool)

    monkeypatch.setattr(TaskBroker, "run", spy)
    return sent


def _levels(client: TestClient, **params: str) -> dict:
    """Return the answer of a search that succeeds."""
    answer = client.get("/api/filter-levels", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_levels_found_and_their_shape(client: TestClient) -> None:
    """A blank search lists the first 100 by name, of all the levels; a query and Count narrow and order them."""
    found = _levels(client, column="id")
    assert found["n_levels"] == 153
    assert found["truncated"] is True
    assert len(found["levels"]) == 100
    assert found["levels"][:3] == [["ABC", 1], ["abc", 1], ["ABC-123", 1]]
    by_count = _levels(client, column="id", q="ID7", order="count")
    assert by_count == {
        "levels": [["ID7", 4], *([f"ID{i}", 1] for i in range(70, 80))],
        "truncated": False,
        "n_levels": 153,
    }
    assert _levels(client, column="id", q="zzz")["levels"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"column": "nope"},
        {"column": "n"},
        {"column": "d"},
        {"column": "id", "order": "size"},
    ],
)
def test_bad_requests_are_refused(client: TestClient, params: dict) -> None:
    """An unknown column, a numeric or date column and an unknown order are 400."""
    assert client.get("/api/filter-levels", params=params).status_code == 400


def test_a_second_search_reads_the_index_only(
    client: TestClient, tasks: list[Task]
) -> None:
    """The first search writes the index; later ones, of any query and order, only search it."""
    _levels(client, column="id")
    _levels(client, column="id", q="ID1", order="count")
    _levels(client, column="id", order="count")
    kinds = [t.KIND for t in tasks if t.KIND != "convert"]
    assert kinds == ["level_index", "level_search", "level_search", "level_search"]


def test_a_failed_index_is_written_again(
    client: TestClient, tasks: list[Task], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An index task that fails fails the search; the next search writes the index again."""
    run = TaskBroker.run
    failed: list[Task] = []

    async def fail_once(self: TaskBroker, task: Task, pool: str = "plot") -> TaskEnd:
        if isinstance(task, LevelIndexTask) and not failed:
            failed.append(task)
            Path(task.index + ".partial").write_bytes(b"half")
            return TaskEnd(0, Path(task.index).parent / "none", {"type": "error", "message": "boom"})
        return await run(self, task, pool)

    monkeypatch.setattr(TaskBroker, "run", fail_once)
    answer = client.get("/api/filter-levels", params={"column": "id"})
    assert answer.status_code == 500
    assert "boom" in answer.text
    assert not Path(failed[0].index + ".partial").exists()
    assert _levels(client, column="id")["n_levels"] == 153
    kinds = [t.KIND for t in tasks if t.KIND != "convert"]
    assert kinds == ["level_index", "level_search"]


def test_the_added_columns_of_several_files_are_searched(
    tmp_path: Path, folder_path: Path, folder_frame: pl.DataFrame
) -> None:
    """The source and filename columns of several files list their files with their rows."""
    files = ["part-10.parquet", "part-1.parquet", "part-2.parquet"]
    for client in _serve(tmp_path, [folder_path / f for f in files]):
        for column in ("source", "filename"):
            found = _levels(client, column=column, order="count")
            assert found["n_levels"] == 3
            assert sum(n for _, n in found["levels"]) == folder_frame.height
        names = [v for v, _ in _levels(client, column="filename")["levels"]]
        assert names == ["part-1", "part-2", "part-10"]
