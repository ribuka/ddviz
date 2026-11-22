"""The join of another table to the input, by keys or by rows (Issue #343), with all its columns or some (Issue #358), maybe but those of the same values (Issue #359)."""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ddviz.server.broker import TaskEnd
from ddviz.server.settings import CacheSettings
from ddviz.server.source import Source
from ddviz.shared.cache import ColumnCache
from ddviz.shared.manifest import write_manifest
from ddviz.shared.tasks import JoinEqualTask, JoinTask
from tests.server.test_source_columns import (
    first_table_page,
    plot_body,
    table_values,
    write_parquet_file,
)

XY = {"x": ["x"], "y": ["y"]}
LEFT_COLUMNS = ["lot", "sub", "x", "y", "temp", "day", "source", "filename"]


def _left(lots: list[int | None], subs: list[str], start: int) -> pl.DataFrame:
    """Return a file of the input: keys, ``x`` and ``y`` from `start`, a temperature and a day."""
    xs = [float(start + i) for i in range(len(lots))]
    return pl.DataFrame(
        {
            "lot": lots,
            "sub": subs,
            "x": xs,
            "y": xs,
            "temp": [x / 10 for x in xs],
            "day": [date(2026, 1, 1 + int(x)) for x in xs],
        },
        schema_overrides={"lot": pl.Int64},
    )


@pytest.fixture
def left(tmp_path: Path) -> Path:
    """Return a folder of 3 files, 12 rows: keys repeated, missing in the joined table, and null."""
    root = tmp_path / "left"
    write_parquet_file(root / "a.parquet", _left([1, 2, 3, None], ["a", "b", "a", "a"], 0))
    write_parquet_file(root / "b.parquet", _left([4, 5, 1], ["a", "b", "b"], 4))
    write_parquet_file(root / "c.parquet", _left([9, 2, 3, 6, 7], ["a", "a", "b", "a", "a"], 7))
    return root


def _right_file(lots: list[int | None], subs: list[str], first: int) -> pl.DataFrame:
    """Return a file of the joined table with a temperature, a vendor and a score."""
    n = len(lots)
    return pl.DataFrame(
        {
            "lot": lots,
            "sub": subs,
            "temp": [100.0 * (first + i) for i in range(n)],
            "vendor": [f"v{first + i}" for i in range(n)],
            "score": [first + i for i in range(n)],
        },
        schema_overrides={"lot": pl.Int64},
    )


@pytest.fixture
def right(tmp_path: Path) -> Path:
    """Return a folder of 2 files, 7 rows, with unique keys and a null key."""
    root = tmp_path / "right"
    write_parquet_file(root / "r1.parquet", _right_file([1, 2, 3], ["a", "a", "a"], 0))
    write_parquet_file(root / "r2.parquet", _right_file([4, 5, 6, None], ["a", "b", "a", "a"], 3))
    return root


def _read_folder(root: Path) -> pl.DataFrame:
    """Return a folder's files one after another, with ``source`` and ``filename``, as the input reads them."""
    files = sorted(root.glob("*.parquet"))
    return pl.concat(
        [
            pl.read_parquet(f).with_columns(
                source=pl.lit(str(f.absolute())), filename=pl.lit(f.stem)
            )
            for f in files
        ],
        how="diagonal_relaxed",
    )


def _expected(left: Path, right: Path, keys: list[str]) -> pl.DataFrame:
    """Return the left join of the two folders by `keys`, with the columns named as the join adds them."""
    names = {
        "sub": "sub_joined",
        "temp": "temp_joined",
        "source": "source_joined",
        "filename": "filename_joined",
    }
    joined = _read_folder(right).rename({k: f"__key_{k}" for k in keys}).rename(names, strict=False)
    joined = joined.with_columns(_joined=pl.lit("both"))
    found = _read_folder(left).join(
        joined,
        left_on=keys,
        right_on=[f"__key_{k}" for k in keys],
        how="left",
        maintain_order="left",
    )
    return found.with_columns(pl.col("_joined").fill_null("left_only"))


def _save(client: TestClient, task: int, file_format: str) -> pl.DataFrame:
    """Save every column of a plot's drawn rows and read the file back."""
    request = {"format": file_format, "rows": "drawn", "columns": "all", "export": "t"}
    written = client.post(f"/api/plot-data/{task}", json=request)
    assert written.status_code == 200, written.text
    content = client.get(f"/api/plot-data/file/{written.json()['file']}").content
    if file_format == "csv":
        return pl.read_csv(io.BytesIO(content), infer_schema=False)
    return pl.read_parquet(io.BytesIO(content))


def _join(client: TestClient, right: Path, kind: str, keys: list[dict]) -> dict:
    """Read the joined table and join it; return the join's answer."""
    loaded = client.post("/api/join/source", json={"paths": [str(right)]})
    assert loaded.status_code == 200, loaded.text
    joined = client.post("/api/join", json={"kind": kind, "keys": keys})
    assert joined.status_code == 200, joined.text
    return joined.json()


def _texts(values: list) -> list[str | None]:
    """Return values as a CSV holds them: texts, an empty cell for null."""
    return [None if v is None else str(v) for v in values]


def _check_saved(saved: dict[str, pl.DataFrame], expected: pl.DataFrame, added: list[str]) -> None:
    """Check the saved Parquet and CSV files against the expected rows."""
    parquet, csv = saved["parquet"], saved["csv"]
    assert parquet["index"].to_list() == list(range(expected.height))
    for column in added:
        assert parquet[column].to_list() == expected[column].to_list(), column
        texts = [None if v is None else str(v) for v in expected[column].to_list()]
        assert csv[column].to_list() == texts, column


KEYS_ONE = [{"left": "lot", "right": "lot"}]
KEYS_TWO = [{"left": "lot", "right": "lot"}, {"left": "sub", "right": "sub"}]
ADDED_ONE = ["_joined", "sub_joined", "temp_joined", "vendor", "score", "source_joined", "filename_joined"]
ADDED_TWO = ["_joined", "temp_joined", "vendor", "score", "source_joined", "filename_joined"]


