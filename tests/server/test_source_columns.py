"""The columns added to an input of several files: each row's source file and its name."""

from __future__ import annotations

import asyncio
import io
import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ddviz.server.broker import TaskEnd
from ddviz.server.settings import CacheSettings
from ddviz.server.source import Source

SIZE = {"width": 400, "height": 300}
HIDE_NULLS = {"show_nulls": False}
EVERYWHERE = {"panel": 0, "x_range": [-100, 100], "y_range": [-100, 100]}


def write_parquet_file(path: Path, frame: pl.DataFrame) -> Path:
    """Write a frame as Parquet, making its folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return path


def _frame(xs: list[float], **columns: list) -> pl.DataFrame:
    """Return a frame with ``x`` and ``y`` equal to `xs`, and other columns."""
    return pl.DataFrame(
        {"x": xs, "y": xs, **columns},
        schema_overrides={"x": pl.Float64, "y": pl.Float64},
    )


@pytest.fixture
def folder(tmp_path: Path) -> tuple[Path, list[Path]]:
    """Return a folder whose files, in reading order, share a name across subfolders.

    ``a/run.01.parquet`` (3 rows) and ``b/run.01.parquet`` (2 rows) have the
    same name in different folders, ``c/empty.parquet`` has no rows, and
    ``z.parquet`` has 1.
    """
    root = tmp_path / "data"
    files = [
        write_parquet_file(
            root / "a" / "run.01.parquet", _frame([0, 1, 2], k=["a0", "a1", "a2"])
        ),
        write_parquet_file(
            root / "b" / "run.01.parquet", _frame([3, 4], k=["b0", "b1"])
        ),
        write_parquet_file(root / "c" / "empty.parquet", _frame([], k=[])),
        write_parquet_file(root / "z.parquet", _frame([5], k=["z0"])),
    ]
    return root, files


def _expected(files: list[Path], rows: list[int]) -> tuple[list[str], list[str]]:
    """Return each row's ``source`` and ``filename`` for files of `rows` rows each."""
    source = [
        str(f.absolute()) for f, n in zip(files, rows, strict=True) for _ in range(n)
    ]
    filename = [f.stem for f, n in zip(files, rows, strict=True) for _ in range(n)]
    return source, filename


