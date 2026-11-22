"""Tests of the plot's data as a file to save."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ddviz.server.plotdata import JOIN_ROWS, SELECTED, file_name

MOMENT = datetime(2026, 10, 30, 9, 5, 7, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "suffix"), [("", ""), (SELECTED, "_selected"), (JOIN_ROWS, "_join_rows")]
)
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ([str(Path("data") / "run 1.parquet")], "run_1{}_20261030-090507.csv"),
        ([str(Path("data") / "lots")], "lots{}_20261030-090507.csv"),
        ([str(Path("data") / ".parquet")], "ddviz{}_20261030-090507.csv"),
        (
            [str(Path("data") / f"data_{i}.parquet") for i in (10, 2, 1)],
            "data_1_and_2_more{}_20261030-090507.csv",
        ),
    ],
)
def test_file_name_is_the_inputs_name_and_the_time(
    source: list[str], expected: str, kind: str, suffix: str
) -> None:
    """The name is the input's without ``.parquet``, its unusable characters as ``_``, then the time.

    Several files are named by the first in reading order and how many more.
    The selected rows add ``_selected`` before the time, the rows of a join
    ``_join_rows``.
    """
    name = file_name(source, "csv", MOMENT, kind)
    assert name == expected.format(suffix)
