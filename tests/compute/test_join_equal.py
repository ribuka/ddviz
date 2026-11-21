"""The comparison of the columns a join may leave out, those named like the input's (Issue #359)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute.join import run_join_equal
from ddviz.shared.joined import MAP_COLUMN
from ddviz.shared.manifest import read_manifest
from ddviz.shared.tasks import JoinEqualTask

# The input: 2 files of 3 and 2 rows. By keys, the map gives the rows of the
# joined table; the second row of each file matches none, and holds a value
# in the input that the joined table cannot have there.
LEFT = [
    {
        "same": [1.0, 99.0, 3.0],
        "differ": [1.0, 99.0, 3.0],
        "nulls": [None, 2.0, 3.0],
        "half": [1.0, 2.0, 3.0],
        "wide": [1, 2, 3],
        "day": [date(2026, 1, 1)] * 3,
    },
    {
        "same": [4.0, 99.0],
        "differ": [4.0, 99.0],
        "nulls": [4.0, None],
        "half": [4.0, 5.0],
        "wide": [4, 5],
        "day": [date(2026, 1, 1)] * 2,
    },
]
MAPS = [[0, None, 2], [3, None]]
# The joined table, by keys: 4 rows, the row of the map.
RIGHT = {
    "same": [1.0, 0.0, 3.0, 4.0],
    "differ": [1.0, 0.0, 3.0, 4.5],
    "nulls": [None, 0.0, 3.0, 4.0],
    "half": [1.0, 0.0, None, 4.0],
    "wide": [1, 0, 3, 4],
    "day": [True, False, True, False],
}
# The joined table, by rows: the input's rows, with `same` and `differ` alike
# but the last row.
RIGHT_ROWS = {
    "same": [1.0, 99.0, 3.0, 4.0, 99.0],
    "differ": [1.0, 99.0, 3.0, 4.0, 98.0],
}


def _write(path: Path, frame: pl.DataFrame) -> str:
    """Write a part and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return str(path)


def _task(tmp_path: Path, right: dict[str, list], maps: list[list[int | None]]) -> JoinEqualTask:
    """Return the task comparing each column of `right` with the input's of its name, through `maps` (empty for rows)."""
    frames = [pl.DataFrame(f, schema_overrides={"wide": pl.Int32}) for f in LEFT]
    joined = pl.DataFrame(right)
    left = {c: [_write(tmp_path / "left" / f"{i}" / f"{c}.parquet", f.select(c)) for i, f in enumerate(frames)] for c in right}
    parts = {c: [_write(tmp_path / "right" / f"{c}.parquet", joined.select(c))] for c in right}
    map_parts = [
        _write(tmp_path / "map" / f"{i}.parquet", pl.DataFrame({MAP_COLUMN: rows}, schema={MAP_COLUMN: pl.UInt32}))
        for i, rows in enumerate(maps)
    ]
    return JoinEqualTask([{"left": c, "right": c} for c in right], left, parts, [3, 2], map_parts)


@pytest.mark.parametrize(
    ("right", "maps", "equal"),
    [
        (RIGHT, MAPS, ["same", "nulls", "wide"]),
        (RIGHT_ROWS, [], ["same"]),
    ],
    ids=["key", "rows"],
)
def test_the_columns_of_the_same_values_in_the_rows_joined_are_found(
    tmp_path: Path, right: dict[str, list], maps: list[list[int | None]], equal: list[str]
) -> None:
    """By keys, the rows the map matches are compared, through it, in the type both cast to, nulls equal; by rows, every row; a progress comes before each column."""
    task = _task(tmp_path, right, maps)
    messages: list[dict] = []
    (tmp_path / "out").mkdir()
    run_join_equal(task, tmp_path / "out", messages.append)
    assert read_manifest(tmp_path / "out") == {"kind": "join_equal", "equal": equal}
    names = list(right)
    assert messages == [
        {"type": "progress", "stage": "compare", "done": i, "total": len(names), "column": c}
        for i, c in enumerate(names)
    ]


def test_no_row_joined_is_not_the_same(tmp_path: Path) -> None:
    """A map matching no row leaves nothing to compare: no column has the same values."""
    task = _task(tmp_path, {"same": RIGHT["same"]}, [[None] * 3, [None] * 2])
    (tmp_path / "out").mkdir()
    run_join_equal(task, tmp_path / "out", lambda message: None)
    assert read_manifest(tmp_path / "out")["equal"] == []