def plot_body(client: TestClient, encoding: dict, **extra: object) -> dict:
    """Draw `encoding` and return the response body."""
    response = client.post(
        "/api/plot", json={"encoding": encoding, **SIZE, **HIDE_NULLS, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def first_table_page(client: TestClient, task: int) -> dict:
    """Select every row of a drawn plot and return the first page of the table."""
    selected = client.post("/api/selection", json={"task": task, **EVERYWHERE})
    assert selected.status_code == 200, selected.text
    table = client.get("/api/table")
    assert table.status_code == 200, table.text
    return table.json()


def table_values(table: dict) -> dict[str, list]:
    """Return the values of each column of a table page."""
    return {c["name"]: c["values"] for c in table["columns"]}


def _shares(client: TestClient) -> dict:
    """Wait for the non-null counts after Load and return the columns with them."""
    deadline = time.monotonic() + 30
    found = client.get("/api/columns").json()
    while found["shares"] == "pending" and time.monotonic() < deadline:
        time.sleep(0.1)
        found = client.get("/api/columns").json()
    assert found["shares"] == "done"
    return {c["name"]: c for c in found["columns"]}


XY = {"x": ["x"], "y": ["y"]}


@pytest.mark.parametrize("given", ["folder", "files"])
def test_several_files_add_their_source_and_name(
    serve: Callable[..., AbstractContextManager[TestClient]],
    folder: tuple[Path, list[Path]],
    given: str,
) -> None:
    """A folder, or the same files given directly, add ``source`` and ``filename``.

    Files of the same name in different folders share the name and differ by
    path; a name keeps all its dots but the extension's; a file without rows
    adds none. The values are the same read from the files (no cache) or
    from the column cache, in the filter pane, a filter and a plot's data.
    """
    root, files = folder
    paths = [root] if given == "folder" else list(reversed(files))
    source, filename = _expected(files, [3, 2, 0, 1])
    with serve(paths, recursive=given == "folder") as client:
        schema = client.get("/api/schema").json()
        assert [c["name"] for c in schema] == ["x", "y", "k", "source", "filename"]
        for column in schema[3:]:
            assert column["dtype"] == "String"
            assert not column["numeric"]
            assert column["temporal"] is None
        shares = _shares(client)
        assert shares["source"]["nonnull"] == 6
        assert shares["filename"]["nonnull"] == 6

        # The table reads the added columns from the files: not in the cache.
        meta = plot_body(client, XY)["meta"]
        uncached = first_table_page(client, meta["task"])
        assert uncached["index"] == list(range(6))
        values = table_values(uncached)
        assert values["k"] == ["a0", "a1", "a2", "b0", "b1", "z0"]
        assert values["source"] == source
        assert values["filename"] == filename == ["run.01"] * 5 + ["z"]
        dtypes = {c["name"]: c["dtype"] for c in uncached["columns"]}
        assert dtypes["source"] == dtypes["filename"] == "String"

        # A filter converts them into the cache; the table then reads it.
        every = [{"column": "filename", "levels": ["run.01", "z"]}]
        every.append({"column": "source", "levels": sorted(set(source))})
        meta = plot_body(client, XY, filters=every)["meta"]
        assert meta["rows"] == 6
        cached = first_table_page(client, meta["task"])
        assert cached["index"] == uncached["index"]
        assert table_values(cached) == values

        narrowed = [{"column": "source", "levels": [source[3]]}]
        assert plot_body(client, XY, filters=narrowed)["meta"]["rows"] == 2
        narrowed = [{"column": "filename", "levels": ["z"]}]
        meta = plot_body(client, XY, filters=narrowed)["meta"]
        assert meta["rows"] == 1
        assert first_table_page(client, meta["task"])["index"] == [5]

        summary = client.get("/api/summary", params={"column": "filename"}).json()
        assert dict(map(tuple, summary["levels"])) == {"run.01": 5, "z": 1}
        assert summary["nulls"] == 0

        # A plot colored by the name saves its rows with the names.
        meta = plot_body(client, {**XY, "color": "filename"})["meta"]
        written = client.post(
            f"/api/plot-data/{meta['task']}",
            json={"format": "parquet", "rows": "drawn", "columns": "all", "export": "t"},
        )
        assert written.status_code == 200, written.text
        saved = client.get(f"/api/plot-data/file/{written.json()['file']}")
        rows = pl.read_parquet(io.BytesIO(saved.content))
        counts = rows.group_by("filename").len()
        assert dict(counts.iter_rows()) == {"run.01": 5, "z": 1}


@pytest.mark.parametrize("folder_input", [False, True])
def test_one_file_adds_nothing(
    tmp_path: Path,
    serve: Callable[..., AbstractContextManager[TestClient]],
    folder_input: bool,
) -> None:
    """One file given directly, or a folder of one file, adds no columns."""
    file = write_parquet_file(
        tmp_path / "one" / "only.parquet", _frame([0, 1], k=["a", "b"])
    )
    with serve([file.parent if folder_input else file]) as client:
        schema = client.get("/api/schema").json()
        assert [c["name"] for c in schema] == ["x", "y", "k"]
        meta = plot_body(client, XY)["meta"]
        assert [c["name"] for c in first_table_page(client, meta["task"])["columns"]] == [
            "x",
            "y",
            "k",
        ]


def test_added_names_skip_the_names_of_the_files(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]]
) -> None:
    """Names some file uses keep its values; the added columns take the next free name.

    One file has ``source``, the other ``source_2`` and ``filename``: the
    source path is ``source_3``, and the name ``filename_2``, on its own.
    """
    first = write_parquet_file(
        tmp_path / "in" / "p1.parquet", _frame([0, 1], source=["s", "t"])
    )
    second = write_parquet_file(
        tmp_path / "in" / "p2.parquet",
        _frame([2], source_2=[7], filename=["mine"]),
    )
    with serve([first, second]) as client:
        schema = client.get("/api/schema").json()
        assert [c["name"] for c in schema] == [
            "x",
            "y",
            "source",
            "source_2",
            "filename",
            "source_3",
            "filename_2",
        ]
        meta = plot_body(client, XY)["meta"]
        values = table_values(first_table_page(client, meta["task"]))
        assert values["source"] == ["s", "t", None]
        assert values["source_2"] == [None, None, 7]
        assert values["filename"] == [None, None, "mine"]
        assert values["source_3"] == [str(first)] * 2 + [str(second)]
        assert values["filename_2"] == ["p1", "p1", "p2"]
        filters = [{"column": "source_3", "levels": [str(second)]}]
        meta = plot_body(client, XY, filters=filters)["meta"]
        assert table_values(first_table_page(client, meta["task"]))["filename"] == ["mine"]