@pytest.mark.parametrize(
    ("keys", "added"), [(KEYS_ONE, ADDED_ONE), (KEYS_TWO, ADDED_TWO)], ids=["one", "two"]
)
def test_a_join_by_keys_adds_the_matching_rows(
    serve: Callable[..., AbstractContextManager[TestClient]],
    left: Path,
    right: Path,
    keys: list[dict],
    added: list[str],
) -> None:
    """Each row takes the joined table's row of the same keys; the others and null keys get nulls.

    The rows, their order and their numbers stay; the table and the saved
    files hold the same values before and after the columns are converted,
    and the joined columns plot, filter and summarize as any column.
    """
    expected = _expected(left, right, [k["left"] for k in keys])
    with serve([left]) as client:
        before = first_table_page(client, plot_body(client, XY)["meta"]["task"])
        loaded = client.post("/api/join/source", json={"paths": [str(right)]}).json()
        assert loaded == {
            "paths": [str(right)],
            "files": 2,
            "rows": 7,
            "columns": 7,
            "casts": [],
        }
        # The join dialog's fields ask for a column of the name typed first (Issue #344).
        for path in ("/api/join/columns", "/api/columns"):
            found = client.get(path, params={"q": "o", "exact": "lot"}).json()
            assert found["columns"][0]["name"] == "lot", path
            plain = client.get(path, params={"q": "o", "exact": "vendor"}).json()
            assert [c["name"] for c in plain["columns"]][:1] == (
                ["vendor"] if path == "/api/join/columns" else ["lot"]
            ), path
        answer = client.post("/api/join", json={"kind": "key", "keys": keys}).json()
        matched = (expected["_joined"] == "both").sum()
        assert answer == {"added": added, "rows": 12, "matched": matched, "skipped": []}
        schema = client.get("/api/schema").json()
        assert [c["name"] for c in schema] == LEFT_COLUMNS + added
        assert [c["joined"] for c in schema] == [False] * 8 + [True] * len(added)
        source = client.get("/api/source").json()
        assert source["join"] == {
            "paths": [str(right)],
            "label": "right",
            "recursive": False,
            "kind": "key",
            "keys": keys,
            "columns": None,
            "same_names": "skip_equal",
            "rows": 12,
            "matched": matched,
            "added": added,
        }

        # Before conversion: read through the map.
        task = plot_body(client, XY)["meta"]["task"]
        table = first_table_page(client, task)
        assert table["index"] == before["index"] == list(range(12))
        values = table_values(table)
        for column in added:
            assert values[column] == expected[column].to_list(), column
        unconverted = {f: _save(client, task, f) for f in ("parquet", "csv")}
        _check_saved(unconverted, expected, added)

        # The filter pane converts each column; the table then reads the parts.
        for column in added:
            summary = client.get("/api/summary", params={"column": column})
            assert summary.status_code == 200, summary.text
        levels = client.get("/api/filter-levels", params={"column": "vendor"}).json()
        assert {v for v, _ in levels["levels"]} == set(expected["vendor"].drop_nulls())
        task = plot_body(client, XY)["meta"]["task"]
        assert table_values(first_table_page(client, task)) == values
        converted = {f: _save(client, task, f) for f in ("parquet", "csv")}
        _check_saved(converted, expected, added)
        for f in ("parquet", "csv"):
            assert converted[f].equals(unconverted[f])

        # The joined columns on X, Color and a filter.
        both = [{"column": "_joined", "levels": ["both"]}]
        meta = plot_body(client, {"x": ["score"], "y": ["y"], "color": "vendor"}, filters=both)["meta"]
        assert meta["rows"] == matched


def test_keys_of_types_with_a_common_type_match(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], left: Path
) -> None:
    """Keys of Int32 and of text match the input's Int64 keys in their common type."""
    root = tmp_path / "typed"
    write_parquet_file(
        root / "t.parquet",
        pl.DataFrame(
            {"k32": [1, 2, 9], "kstr": ["1", "2", "9"], "v": [10.0, 20.0, 90.0]},
            schema_overrides={"k32": pl.Int32},
        ),
    )
    lots = _read_folder(left)["lot"].to_list()
    expected = [{1: 10.0, 2: 20.0, 9: 90.0}.get(lot) for lot in lots]
    for key in ("k32", "kstr"):
        with serve([left]) as client:
            keys = [{"left": "lot", "right": key}]
            answer = _join(client, root, "key", keys)
            assert answer["matched"] == sum(v is not None for v in expected)
            values = table_values(first_table_page(client, plot_body(client, XY)["meta"]["task"]))
            assert values["v"] == expected


