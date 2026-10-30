"""Tests of the plot's data as a file to save."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ddviz.server.plotdata import file_name

MOMENT = datetime(2026, 10, 30, 9, 5, 7, tzinfo=UTC)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (str(Path("data") / "run 1.parquet"), "run_1_20261030-090507.csv"),
        (str(Path("data") / "lots"), "lots_20261030-090507.csv"),
        (str(Path("data") / ".parquet"), "ddviz_20261030-090507.csv"),
    ],
)
def test_file_name_is_the_inputs_name_and_the_time(source: str, expected: str) -> None:
    """The name is the input's without ``.parquet``, its unusable characters as ``_``, then the time."""
    assert file_name(source, "csv", MOMENT) == expected