def test_a_cache_from_before_the_added_columns_is_read_again(
    tmp_path: Path,
    serve: Callable[..., AbstractContextManager[TestClient]],
    folder: tuple[Path, list[Path]],
) -> None:
    """A stored schema and non-null counts without the added columns are made again."""
    root, _ = folder
    with serve([root], recursive=True) as client:
        _shares(client)
    (stored,) = (tmp_path / "cache").glob("*/schema.json")
    schema = json.loads(stored.read_text(encoding="utf-8"))
    schema["columns"] = schema["columns"][:3]
    del schema["generated"]
    stored.write_text(json.dumps(schema), encoding="utf-8")
    nonnull = stored.parent / "nonnull.json"
    counts = json.loads(nonnull.read_text(encoding="utf-8"))
    counts["counts"] = counts["counts"][:3]
    nonnull.write_text(json.dumps(counts), encoding="utf-8")

    with serve([root], recursive=True) as client:
        schema = client.get("/api/schema").json()
        assert [c["name"] for c in schema][3:] == ["source", "filename"]
        shares = _shares(client)
        assert shares["source"]["nonnull"] == shares["filename"]["nonnull"] == 6


def test_a_replaced_file_moving_a_name_reuses_no_part(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]]
) -> None:
    """A file replaced with one that has ``source`` takes the name from the added column.

    The parts converted for the added ``source`` are not read as the file's
    column, whose other file has nulls, and the added column is ``source_2``.
    """
    first = write_parquet_file(tmp_path / "in" / "p1.parquet", _frame([0, 1]))
    second = write_parquet_file(tmp_path / "in" / "p2.parquet", _frame([2]))
    with serve([first.parent]) as client:
        filters = [{"column": "source", "levels": [str(first), str(second)]}]
        meta = plot_body(client, XY, filters=filters)["meta"]
        assert table_values(first_table_page(client, meta["task"]))["source"] == [
            str(first),
            str(first),
            str(second),
        ]
    write_parquet_file(second, _frame([2, 3], source=["mine", "yours"]))
    with serve([first.parent]) as client:
        names = [c["name"] for c in client.get("/api/schema").json()]
        assert names == ["x", "y", "source", "source_2", "filename"]
        # The summary converts ``source`` into the cache, where the table reads it.
        summary = client.get("/api/summary", params={"column": "source"}).json()
        assert dict(map(tuple, summary["levels"])) == {"mine": 1, "yours": 1}
        assert summary["nulls"] == 2
        client.get("/api/summary", params={"column": "source_2"})
        meta = plot_body(client, XY)["meta"]
        table = first_table_page(client, meta["task"])
        assert table["index"] == [0, 1, 2, 3]
        values = table_values(table)
        assert values["source"] == [None, None, "mine", "yours"]
        assert values["source_2"] == [str(first)] * 2 + [str(second)] * 2


def _alias(real: Path, how: str) -> Path:
    """Return another spelling of a folder: a junction to it, or a path through ``..``."""
    if how == "dotdot":
        (real.parent / "x").mkdir()
        return real.parent / "x" / ".." / real.name
    _winapi = pytest.importorskip("_winapi")
    alias = real.parent / "alias"
    _winapi.CreateJunction(str(real), str(alias))
    return alias