@pytest.mark.parametrize(
    ("pair", "detail"),
    [
        ({"left": "day", "right": "flag"}, "キーの型が合いません：day（Date）と flag（Boolean）"),
        ({"left": "lot", "right": "items"}, "キーにできない型です：items（List(Int64)）"),
        ({"left": "lot", "right": "nope"}, "列がありません：nope"),
        ({"left": "nope", "right": "flag"}, "列がありません：nope"),
    ],
)
def test_keys_of_no_common_type_or_nested_or_unknown_are_refused(
    tmp_path: Path,
    serve: Callable[..., AbstractContextManager[TestClient]],
    left: Path,
    pair: dict,
    detail: str,
) -> None:
    """Keys that cannot be compared are refused, adding nothing; another try works."""
    root = tmp_path / "typed"
    write_parquet_file(
        root / "t.parquet",
        pl.DataFrame({"lot": [1, 2], "flag": [True, False], "items": [[1], [2]]}),
    )
    with serve([left]) as client:
        schema = client.get("/api/schema").json()
        loaded = client.post("/api/join/source", json={"paths": [str(root)]})
        assert loaded.status_code == 200
        refused = client.post("/api/join", json={"kind": "key", "keys": [pair]})
        assert refused.status_code == 400
        assert refused.json()["detail"] == detail
        assert client.get("/api/schema").json() == schema
        assert client.get("/api/source").json()["join"] is None
        again = client.post("/api/join", json={"kind": "key", "keys": KEYS_ONE})
        assert again.status_code == 200, again.text


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"kind": "key", "keys": []}, "キーの指定が正しくありません：キーで結合するときはキーが要ります"),
        ({"kind": "rows", "keys": KEYS_ONE}, "キーの指定が正しくありません：行の順で結合するときはキーを指定しません"),
        ({"kind": "outer", "keys": KEYS_ONE}, "キーの指定が正しくありません：知らない種類です：outer"),
        (
            {"kind": "key", "keys": [{"left": "lot", "right": "lot"}, {"left": "lot", "right": "sub"}]},
            "キーの指定が正しくありません：元の表の列が 2 回あります：lot",
        ),
        (
            {"kind": "key", "keys": [{"left": "lot", "right": "lot"}, {"left": "sub", "right": "lot"}]},
            "キーの指定が正しくありません：結合する表の列が 2 回あります：lot",
        ),
    ],
)
def test_keys_given_wrong_are_refused(
    serve: Callable[..., AbstractContextManager[TestClient]],
    left: Path,
    right: Path,
    body: dict,
    detail: str,
) -> None:
    """A kind or keys given wrong are refused with the reason."""
    with serve([left]) as client:
        client.post("/api/join/source", json={"paths": [str(right)]})
        refused = client.post("/api/join", json=body)
        assert refused.status_code == 400
        assert refused.json()["detail"] == detail


def test_duplicate_keys_in_the_joined_table_are_refused(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], left: Path
) -> None:
    """Keys several rows hold are counted and shown, those with a null left out; nothing is added."""
    root = tmp_path / "dup"
    lots = [7, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 8, None, None]
    write_parquet_file(root / "d1.parquet", pl.DataFrame({"lot": lots[:9], "v": [0.0] * 9}))
    write_parquet_file(root / "d2.parquet", pl.DataFrame({"lot": lots[9:], "v": [0.0] * 8}))
    with serve([left]) as client:
        schema = client.get("/api/schema").json()
        client.post("/api/join/source", json={"paths": [str(root)]})
        refused = client.post("/api/join", json={"kind": "key", "keys": KEYS_ONE})
        assert refused.status_code == 400
        assert refused.json()["detail"] == (
            "結合する表でキーが重複しています：7 組（例：1、2、3、4、5）"
        )
        assert client.get("/api/schema").json() == schema
        two = [{"left": "lot", "right": "lot"}, {"left": "sub", "right": "s"}]
        write_parquet_file(
            root / "d1.parquet",
            pl.DataFrame({"lot": [1, 1, 2, None, None], "s": ["a", "a", "b", "c", "c"]}),
        )
        (root / "d2.parquet").unlink()
        client.post("/api/join/source", json={"paths": [str(root)]})
        refused = client.post("/api/join", json={"kind": "key", "keys": two})
        assert refused.json()["detail"] == (
            "結合する表でキーが重複しています：1 組（例：(1, a)）"
        )


def test_a_join_by_rows_puts_rows_side_by_side(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], left: Path
) -> None:
    """The i-th rows go together across files split differently, without ``_joined``; other rows are refused."""
    root = tmp_path / "rows"
    write_parquet_file(root / "p1.parquet", pl.DataFrame({"w": [float(i) for i in range(5)], "x": list(range(50, 55))}))
    write_parquet_file(root / "p2.parquet", pl.DataFrame({"w": [float(i) for i in range(5, 12)], "x": list(range(55, 62))}))
    short = tmp_path / "short"
    write_parquet_file(short / "s.parquet", pl.DataFrame({"w": [0.0] * 11}))
    with serve([left]) as client:
        client.post("/api/join/source", json={"paths": [str(short)]})
        refused = client.post("/api/join", json={"kind": "rows", "keys": []})
        assert refused.status_code == 400
        assert refused.json()["detail"] == "行数が違います：元の表 12 行、結合する表 11 行"
        answer = _join(client, root, "rows", [])
        added = ["w", "x_joined", "source_joined", "filename_joined"]
        assert answer == {"added": added, "rows": 12, "matched": 12, "skipped": []}
        task = plot_body(client, XY)["meta"]["task"]
        values = table_values(first_table_page(client, task))
        assert values["w"] == [float(i) for i in range(12)]
        assert values["x_joined"] == list(range(50, 62))
        assert values["filename_joined"] == ["p1"] * 5 + ["p2"] * 7
        unconverted = _save(client, task, "parquet")
        assert client.get("/api/summary", params={"column": "w"}).status_code == 200
        assert client.get("/api/summary", params={"column": "x_joined"}).status_code == 200
        task = plot_body(client, {"x": ["w"], "y": ["x_joined"]})["meta"]["task"]
        assert table_values(first_table_page(client, task)) == values
        assert _save(client, task, "parquet").equals(unconverted)


def test_a_second_join_and_a_join_without_a_table_are_refused(
    serve: Callable[..., AbstractContextManager[TestClient]], left: Path, right: Path
) -> None:
    """A join needs a table read first, and is made once."""
    with serve([left]) as client:
        refused = client.post("/api/join", json={"kind": "key", "keys": KEYS_ONE})
        assert (refused.status_code, refused.json()["detail"]) == (409, "no join source")
        assert client.get("/api/join/columns").status_code == 409
        client.post("/api/join/source", json={"paths": [str(right)]})
        found = client.get("/api/join/columns", params={"q": "o"}).json()
        assert found["total"] == 7
        assert [c["name"] for c in found["columns"]] == ["lot", "vendor", "score", "source"]
        assert found["columns"][0] == {
            "name": "lot",
            "dtype": "Int64",
            "numeric": True,
            "temporal": None,
        }
        joined = client.post("/api/join", json={"kind": "key", "keys": KEYS_ONE})
        assert joined.status_code == 200, joined.text
        again = client.post("/api/join", json={"kind": "key", "keys": KEYS_ONE})
        assert (again.status_code, again.json()["detail"]) == (409, "already joined")
        loaded = client.post("/api/join/source", json={"paths": [str(right)]})
        assert (loaded.status_code, loaded.json()["detail"]) == (409, "already joined")


