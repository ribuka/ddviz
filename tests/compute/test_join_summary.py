"""The summary of a join by keys before it is made: the rows matched and the sets of keys matching none (Issue #379)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from ddviz.compute import joinsummary
from ddviz.compute.join import run_join
from ddviz.compute.joinsummary import UNMATCHED_EXAMPLES, run_join_summary
from ddviz.shared.manifest import read_manifest
from ddviz.shared.tasks import JoinSummaryTask, JoinTask
from tests.compute.test_join_keys import _parts

# The input: 3 files of 4, 3 and 5 rows. Rows 0 and 9 match the same row of
# the joined table; some keys are null, some match no row.
LEFT = pl.DataFrame(
    {
        "n": [1, 2, None, 9, 3, 3, 9, None, 4, 1, 8, 9],
        "s": ["a", "b", "a", "z", "c", None, "z", "b", "d", "a", "a", "y"],
    },
    schema_overrides={"n": pl.Int64},
)
LEFT_ROWS = [4, 3, 5]
# The joined table: 2 files of 4 and 26 rows, each set of keys once. Its
# last 25 sets and its null match no row of the input.
RIGHT = pl.DataFrame(
    {
        "id": [1, 2, 3, 4, *range(124, 99, -1), None],
        "sub": ["a", "b", "c", "d", *["u"] * 25, "a"],
    },
    schema_overrides={"id": pl.Int64},
)
RIGHT_ROWS = [4, 26]
KEYS = {
    "one": [{"left": "n", "right": "id"}],
    "two": [{"left": "n", "right": "id"}, {"left": "s", "right": "sub"}],
}


def _summary(tmp_path: Path, keys: list[dict[str, str]]) -> dict:
    """Run the join task and then the summary of `keys`; return the summary's manifest."""
    left = _parts(tmp_path / "left", LEFT, LEFT_ROWS)
    right = _parts(tmp_path / "right", RIGHT, RIGHT_ROWS)
    maps = [str(tmp_path / "maps" / f"{i}.parquet") for i in range(len(LEFT_ROWS))]
    joined = [str(tmp_path / "joined" / f"{i}.parquet") for i in range(len(LEFT_ROWS))]
    used = {side: {k[side] for k in keys} for side in ("left", "right")}
    run_join(
        JoinTask(
            keys,
            {c: p for c, p in left.items() if c in used["left"]},
            {c: p for c, p in right.items() if c in used["right"]},
            LEFT_ROWS,
            RIGHT.height,
            maps,
            "_joined",
            joined,
        ),
        tmp_path / "join",
        lambda _: None,
    )
    out = tmp_path / "summary"
    out.mkdir()
    task = JoinSummaryTask(
        keys,
        {c: p for c, p in left.items() if c in used["left"]},
        {c: p for c, p in right.items() if c in used["right"]},
        maps,
        LEFT.height,
        RIGHT.height,
    )
    run_join_summary(task, out, lambda _: None)
    assert sorted(p.name for p in out.iterdir()) == ["manifest.json"]
    return read_manifest(out)


def _sets(frame: pl.DataFrame, keys: list[str]) -> dict:
    """Return the sets of `keys` of `frame` as the summary lists them: the most rows first, then the values ascending, nulls last."""
    found = frame.group_by(keys).agg(pl.len().alias("rows"))
    first = found.sort(["rows", *keys], descending=[True] + [False] * len(keys), nulls_last=True)
    return {
        "sets": found.height,
        "top": [
            {"values": [None if v is None else str(v) for v in row[:-1]], "rows": row[-1]}
            for row in first.head(UNMATCHED_EXAMPLES).rows()
        ],
    }


def _expected(keys: list[dict[str, str]]) -> dict:
    """Return the summary found apart with polars joins: a null key matches no row."""
    lefts = [k["left"] for k in keys]
    rights = [k["right"] for k in keys]
    left = LEFT.join(RIGHT, left_on=lefts, right_on=rights, how="anti")
    right = RIGHT.join(LEFT, left_on=rights, right_on=lefts, how="anti")
    return {
        "kind": "join_summary",
        "right_matched": RIGHT.height - right.height,
        "left_unmatched": _sets(left, lefts),
        "right_unmatched": _sets(right, rights),
    }


@pytest.mark.parametrize("case", list(KEYS))
def test_the_summary_in_one_piece_and_in_buckets_is_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Counted at once or in pieces split on disk, the summary is the one found apart, and the pieces leave no files."""
    keys = KEYS[case]
    whole = _summary(tmp_path / "one", keys)
    monkeypatch.setattr(joinsummary, "ONE_BUCKET_ROWS", 0)
    split = _summary(tmp_path / "buckets", keys)
    assert whole == split == _expected(keys)


def test_the_sets_are_listed_by_rows_then_by_values_with_nulls_last(tmp_path: Path) -> None:
    """By one key: the input's sets of more rows first, null last among those of one row; the joined table's 26 sets cut to 20."""
    found = _summary(tmp_path, KEYS["one"])
    assert found["right_matched"] == 4
    assert found["left_unmatched"] == {
        "sets": 3,
        "top": [
            {"values": ["9"], "rows": 3},
            {"values": [None], "rows": 2},
            {"values": ["8"], "rows": 1},
        ],
    }
    right = found["right_unmatched"]
    assert right["sets"] == 26
    assert len(right["top"]) == UNMATCHED_EXAMPLES
    assert right["top"][:2] == [{"values": ["100"], "rows": 1}, {"values": ["101"], "rows": 1}]
    assert right["top"][-1] == {"values": ["119"], "rows": 1}