@pytest.mark.parametrize("how", ["junction", "dotdot"])
def test_another_spelling_of_the_input_has_its_own_paths(
    tmp_path: Path,
    serve: Callable[..., AbstractContextManager[TestClient]],
    how: str,
) -> None:
    """The same folder opened by another path, sharing the cache, shows that path.

    The cache knows the input by its resolved path, and the parts of the
    added columns made for one spelling are not read for the other.
    """
    real = tmp_path / "real"
    first = write_parquet_file(real / "a.parquet", _frame([0, 1]))
    second = write_parquet_file(real / "b.parquet", _frame([2]))
    with serve([real]) as client:
        summary = client.get("/api/summary", params={"column": "source"}).json()
        assert dict(map(tuple, summary["levels"])) == {str(first): 2, str(second): 1}
    alias = _alias(real, how)
    expected = [str((alias / "a.parquet").absolute())] * 2
    expected.append(str((alias / "b.parquet").absolute()))
    assert expected[0] != str(first)
    with serve([alias]) as client:
        assert len(list((tmp_path / "cache").glob("*/source.json"))) == 1
        meta = plot_body(client, XY)["meta"]
        assert table_values(first_table_page(client, meta["task"]))["source"] == expected
        filters = [{"column": "source", "levels": [expected[2]]}]
        meta = plot_body(client, XY, filters=filters)["meta"]
        assert table_values(first_table_page(client, meta["task"]))["source"] == expected[2:]


class _RecordingBroker:
    """A broker whose conversion task records `Source.converting` and ends as told."""

    def __init__(self, end: str) -> None:
        self.end = end
        self.seen: list[bool] = []
        self.source: Source | None = None

    async def run(self, task: object, pool: str = "plot") -> TaskEnd:
        self.seen.append(self.source.converting)
        await asyncio.sleep(0)
        message = {"type": self.end, "message": "the conversion failed"}
        return TaskEnd(0, self.out, message)


def _converting_source(
    tmp_path: Path, missing: dict[str, list[int]], end: str = "done"
) -> tuple[Source, _RecordingBroker, list[bool]]:
    """Return a source whose columns miss `missing`, its broker, and what checking saw.

    Checking for missing parts records `Source.converting` meanwhile.
    """
    broker = _RecordingBroker(end)
    broker.out = tmp_path / "task"
    source = Source(
        [str(tmp_path / "a.parquet")],
        False,
        tmp_path / "cache",
        tmp_path / "index",
        lambda: CacheSettings(),
        broker,
    )
    broker.source = source
    source.cache = SimpleNamespace(dir=tmp_path / "cache")
    source.files = [tmp_path / "a.parquet"]
    source._dtypes = {"x": "Float64"}
    source.parts = lambda column: [str(tmp_path / f"{column}.arrow")]
    source.evict = lambda keep: None
    checking: list[bool] = []

    def _missing(columns: list[str]) -> dict[str, list[int]]:
        checking.append(source.converting)
        return missing

    source.missing = _missing
    return source, broker, checking


def test_converting_stays_off_without_missing_parts(tmp_path: Path) -> None:
    """With every part converted, the plot pool's call never marks a conversion."""
    source, broker, checking = _converting_source(tmp_path, {})
    asyncio.run(source.convert(["x"]))
    assert checking == [False]
    assert broker.seen == []
    assert source.converting is False


def test_converting_is_on_while_missing_parts_convert(tmp_path: Path) -> None:
    """The plot pool's conversion of missing parts is marked while its task runs."""
    source, broker, checking = _converting_source(tmp_path, {"x": [0]})
    asyncio.run(source.convert(["x"]))
    assert checking == [False]
    assert broker.seen == [True]
    assert source.converting is False


def test_converting_is_off_after_a_failed_conversion(tmp_path: Path) -> None:
    """A conversion task that fails leaves the source not converting."""
    source, broker, _ = _converting_source(tmp_path, {"x": [0]}, end="error")
    with pytest.raises(HTTPException) as raised:
        asyncio.run(source.convert(["x"]))
    assert raised.value.status_code == 500
    assert broker.seen == [True]
    assert source.converting is False


def test_the_summary_pool_conversion_is_not_marked(tmp_path: Path) -> None:
    """A conversion in the summary pool leaves plots allowed."""
    source, broker, _ = _converting_source(tmp_path, {"x": [0]})
    asyncio.run(source.convert(["x"], pool="summary"))
    assert broker.seen == [False]
    assert source.converting is False
