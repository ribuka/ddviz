"""The columns added to an input of several files: each row's source file and its name."""

from __future__ import annotations

import io
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from ddviz.server.app import create_app
from ddviz.server.settings import Settings

TOKEN = "secret-of-the-run"
SIZE = {"width": 400, "height": 300}
HIDE_NULLS = {"show_nulls": False}
EVERYWHERE = {"panel": 0, "x_range": [-100, 100], "y_range": [-100, 100]}


@contextmanager
def _serve(tmp_path: Path, paths: list[Path], recursive: bool) -> Iterator[TestClient]:
    """Serve an input with its column cache under `tmp_path`, kept across calls."""
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    app = create_app(
        [str(p) for p in paths],
        recursive,
        run,
        tmp_path / "cache",
        tmp_path / "history",
        Settings(),
        TOKEN,
    )
    with TestClient(app) as client:
        assert client.get("/", params={"token": TOKEN}).status_code == 200
        yield client


def _write(path: Path, frame: pl.DataFrame) -> Path:
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
        _write(root / "a" / "run.01.parquet", _frame([0, 1, 2], k=["a0", "a1", "a2"])),
        _write(root / "b" / "run.01.parquet", _frame([3, 4], k=["b0", "b1"])),
        _write(root / "c" / "empty.parquet", _frame([], k=[])),
        _write(root / "z.parquet", _frame([5], k=["z0"])),
    ]
    return root, files


def _expected(files: list[Path], rows: list[int]) -> tuple[list[str], list[str]]:
    """Return each row's ``source`` and ``filename`` for files of `rows` rows each."""
    source = [
        str(f.absolute()) for f, n in zip(files, rows, strict=True) for _ in range(n)
    ]
    filename = [f.stem for f, n in zip(files, rows, strict=True) for _ in range(n)]
    return source, filename