def test_a_joined_table_without_parquet_is_refused_as_load_refuses(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], left: Path
) -> None:
    """A joined table is read as Load reads an input, with its refusals."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with serve([left]) as client:
        refused = client.post("/api/join/source", json={"paths": [str(empty)]})
        assert refused.status_code == 400
        assert refused.json()["detail"] == f"Parquet ファイルがありません：{empty}"
        mixed = client.post(
            "/api/join/source", json={"paths": [str(empty), str(left / "a.parquet")]}
        )
        assert mixed.status_code == 400
        assert mixed.json()["detail"].startswith("複数を選ぶときはファイルだけにしてください")
        # A path that does not exist (typed in the join dialog, Issue #344).
        missing = tmp_path / "missing.parquet"
        gone = client.post("/api/join/source", json={"paths": [str(missing)]})
        assert gone.status_code == 400
        assert gone.json()["detail"] == f"ファイルかフォルダがありません：{missing}"


def test_changed_files_are_read_again(
    serve: Callable[..., AbstractContextManager[TestClient]], left: Path, right: Path
) -> None:
    """A changed file of the joined table, or of the input, gives its new values, not old parts."""
    with serve([left]) as client:
        _join(client, right, "key", KEYS_ONE)
        plot_body(client, {"x": ["score"], "y": ["y"]})
        assert table_values(first_table_page(client, plot_body(client, XY)["meta"]["task"]))["score"][:3] == [0, 1, 2]
    time.sleep(0.01)
    write_parquet_file(right / "r1.parquet", _right_file([1, 2, 3], ["a", "a", "a"], 50))
    with serve([left]) as client:
        _join(client, right, "key", KEYS_ONE)
        plot_body(client, {"x": ["score"], "y": ["y"]})
        assert table_values(first_table_page(client, plot_body(client, XY)["meta"]["task"]))["score"][:3] == [50, 51, 52]
    write_parquet_file(left / "a.parquet", _left([3, 2, 1, None], ["a", "b", "a", "a"], 0))
    with serve([left]) as client:
        _join(client, right, "key", KEYS_ONE)
        plot_body(client, {"x": ["score"], "y": ["y"]})
        assert table_values(first_table_page(client, plot_body(client, XY)["meta"]["task"]))["score"][:4] == [52, 51, 50, None]


def _nonnull(client: TestClient, names: list[str]) -> dict[str, int | None]:
    """Wait for the counts of the joined table and return the non-null values of `names`."""
    deadline = time.monotonic() + 30
    while True:
        found = {
            c["name"]: c["nonnull"]
            for c in client.get("/api/columns", params={"q": ""}).json()["columns"]
        }
        if all(found[n] is not None for n in names) or time.monotonic() > deadline:
            return {n: found[n] for n in names}
        time.sleep(0.1)


def test_non_null_counts_are_estimated_then_exact(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], left: Path
) -> None:
    """Before conversion a joined column counts its share times the rows matched; after, its own values."""
    root = tmp_path / "skewed"
    # Keys 1 and 2 (matched 2 + 2 times) have no value; 4..7 (each once) have.
    lots = [1, 2, 4, 5, 6, 7, 10, 11]
    values = [None, None, 4.0, 5.0, 6.0, 7.0, 10.0, 11.0]
    write_parquet_file(root / "s.parquet", pl.DataFrame({"lot": lots, "v": values}))
    with serve([left]) as client:
        answer = _join(client, root, "key", KEYS_ONE)
        matched = answer["matched"]
        assert matched == 8
        counts = _nonnull(client, ["_joined", "v"])
        assert counts == {"_joined": 12, "v": round(6 / 8 * matched)}
        assert client.get("/api/summary", params={"column": "v"}).status_code == 200
        assert _nonnull(client, ["v"]) == {"v": 4}
    with serve([left]) as client:
        _join(client, root, "key", KEYS_ONE)
        assert _nonnull(client, ["v"]) == {"v": 4}


def test_a_join_by_rows_counts_the_joined_table(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], left: Path
) -> None:
    """A column joined by rows has the joined table's count from the start."""
    root = tmp_path / "rows"
    write_parquet_file(root / "p.parquet", pl.DataFrame({"w": [None, *range(11)]}))
    with serve([left]) as client:
        _join(client, root, "rows", [])
        assert _nonnull(client, ["w"]) == {"w": 11}


class _JoinBroker:
    """A broker recording the kind of each task it gets with `Source.converting`; the task of the kind `fails` fails.

    The join task matches 1 row; the comparison finds ``v`` of the same values.
    """

    def __init__(self, fails: str | None, out: Path) -> None:
        self.fails = fails
        self.out = out
        self.seen: list[tuple[str, bool]] = []
        self.source: Source | None = None

    async def run(self, task: object, pool: str = "plot") -> TaskEnd:
        assert isinstance(task, JoinTask | JoinEqualTask)
        self.seen.append((task.KIND, self.source.converting))
        await asyncio.sleep(0)
        self.out.mkdir(parents=True, exist_ok=True)
        if isinstance(task, JoinTask):
            write_manifest(self.out, {"kind": "join", "matched": 1})
        else:
            write_manifest(self.out, {"kind": "join_equal", "equal": ["v"]})
        end = "error" if self.fails == task.KIND else "done"
        return TaskEnd(0, self.out, {"type": end, "message": f"the {task.KIND} task failed"})


