"""Tests of the plot's data as a file to save."""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient
from polars.testing import assert_frame_equal

from ddviz.server.plotdata import JOIN_ROWS, SELECTED, file_name
from tests.server.test_source_columns import (
    first_table_page,
    plot_body,
    write_parquet_file,
)

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


def _saved(client: TestClient, url: str, file_format: str, **fields: str) -> tuple[str, pl.DataFrame]:
    """Write a file of rows at `url` and fetch it; return its name and the file read back, a CSV as texts."""
    written = client.post(url, json={"format": file_format, "export": "t", **fields})
    assert written.status_code == 200, written.text
    found = written.json()
    fetched = client.get(f"/api/plot-data/file/{found['file']}")
    assert fetched.status_code == 200
    if file_format == "csv":
        return found["name"], pl.read_csv(io.BytesIO(fetched.content), infer_schema=False)
    return found["name"], pl.read_parquet(io.BytesIO(fetched.content))


def test_the_rows_of_both_tables_are_saved_after_a_dry_run_and_before_the_join(
    tmp_path: Path, serve: Callable[..., AbstractContextManager[TestClient]]
) -> None:
    """The rows of both tables come as a saved plot's file, named ``_join_rows``, only between a dry run and the join; a selection's file keeps ``_selected``."""
    left = write_parquet_file(
        tmp_path / "lots.parquet",
        pl.DataFrame({"lot": ["A", "A", "B", None], "x": [0.0, 1.0, 2.0, 3.0], "y": [0.0, 1.0, 2.0, 3.0]}),
    )
    right = write_parquet_file(tmp_path / "right.parquet", pl.DataFrame({"lot_id": ["A", "C", None]}))
    index = pl.get_index_type()
    expected = pl.DataFrame(
        {
            "_joined": ["both", "both", "left_only", "left_only", "right_only", "right_only"],
            "index": pl.Series([0, 1, 2, 3, None, None], dtype=index),
            "index_joined": pl.Series([0, 0, None, None, 1, 2], dtype=index),
            "lot": ["A", "A", "B", None, None, None],
            "lot_id": ["A", "A", None, None, "C", None],
        }
    )
    url = "/api/plot-data/join-rows"
    with serve([left]) as client:
        client.post("/api/join/source", json={"paths": [str(right)]})
        refused = client.post(url, json={"format": "csv", "columns": "key", "export": "t"})
        assert (refused.status_code, refused.json()["detail"]) == (409, "no join check")
        checked = client.post("/api/join/check", json={"keys": [{"left": "lot", "right": "lot_id"}]})
        assert checked.status_code == 200, checked.text
        for file_format in ("parquet", "csv"):
            name, found = _saved(client, url, file_format, columns="key")
            assert re.fullmatch(rf"lots_join_rows_\d{{8}}-\d{{6}}\.{file_format}", name), name
            if file_format == "parquet":
                assert_frame_equal(found, expected)
            else:
                texts = pl.read_csv(io.BytesIO(expected.write_csv().encode()), infer_schema=False)
                assert_frame_equal(found, texts)
        _, every = _saved(client, url, "parquet", columns="all")
        assert every.columns == [*expected.columns[:4], "lot_id", "x", "y"]
        task = plot_body(client, {"x": ["x"], "y": ["y"]})["meta"]["task"]
        first_table_page(client, task)
        name, _ = _saved(client, "/api/plot-data/selection", "csv", columns="all")
        assert re.fullmatch(r"lots_selected_\d{8}-\d{6}\.csv", name), name
        joined = client.post("/api/join", json={"kind": "key", "keys": [{"left": "lot", "right": "lot_id"}]})
        assert joined.status_code == 200, joined.text
        refused = client.post(url, json={"format": "csv", "columns": "key", "export": "t"})
        assert (refused.status_code, refused.json()["detail"]) == (409, "already joined")