def _plot(client: TestClient, encoding: dict, **extra: object) -> dict:
    """Draw `encoding` and return the response body."""
    response = client.post(
        "/api/plot", json={"encoding": encoding, **SIZE, **HIDE_NULLS, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _table(client: TestClient, task: int) -> dict:
    """Select every row of a drawn plot and return the first page of the table."""
    selected = client.post("/api/selection", json={"task": task, **EVERYWHERE})
    assert selected.status_code == 200, selected.text
    table = client.get("/api/table")
    assert table.status_code == 200, table.text
    return table.json()


def _values(table: dict) -> dict[str, list]:
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
    tmp_path: Path, folder: tuple[Path, list[Path]], given: str
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
    with _serve(tmp_path, paths, given == "folder") as client:
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
        meta = _plot(client, XY)["meta"]
        uncached = _table(client, meta["task"])
        assert uncached["index"] == list(range(6))
        values = _values(uncached)
        assert values["k"] == ["a0", "a1", "a2", "b0", "b1", "z0"]
        assert values["source"] == source
        assert values["filename"] == filename == ["run.01"] * 5 + ["z"]
        dtypes = {c["name"]: c["dtype"] for c in uncached["columns"]}
        assert dtypes["source"] == dtypes["filename"] == "String"

        # A filter converts them into the cache; the table then reads it.
        every = [{"column": "filename", "levels": ["run.01", "z"]}]
        every.append({"column": "source", "levels": sorted(set(source))})
        meta = _plot(client, XY, filters=every)["meta"]
        assert meta["rows"] == 6
        cached = _table(client, meta["task"])
        assert cached["index"] == uncached["index"]
        assert _values(cached) == values

        narrowed = [{"column": "source", "levels": [source[3]]}]
        assert _plot(client, XY, filters=narrowed)["meta"]["rows"] == 2
        narrowed = [{"column": "filename", "levels": ["z"]}]
        meta = _plot(client, XY, filters=narrowed)["meta"]
        assert meta["rows"] == 1
        assert _table(client, meta["task"])["index"] == [5]

        summary = client.get("/api/summary", params={"column": "filename"}).json()
        assert dict(map(tuple, summary["levels"])) == {"run.01": 5, "z": 1}
        assert summary["nulls"] == 0

        # A plot colored by the name saves its bins with the names.
        meta = _plot(client, {**XY, "color": "filename"})["meta"]
        url = f"/api/plot-data/{meta['task']}"
        saved = client.get(url, params={"format": "parquet"})
        assert saved.status_code == 200, saved.text
        bins = pl.read_parquet(io.BytesIO(saved.content))
        counts = bins.group_by("color").agg(pl.col("count").sum())
        assert dict(counts.iter_rows()) == {"run.01": 5, "z": 1}
        csv = client.get(url, params={"format": "csv"})
        assert pl.read_csv(io.BytesIO(csv.content)).equals(bins)


@pytest.mark.parametrize("folder_input", [False, True])
def test_one_file_adds_nothing(tmp_path: Path, folder_input: bool) -> None:
    """One file given directly, or a folder of one file, adds no columns."""
    file = _write(tmp_path / "one" / "only.parquet", _frame([0, 1], k=["a", "b"]))
    with _serve(tmp_path, [file.parent if folder_input else file], False) as client:
        schema = client.get("/api/schema").json()
        assert [c["name"] for c in schema] == ["x", "y", "k"]
        meta = _plot(client, XY)["meta"]
        assert [c["name"] for c in _table(client, meta["task"])["columns"]] == [
            "x",
            "y",
            "k",
        ]


def test_added_names_skip_the_names_of_the_files(tmp_path: Path) -> None:
    """Names some file uses keep its values; the added columns take the next free name.

    One file has ``source``, the other ``source_2`` and ``filename``: the
    source path is ``source_3``, and the name ``filename_2``, on its own.
    """
    first = _write(tmp_path / "in" / "p1.parquet", _frame([0, 1], source=["s", "t"]))
    second = _write(
        tmp_path / "in" / "p2.parquet",
        _frame([2], source_2=[7], filename=["mine"]),
    )
    with _serve(tmp_path, [first, second], False) as client:
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
        meta = _plot(client, XY)["meta"]
        values = _values(_table(client, meta["task"]))
        assert values["source"] == ["s", "t", None]
        assert values["source_2"] == [None, None, 7]
        assert values["filename"] == [None, None, "mine"]
        assert values["source_3"] == [str(first)] * 2 + [str(second)]
        assert values["filename_2"] == ["p1", "p1", "p2"]
        filters = [{"column": "source_3", "levels": [str(second)]}]
        meta = _plot(client, XY, filters=filters)["meta"]
        assert _values(_table(client, meta["task"]))["filename"] == ["mine"]


def test_a_cache_from_before_the_added_columns_is_read_again(
    tmp_path: Path, folder: tuple[Path, list[Path]]
) -> None:
    """A stored schema and non-null counts without the added columns are made again."""
    root, _ = folder
    with _serve(tmp_path, [root], True) as client:
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

    with _serve(tmp_path, [root], True) as client:
        schema = client.get("/api/schema").json()
        assert [c["name"] for c in schema][3:] == ["source", "filename"]
        shares = _shares(client)
        assert shares["source"]["nonnull"] == shares["filename"]["nonnull"] == 6


def test_a_replaced_file_moving_a_name_reuses_no_part(tmp_path: Path) -> None:
    """A file replaced with one that has ``source`` takes the name from the added column.

    The parts converted for the added ``source`` are not read as the file's
    column, whose other file has nulls, and the added column is ``source_2``.
    """
    first = _write(tmp_path / "in" / "p1.parquet", _frame([0, 1]))
    second = _write(tmp_path / "in" / "p2.parquet", _frame([2]))
    with _serve(tmp_path, [first.parent], False) as client:
        filters = [{"column": "source", "levels": [str(first), str(second)]}]
        meta = _plot(client, XY, filters=filters)["meta"]
        assert _values(_table(client, meta["task"]))["source"] == [
            str(first),
            str(first),
            str(second),
        ]
    _write(second, _frame([2, 3], source=["mine", "yours"]))
    with _serve(tmp_path, [first.parent], False) as client:
        names = [c["name"] for c in client.get("/api/schema").json()]
        assert names == ["x", "y", "source", "source_2", "filename"]
        # The summary converts ``source`` into the cache, where the table reads it.
        summary = client.get("/api/summary", params={"column": "source"}).json()
        assert dict(map(tuple, summary["levels"])) == {"mine": 1, "yours": 1}
        assert summary["nulls"] == 2
        client.get("/api/summary", params={"column": "source_2"})
        meta = _plot(client, XY)["meta"]
        table = _table(client, meta["task"])
        assert table["index"] == [0, 1, 2, 3]
        values = _values(table)
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
    tmp_path: Path, how: str
) -> None:
    """The same folder opened by another path, sharing the cache, shows that path.

    The cache knows the input by its resolved path, and the parts of the
    added columns made for one spelling are not read for the other.
    """
    real = tmp_path / "real"
    first = _write(real / "a.parquet", _frame([0, 1]))
    second = _write(real / "b.parquet", _frame([2]))
    with _serve(tmp_path, [real], False) as client:
        summary = client.get("/api/summary", params={"column": "source"}).json()
        assert dict(map(tuple, summary["levels"])) == {str(first): 2, str(second): 1}
    alias = _alias(real, how)
    expected = [str((alias / "a.parquet").absolute())] * 2
    expected.append(str((alias / "b.parquet").absolute()))
    assert expected[0] != str(first)
    with _serve(tmp_path, [alias], False) as client:
        assert len(list((tmp_path / "cache").glob("*/source.json"))) == 1
        meta = _plot(client, XY)["meta"]
        assert _values(_table(client, meta["task"]))["source"] == expected
        filters = [{"column": "source", "levels": [expected[2]]}]
        meta = _plot(client, XY, filters=filters)["meta"]
        assert _values(_table(client, meta["task"]))["source"] == expected[2:]