def _joining_source(tmp_path: Path, fails: str | None = None) -> tuple[Source, _JoinBroker]:
    """Return a source of ``k`` and ``v`` with a joined table of the same columns read, whose columns are converted, and its broker."""
    broker = _JoinBroker(fails, tmp_path / "task")
    sources = []
    for name in ("a", "b"):
        file = write_parquet_file(tmp_path / f"{name}.parquet", pl.DataFrame({"k": [1, 2], "v": [1.0, 2.0]}))
        source = Source([str(file)], False, tmp_path / "cache", tmp_path / "index", CacheSettings, broker)
        source._schema = [
            {"name": "k", "dtype": "Int64", "numeric": True, "temporal": None, "joined": False},
            {"name": "v", "dtype": "Float64", "numeric": True, "temporal": None, "joined": False},
        ]
        source._dtypes = {"k": "Int64", "v": "Float64"}
        source.rows = [2]
        source.files = [file]
        source.cache = ColumnCache(tmp_path / "cache", [file], [file])
        source.missing = lambda columns: {}
        sources.append(source)
    sources[0].join_source = sources[1]
    broker.source = sources[0]
    return sources[0], broker


def test_converting_is_on_while_the_join_task_runs(tmp_path: Path) -> None:
    """The join task and, by default, the comparison of ``v`` run with plots refused, and let them again once done."""
    source, broker = _joining_source(tmp_path)
    asyncio.run(source.join("key", [{"left": "k", "right": "k"}]))
    assert broker.seen == [("join", True), ("join_equal", True)]
    assert source.converting is False


def test_converting_is_off_after_a_failed_join(tmp_path: Path) -> None:
    """A join task that fails leaves the source not converting and not joined."""
    source, broker = _joining_source(tmp_path, "join")
    with pytest.raises(HTTPException) as raised:
        asyncio.run(source.join("key", [{"left": "k", "right": "k"}]))
    assert (raised.value.status_code, raised.value.detail) == (500, "the join task failed")
    assert broker.seen == [("join", True)]
    assert source.converting is False
    assert source.joined is None
    assert not broker.out.exists()


@pytest.mark.parametrize(
    ("kind", "keys", "seen", "added"),
    [
        ("key", [{"left": "k", "right": "k"}], [("join", True), ("join_equal", True)], ["_joined"]),
        ("rows", [], [("join_equal", True)], ["k_joined"]),
    ],
    ids=["key", "rows"],
)
def test_converting_is_on_while_the_comparison_runs(
    tmp_path: Path, kind: str, keys: list[dict], seen: list[tuple[str, bool]], added: list[str]
) -> None:
    """On ``"skip_equal"``, the comparison runs with plots refused, after the join task by keys, and lets them again once done."""
    source, broker = _joining_source(tmp_path)
    answer = asyncio.run(source.join(kind, keys, same_names="skip_equal"))
    assert (answer["added"], answer["skipped"]) == (added, ["v"])
    assert broker.seen == seen
    assert source.converting is False


def test_skip_equal_does_not_compare_when_no_columns_are_candidates(tmp_path: Path) -> None:
    """A join whose only same-named columns are right keys runs just the join task."""
    source, broker = _joining_source(tmp_path)
    keys = [{"left": name, "right": name} for name in ("k", "v")]
    answer = asyncio.run(source.join("key", keys, same_names="skip_equal"))
    assert (answer["added"], answer["skipped"]) == (["_joined"], [])
    assert broker.seen == [("join", True)]


@pytest.mark.parametrize(
    ("kind", "keys"), [("key", [{"left": "k", "right": "k"}]), ("rows", [])], ids=["key", "rows"]
)
def test_converting_is_off_after_a_failed_comparison(tmp_path: Path, kind: str, keys: list[dict]) -> None:
    """A comparison that fails is a 500 with the worker's reason, leaving the source not converting, not joined, and its columns as before."""
    source, broker = _joining_source(tmp_path, "join_equal")
    schema = asyncio.run(source.schema())
    with pytest.raises(HTTPException) as raised:
        asyncio.run(source.join(kind, keys, same_names="skip_equal"))
    assert (raised.value.status_code, raised.value.detail) == (500, "the join_equal task failed")
    assert broker.seen[-1] == ("join_equal", True)
    assert source.converting is False
    assert source.joined is None
    assert asyncio.run(source.schema()) == schema


def test_another_spelling_of_the_paths_joins_its_own_values(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], left: Path
) -> None:
    """A key on ``source``, and ``source_joined``, follow the paths as given in each session, not parts made with another spelling."""
    root = tmp_path / "bysource"
    first = str((left / "a.parquet").absolute())
    write_parquet_file(root / "s1.parquet", pl.DataFrame({"src": [first], "v": [99.0]}))
    write_parquet_file(root / "s2.parquet", pl.DataFrame({"src": ["elsewhere"], "v": [1.0]}))
    keys = [{"left": "source", "right": "src"}]
    with serve([left]) as client:
        assert _join(client, root, "key", keys)["matched"] == 4
        assert client.get("/api/summary", params={"column": "v"}).status_code == 200
        values = table_values(first_table_page(client, plot_body(client, XY)["meta"]["task"]))
        assert values["v"] == [99.0] * 4 + [None] * 8
    spelled = tmp_path / "left" / ".." / "left"
    other = tmp_path / "bysource" / ".." / "bysource"
    with serve([spelled]) as client:
        assert _join(client, other, "key", keys)["matched"] == 0
        table = first_table_page(client, plot_body(client, XY)["meta"]["task"])
        assert table_values(table)["v"] == [None] * 12
        assert table_values(table)["_joined"] == ["left_only"] * 12
        for column in ("v", "source_joined"):
            assert client.get("/api/summary", params={"column": column}).status_code == 200
        assert table_values(first_table_page(client, plot_body(client, XY)["meta"]["task"])) == table_values(table)
    with serve([left]) as client:
        _join(client, other, "key", keys)
        for column in ("v", "source_joined"):
            assert client.get("/api/summary", params={"column": column}).status_code == 200
        values = table_values(first_table_page(client, plot_body(client, XY)["meta"]["task"]))
        assert values["v"] == [99.0] * 4 + [None] * 8
        assert values["source_joined"] == [str((other / "s1.parquet").absolute())] * 4 + [None] * 8


