"""The join by keys: the map and ``_joined`` in one piece or in buckets on disk (Issue #365)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from ddviz.compute import join
from ddviz.compute.join import run_join
from ddviz.shared.joined import MAP_COLUMN
from ddviz.shared.manifest import read_manifest
from ddviz.shared.tasks import JoinTask

# The input: 3 files of 4, 3 and 5 rows. Some keys are null, some match no
# row of the joined table.
LEFT = {
    "n": [1, 2, None, 9, 3, 3, 7, None, 4, 1, 8, 2],
    "s": ["a", "b", "a", "z", None, "c", "a", "b", "d", "a", "a", "b"],
}
ROWS = [4, 3, 5]
# The joined table: each set of keys once.
RIGHT = {
    "n": [3, 1, 2, 4, 7, 5],
    "s": ["c", "a", "b", "d", "a", "x"],
}
# The pairs of keys, with the types of the input's and the joined table's.
CASES = {
    "int64": ([("n", "n")], {"n": pl.Int64}, {"n": pl.Int64}),
    "int32-int64": ([("n", "n")], {"n": pl.Int32}, {"n": pl.Int64}),
    "string-int64": ([("s", "s"), ("n", "n")], {"s": pl.String, "n": pl.Int64}, {"s": pl.String, "n": pl.Int64}),
}


def _parts(folder: Path, frame: pl.DataFrame, rows: list[int]) -> dict[str, list[str]]:
    """Write each column of `frame` as a part per file of `rows` rows, as the column cache holds them, and return their paths."""
    folder.mkdir(parents=True)
    parts: dict[str, list[str]] = {}
    for column in frame.columns:
        start = 0
        for i, n in enumerate(rows):
            path = folder / f"{column}_{i}.parquet"
            frame.select(column).slice(start, n).write_parquet(path)
            parts.setdefault(column, []).append(str(path))
            start += n
    return parts


def _task(tmp_path: Path, keys: list[tuple[str, str]], left: pl.DataFrame, right: pl.DataFrame) -> JoinTask:
    """Return a join task of `left` (files of `ROWS` rows) and `right` (one file) on `keys`."""
    return JoinTask(
        [{"left": a, "right": b} for a, b in keys],
        _parts(tmp_path / "left", left, ROWS),
        _parts(tmp_path / "right", right, [right.height]),
        ROWS,
        right.height,
        [str(tmp_path / "maps" / f"{i}.parquet") for i in range(len(ROWS))],
        "_joined",
        [str(tmp_path / "joined" / f"{i}.parquet") for i in range(len(ROWS))],
    )


@pytest.fixture(params=["one", "buckets"])
def buckets(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Merge in one piece (the default), or in `BUCKETS` pieces with `ONE_BUCKET_ROWS` at 0."""
    if request.param == "buckets":
        monkeypatch.setattr(join, "ONE_BUCKET_ROWS", 0)
    return request.param


@pytest.mark.parametrize("case", list(CASES))
def test_the_parts_are_those_of_a_left_join(tmp_path: Path, buckets: str, case: str) -> None:
    """The map and ``_joined`` of each file are those of a left join of the input's rows, and the merge leaves no files."""
    keys, left_types, right_types = CASES[case]
    left = pl.DataFrame(LEFT).select(pl.col(c).cast(t) for c, t in left_types.items())
    right = pl.DataFrame(RIGHT).select(pl.col(c).cast(t) for c, t in right_types.items())
    task = _task(tmp_path, keys, left, right)
    out = tmp_path / "out"
    out.mkdir()
    run_join(task, out, lambda message: None)

    expected = left.join(
        right.with_row_index("row"),
        left_on=[pl.col(a).cast(pl.Int64) if a == "n" else pl.col(a) for a, _ in keys],
        right_on=[b for _, b in keys],
        how="left",
        maintain_order="left",
    ).select(
        pl.col("row").alias(MAP_COLUMN),
        pl.when(pl.col("row").is_null()).then(pl.lit("left_only")).otherwise(pl.lit("both")).alias("_joined"),
    )
    start = 0
    for i, rows in enumerate(ROWS):
        found = pl.read_parquet(task.maps[i])
        assert found.schema == pl.Schema({MAP_COLUMN: pl.UInt32})
        assert found.equals(expected.select(MAP_COLUMN).slice(start, rows))
        joined = pl.read_parquet(task.indicators[i])
        assert joined.schema == pl.Schema({"_joined": pl.String})
        assert joined.equals(expected.select("_joined").slice(start, rows))
        start += rows
    assert read_manifest(out) == {"kind": "join", "matched": int((expected["_joined"] == "both").sum())}
    assert not (out / "merge").exists()
    assert not (out / "duplicates").exists()


def test_duplicate_keys_are_refused_alike(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A joined table of duplicate keys is refused with the same text in one piece and in buckets; sets with a null are not counted."""
    sets = [("c", 1), ("a", 2), ("b", 1), ("a", 1), ("d", 5), ("b", 3)]
    pairs = [*sets, *sets, ("a", None), ("a", None)]
    right = pl.DataFrame({"s": [s for s, _ in pairs], "n": [n for _, n in pairs]}, schema={"s": pl.String, "n": pl.Int64})
    left = pl.DataFrame(LEFT).select(pl.col("s"), pl.col("n").cast(pl.Int64))
    refused = []
    for case, rows in (("one", join.ONE_BUCKET_ROWS), ("buckets", 0)):
        monkeypatch.setattr(join, "ONE_BUCKET_ROWS", rows)
        task = _task(tmp_path / case, [("s", "s"), ("n", "n")], left, right)
        out = tmp_path / case / "out"
        out.mkdir()
        run_join(task, out, lambda message: None)
        refused.append(read_manifest(out)["refused"])
        assert not Path(task.maps[0]).parent.exists()
        assert not (out / "merge").exists()
        assert not (out / "duplicates").exists()
    assert refused == [
        "結合する表でキーが重複しています：6 組（例：(a, 1)、(a, 2)、(b, 1)、(b, 3)、(c, 1)）"
    ] * 2