def test_columns_named_as_the_internal_ones_keep_their_values(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], left: Path
) -> None:
    """Columns and keys named as the names a join uses inside are joined, read and saved as any others."""
    root = tmp_path / "named"
    write_parquet_file(
        root / "n.parquet",
        pl.DataFrame(
            {
                "__ddviz_row": [1, 2],
                "__ddviz_count": [1, 2],
                "__ddviz_left": [10, 20],
                "__ddviz_map": [30, 40],
                "__ddviz_value_0": [50, 60],
            }
        ),
    )
    keys = [{"left": "lot", "right": "__ddviz_row"}]
    lots = _read_folder(left)["lot"].to_list()
    expected = {
        c: [{1: a, 2: b}.get(lot) for lot in lots]
        for c, (a, b) in (
            ("__ddviz_left", (10, 20)),
            ("__ddviz_map", (30, 40)),
            ("__ddviz_value_0", (50, 60)),
        )
    }
    with serve([left]) as client:
        answer = _join(client, root, "key", keys)
        assert answer["matched"] == 4
        task = plot_body(client, XY)["meta"]["task"]
        values = table_values(first_table_page(client, task))
        for column, found in expected.items():
            assert values[column] == found, column
        unconverted = _save(client, task, "parquet")
        for column in expected:
            assert client.get("/api/summary", params={"column": column}).status_code == 200
        task = plot_body(client, XY)["meta"]["task"]
        assert table_values(first_table_page(client, task)) == values
        assert _save(client, task, "parquet").equals(unconverted)
    dup = tmp_path / "dupnamed"
    write_parquet_file(dup / "d.parquet", pl.DataFrame({"__ddviz_count": [1, 1, 2], "__ddviz_row": [5, 5, 6]}))
    with serve([left]) as client:
        client.post("/api/join/source", json={"paths": [str(dup)]})
        pair = [{"left": "lot", "right": "__ddviz_count"}, {"left": "sub", "right": "__ddviz_row"}]
        refused = client.post("/api/join", json={"kind": "key", "keys": pair})
        assert refused.status_code == 400
        assert refused.json()["detail"] == "結合する表でキーが重複しています：1 組（例：(1, 5)）"


def test_a_later_read_of_the_table_to_join_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A read that ends after a later one is refused and keeps nothing: the page read other paths meanwhile (Issue #344)."""
    source, _ = _joining_source(tmp_path)
    source.join_source = None
    read_schema = Source.schema
    gate = asyncio.Event()

    async def schema(self: Source) -> list[dict]:
        if self is source:
            return await read_schema(self)
        if self.paths == ["first"]:
            await gate.wait()
        self.files, self.rows, self.casts = [Path(self.paths[0])], [2], []
        return [{"name": "k"}]

    monkeypatch.setattr(Source, "schema", schema)

    async def reads() -> tuple[HTTPException, dict]:
        first = asyncio.create_task(source.load_join_source(["first"], False))
        await asyncio.sleep(0)
        second = await source.load_join_source(["second"], False)
        gate.set()
        with pytest.raises(HTTPException) as raised:
            await first
        return raised.value, second

    refused, second = asyncio.run(reads())
    assert (refused.status_code, refused.detail) == (409, "superseded")
    assert second["paths"] == ["second"]
    assert source.join_source.paths == ["second"]


# ---- the columns to add (Issue #358) ----

# Start of the message of the columns to keep given wrong, and the reason for a same_names with columns chosen.
WRONG = "保持する列の指定が正しくありません："
CHOSEN = "列を選んだときは同じ名前の扱いを指定しません"


def _joined_values(
    serve: Callable[..., AbstractContextManager[TestClient]], left: Path, right: Path, body: dict
) -> tuple[dict, list[str], dict[str, list]]:
    """Join `right` to `left` with `body` on a server of its own; return the answer, the columns added and the table's values."""
    with serve([left]) as client:
        loaded = client.post("/api/join/source", json={"paths": [str(right)]})
        assert loaded.status_code == 200, loaded.text
        joined = client.post("/api/join", json=body)
        assert joined.status_code == 200, joined.text
        schema = client.get("/api/schema").json()
        added = [c["name"] for c in schema if c["joined"]]
        values = table_values(first_table_page(client, plot_body(client, XY)["meta"]["task"]))
        return joined.json(), added, values


@pytest.fixture
def rows_right(tmp_path: Path) -> Path:
    """Return a folder of 2 files of 12 rows to join by rows to `left`: ``w``, and ``x`` of values other than the input's."""
    root = tmp_path / "rows"
    write_parquet_file(root / "p1.parquet", pl.DataFrame({"w": [float(i) for i in range(5)], "x": list(range(50, 55))}))
    write_parquet_file(root / "p2.parquet", pl.DataFrame({"w": [float(i) for i in range(5, 12)], "x": list(range(55, 62))}))
    return root


@pytest.mark.parametrize(
    ("kind", "keys", "columns", "added"),
    [
        ("key", KEYS_ONE, ["score", "temp"], ["_joined", "temp_joined", "score"]),
        ("key", KEYS_ONE, ["source"], ["_joined", "source_joined"]),
        ("rows", [], ["x"], ["x_joined"]),
    ],
    ids=["key-reversed", "key-source", "rows"],
)
def test_only_the_columns_picked_are_added_in_the_joined_table_s_order(
    request: pytest.FixtureRequest,
    serve: Callable[..., AbstractContextManager[TestClient]],
    left: Path,
    kind: str,
    keys: list[dict],
    columns: list[str],
    added: list[str],
) -> None:
    """``columns`` adds those columns alone, after ``_joined`` by keys, in the joined table's order, with the values all the columns give them."""
    right = request.getfixturevalue("right" if kind == "key" else "rows_right")
    answer, listed, values = _joined_values(serve, left, right, {"kind": kind, "keys": keys, "columns": columns})
    assert (answer["added"], answer["skipped"], listed) == (added, [], added)
    _, _, every = _joined_values(serve, left, right, {"kind": kind, "keys": keys, "columns": None})
    for column in added:
        assert values[column] == every[column], column


@pytest.fixture
def same_named(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return an input of ``id`` and ``label``, a joined table of 2 files with ``id``, ``label``, ``label_joined`` and ``score``, and one of 1 file of the input's columns alone."""
    left = tmp_path / "input.parquet"
    write_parquet_file(left, pl.DataFrame({"id": [1, 2, 3], "label": ["a", "b", "c"], "x": [0.0, 1.0, 2.0], "y": [0.0, 1.0, 2.0]}))
    right = tmp_path / "named"
    for name, ids in (("n1", [1]), ("n2", [2, 3])):
        write_parquet_file(
            right / f"{name}.parquet",
            pl.DataFrame(
                {
                    "id": ids,
                    "label": [f"L{i}" for i in ids],
                    "label_joined": [f"J{i}" for i in ids],
                    "score": [10 * i for i in ids],
                }
            ),
        )
    alone = tmp_path / "alone"
    write_parquet_file(alone / "a.parquet", pl.DataFrame({"id": [7, 8, 9], "label": ["p", "q", "r"], "x": [1.0, 2.0, 3.0]}))
    return left, right, alone


def test_columns_named_like_the_input_s_are_left_out_on_skip(
    serve: Callable[..., AbstractContextManager[TestClient]], same_named: tuple[Path, Path, Path]
) -> None:
    """``"skip"`` leaves out ``label``, names the others as if it were not there and keeps ``source`` and ``filename``; by default, ``label`` of other values is kept renamed."""
    left, right, alone = same_named
    keys = [{"left": "id", "right": "id"}]
    answer, listed, values = _joined_values(serve, left, right, {"kind": "key", "keys": keys, "same_names": "skip"})
    added = ["_joined", "label_joined", "score", "source_joined", "filename_joined"]
    assert (answer["added"], answer["skipped"], listed) == (added, ["label"], added)
    assert values["label_joined"] == ["J1", "J2", "J3"]
    assert values["label"] == ["a", "b", "c"]

    answer, listed, values = _joined_values(serve, left, right, {"kind": "key", "keys": keys})
    added = ["_joined", "label_joined", "label_joined_joined", "score", "source_joined", "filename_joined"]
    assert (answer["added"], answer["skipped"], listed) == (added, [], added)
    assert (values["label_joined"], values["label_joined_joined"]) == (["L1", "L2", "L3"], ["J1", "J2", "J3"])

    # By keys, nothing left but `_joined` is not refused.
    answer, listed, _ = _joined_values(serve, left, alone, {"kind": "key", "keys": keys, "same_names": "skip"})
    assert (answer["added"], answer["skipped"]) == (["_joined"], ["label", "x"])

    with serve([left]) as client:
        schema = client.get("/api/schema").json()
        client.post("/api/join/source", json={"paths": [str(alone)]})
        refused = client.post("/api/join", json={"kind": "rows", "same_names": "skip"})
        assert refused.status_code == 400
        assert refused.json()["detail"] == "保持する列がありません：結合する表の列はすべて元の表と同じ名前です"
        assert client.get("/api/schema").json() == schema
        again = client.post("/api/join", json={"kind": "rows"})
        assert again.status_code == 200, again.text
        assert again.json()["added"] == ["id_joined", "label_joined", "x_joined"]


@pytest.mark.parametrize(
    ("given", "detail"),
    [
        ({"same_names": "drop"}, f"{WRONG}知らない扱いです：drop"),
        ({"columns": None, "same_names": "rename"}, f"{WRONG}知らない扱いです：rename"),
        ({"columns": ["score"], "same_names": "skip_equal"}, f"{WRONG}{CHOSEN}"),
        ({"columns": ["score"], "same_names": "skip"}, f"{WRONG}{CHOSEN}"),
        ({"columns": ["score"], "same_names": "rename"}, f"{WRONG}{CHOSEN}"),
        ({"columns": []}, f"{WRONG}列を 1 つ以上選んでください"),
        ({"columns": ["score", "vendor", "score"]}, f"{WRONG}列が 2 回あります：score"),
        ({"columns": ["score", "nope"]}, "列がありません：nope"),
        ({"columns": ["lot", "score"]}, f"{WRONG}キーの列は足せません：lot"),
        ({"columns": ["lot", "nope"]}, "列がありません：nope"),
    ],
    ids=[
        "same-names",
        "rename",
        "columns-with-skip-equal",
        "columns-with-skip",
        "columns-with-rename",
        "empty",
        "twice",
        "missing",
        "key",
        "missing-before-key",
    ],
)
def test_columns_to_add_given_wrong_are_refused(
    serve: Callable[..., AbstractContextManager[TestClient]],
    left: Path,
    right: Path,
    given: dict,
    detail: str,
) -> None:
    """Columns to add given wrong are refused with the reason, adding nothing; the join given right then works.

    The join given right picks ``temp``, named like a column of the input,
    without ``same_names``: it is kept renamed, and ``same_names`` stays null.
    """
    with serve([left]) as client:
        schema = client.get("/api/schema").json()
        client.post("/api/join/source", json={"paths": [str(right)]})
        refused = client.post("/api/join", json={"kind": "key", "keys": KEYS_ONE, **given})
        assert refused.status_code == 400
        assert refused.json()["detail"] == detail
        assert client.get("/api/schema").json() == schema
        assert client.get("/api/source").json()["join"] is None
        again = client.post("/api/join", json={"kind": "key", "keys": KEYS_ONE, "columns": ["temp", "score"]})
        assert again.status_code == 200, again.text
        assert again.json()["added"] == ["_joined", "temp_joined", "score"]
        assert client.get("/api/source").json()["join"]["same_names"] is None


# ---- the columns of the same values (Issue #359) ----


@pytest.fixture
def equal_left(tmp_path: Path) -> Path:
    """Return an input of 3 files, 8 rows of ``id`` 1 to 8, with the columns `equal_right` has named alike."""
    root = tmp_path / "eq_left"
    for name, ids in (("e1", [1, 2, 3]), ("e2", [4, 5]), ("e3", [6, 7, 8])):
        xs = [float(i) for i in ids]
        frame = pl.DataFrame(
            {
                "id": ids,
                "x": xs,
                "y": xs,
                "same": xs,
                "differ": xs,
                "nulls": [None if i in (2, 5) else x for i, x in zip(ids, xs, strict=True)],
                "half": xs,
                "wide": ids,
                "day": [date(2026, 1, i) for i in ids],
                "tags": [[i] for i in ids],
            },
            schema_overrides={"wide": pl.Int32},
        )
        write_parquet_file(root / f"{name}.parquet", frame)
    return root


@pytest.fixture
def equal_right(tmp_path: Path) -> Path:
    """Return a joined table of 1 file matching ``id`` 1, 2, 4, 5, 6 and 7 of `equal_left`, of columns named like the input's.

    ``same`` holds the input's values in the rows joined, ``differ`` too but
    in the last row joined of the last file (``id`` 7), ``nulls`` the same
    nulls, ``half`` a null where the input has a value (``id`` 4), ``wide``
    the same values in Int64 (Int32 in the input), ``day`` Boolean (Date in
    the input), and ``tags`` the same lists.
    """
    ids = [1, 2, 4, 5, 6, 7]
    xs = [float(i) for i in ids]
    frame = pl.DataFrame(
        {
            "id": ids,
            "same": xs,
            "differ": [70.0 if i == 7 else x for i, x in zip(ids, xs, strict=True)],
            "nulls": [None if i in (2, 5) else x for i, x in zip(ids, xs, strict=True)],
            "half": [None if i == 4 else x for i, x in zip(ids, xs, strict=True)],
            "wide": ids,
            "day": [i % 2 == 0 for i in ids],
            "tags": [[i] for i in ids],
        }
    )
    root = tmp_path / "eq_right"
    write_parquet_file(root / "r.parquet", frame)
    return root


def test_columns_of_the_same_values_in_the_rows_joined_are_left_out_on_skip_equal(
    serve: Callable[..., AbstractContextManager[TestClient]], equal_left: Path, equal_right: Path
) -> None:
    """``"skip_equal"`` leaves out the columns of the same values in the rows joined, nulls and types cast alike, and adds the others renamed."""
    keys = [{"left": "id", "right": "id"}]
    answer, listed, values = _joined_values(
        serve, equal_left, equal_right, {"kind": "key", "keys": keys, "same_names": "skip_equal"}
    )
    added = ["_joined", "differ_joined", "half_joined", "day_joined", "tags_joined"]
    assert (answer["added"], answer["skipped"], listed) == (added, ["same", "nulls", "wide"], added)
    assert values["differ_joined"] == [1.0, 2.0, None, 4.0, 5.0, 6.0, 70.0, None]


@pytest.mark.parametrize("kind", ["key", "rows"])
def test_columns_of_the_same_values_are_left_out_by_default(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], equal_left: Path, kind: str
) -> None:
    """Without ``same_names``, a column named like the input's of the same values in the rows joined is left out, one of other values kept renamed (Issue #378)."""
    root = tmp_path / "eq_default"
    if kind == "key":
        ids = [1, 2, 4]
        xs = [float(i) for i in ids]
        frame = pl.DataFrame({"id": ids, "same": xs, "differ": [*xs[:-1], 40.0]})
        keys = [{"left": "id", "right": "id"}]
        added = ["_joined", "differ_joined"]
    else:
        xs = [float(i) for i in range(1, 9)]
        frame = pl.DataFrame({"same": xs, "differ": [*xs[:-1], 80.5]})
        keys = []
        added = ["differ_joined"]
    write_parquet_file(root / "r.parquet", frame)
    with serve([equal_left]) as client:
        client.post("/api/join/source", json={"paths": [str(root)]})
        joined = client.post("/api/join", json={"kind": kind, "keys": keys})
        assert joined.status_code == 200, joined.text
        assert (joined.json()["added"], joined.json()["skipped"]) == (added, ["same"])
        join = client.get("/api/source").json()["join"]
        assert (join["columns"], join["same_names"], join["added"]) == (None, "skip_equal", added)


def test_columns_are_compared_in_every_row_by_rows(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], equal_left: Path
) -> None:
    """By rows, ``"skip_equal"`` compares every row: a column different in the last row is added renamed; none left is refused."""
    xs = [float(i) for i in range(1, 9)]
    root = tmp_path / "eq_rows"
    write_parquet_file(root / "p.parquet", pl.DataFrame({"same": xs, "differ": [*xs[:-1], 80.5]}))
    answer, listed, _ = _joined_values(serve, equal_left, root, {"kind": "rows", "same_names": "skip_equal"})
    assert (answer["added"], answer["skipped"], listed) == (["differ_joined"], ["same"], ["differ_joined"])

    alone = tmp_path / "eq_alone"
    write_parquet_file(alone / "p.parquet", pl.DataFrame({"same": xs}))
    with serve([equal_left]) as client:
        schema = client.get("/api/schema").json()
        client.post("/api/join/source", json={"paths": [str(alone)]})
        refused = client.post("/api/join", json={"kind": "rows", "same_names": "skip_equal"})
        assert refused.status_code == 400
        assert refused.json()["detail"] == "保持する列がありません：結合する表の列はすべて元の表と同じ名前です"
        assert client.get("/api/schema").json() == schema


def test_no_row_joined_leaves_out_no_column(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]], equal_left: Path
) -> None:
    """By keys matching no row, nothing is compared alike: the columns named like the input's are added renamed."""
    root = tmp_path / "eq_none"
    write_parquet_file(root / "r.parquet", pl.DataFrame({"id": [100, 101], "same": [1.0, 2.0]}))
    keys = [{"left": "id", "right": "id"}]
    answer, _, _ = _joined_values(serve, equal_left, root, {"kind": "key", "keys": keys, "same_names": "skip_equal"})
    assert (answer["added"], answer["skipped"], answer["matched"]) == (["_joined", "same_joined"], [], 0)
