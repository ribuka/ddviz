"""Tests of temporal columns read as numbers: their kinds, values, schema, summary and plots."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from ddviz.compute.aggregate import COUNT, KEY, aggregate
from ddviz.compute.scan import scan_columns
from ddviz.compute.summary import summarize_column
from ddviz.compute.tasks.columns import run_schema
from ddviz.compute.temporal import as_number, temporal_kind, with_numbers
from ddviz.server.encoding import Encoding
from ddviz.server.plan import scatter_spec
from ddviz.shared.manifest import read_manifest
from ddviz.shared.scatter import Binning, Filter, ScatterSpec

# 2026-10-31 12:34:56.789 UTC in milliseconds since the epoch.
NOON_MS = 1_793_450_096_789.0
# Naive, as a Parquet datetime without a time zone.
NOON = dt.datetime(2026, 10, 31, 12, 34, 56, 789000)  # noqa: DTZ001


def _numbers(series: pl.Series) -> list[float]:
    """Return a series as numbers by `as_number`."""
    frame = series.to_frame("c")
    return frame.select(as_number("c", series.dtype))["c"].to_list()


@pytest.mark.parametrize(
    ("dtype", "kind"),
    [
        (pl.Datetime("ns"), "datetime"),
        (pl.Datetime("us", "Asia/Tokyo"), "datetime"),
        (pl.Date, "date"),
        (pl.Time, "time"),
        (pl.Duration("ms"), "duration"),
        (pl.Float64, None),
        (pl.String, None),
    ],
)
def test_temporal_kind(dtype: pl.DataType, kind: str | None) -> None:
    """Datetime, Date, Time and Duration have a kind; other types none."""
    assert temporal_kind(dtype) == kind


@pytest.mark.parametrize("unit", ["ns", "us", "ms"])
def test_a_datetime_is_milliseconds_since_the_epoch(unit: str) -> None:
    """A datetime of any unit is its milliseconds since the epoch."""
    series = pl.Series([NOON, None]).cast(pl.Datetime(unit))
    assert _numbers(series) == [pytest.approx(NOON_MS, abs=1e-3), None]


def test_a_zoned_datetime_is_its_wall_clock_time() -> None:
    """A datetime with a time zone is taken at its time in that zone."""
    series = pl.Series([NOON]).dt.replace_time_zone("Asia/Tokyo")
    assert _numbers(series) == [pytest.approx(NOON_MS, abs=1e-3)]


def test_a_date_is_its_midnight_and_a_time_its_milliseconds_since_midnight() -> None:
    """A date is the milliseconds of its 0:00; a time those since 0:00."""
    assert _numbers(pl.Series([dt.date(1970, 1, 2)])) == [86_400_000.0]
    assert _numbers(pl.Series([dt.time(1, 0, 0, 500)])) == [3_600_000.5]


@pytest.mark.parametrize("unit", ["ns", "us", "ms"])
def test_a_duration_is_seconds(unit: str) -> None:
    """A duration of any unit is its seconds."""
    series = pl.Series([dt.timedelta(seconds=90, milliseconds=250)]).cast(
        pl.Duration(unit)
    )
    assert _numbers(series) == [90.25]


def test_with_numbers_converts_only_temporal_columns() -> None:
    """A frame keeps its other columns and the names of its temporal ones."""
    frame = pl.LazyFrame({"t": [NOON], "v": [1]})
    out = with_numbers(frame).collect()
    assert out.schema == pl.Schema({"t": pl.Float64, "v": pl.Int64})


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """Write 100 rows: a datetime one minute apart, a date, a time, a duration and y."""
    n = 100
    start = dt.datetime(2026, 10, 31)  # noqa: DTZ001 (naive, as in Parquet)
    frame = pl.DataFrame(
        {
            "at": [start + dt.timedelta(minutes=i) for i in range(n)],
            "day": [dt.date(2026, 10, 1 + i % 3) for i in range(n)],
            "clock": [dt.time(i % 24, 0) for i in range(n)],
            "took": [dt.timedelta(seconds=i) for i in range(n)],
            "y": [float(i) for i in range(n)],
        }
    )
    path = tmp_path / "temporal.parquet"
    frame.write_parquet(path)
    return path


def test_schema_marks_temporal_columns_numeric_with_their_kind(
    tmp_path: Path, path: Path
) -> None:
    """The schema task gives each column its temporal kind; a temporal column is numeric."""
    out = tmp_path / "out"
    out.mkdir()
    run_schema([str(path)], out, lambda _: None)
    columns = {c["name"]: c for c in read_manifest(out)["columns"]}
    assert {n: (c["numeric"], c["temporal"]) for n, c in columns.items()} == {
        "at": (True, "datetime"),
        "day": (True, "date"),
        "clock": (True, "time"),
        "took": (True, "duration"),
        "y": (True, None),
    }


def test_summary_of_a_datetime_is_its_range_in_milliseconds(path: Path) -> None:
    """A datetime's summary is numeric, with its kind and its range as numbers."""
    summary = summarize_column([str(path)], "at")
    start = dt.datetime(2026, 10, 31, tzinfo=dt.UTC).timestamp() * 1000
    assert summary["numeric"] is True
    assert summary["temporal"] == "datetime"
    assert summary["min"] == start
    assert summary["max"] == start + 99 * 60_000


def test_scan_reads_numbers_unless_told_to_keep_the_values(path: Path) -> None:
    """Plots read a datetime as numbers; the table reads its values."""
    files = {"at": [str(path)]}
    assert scan_columns(files).collect_schema()["at"] == pl.Float64
    kept = scan_columns(files, numbers=False).collect_schema()["at"]
    assert kept == pl.Datetime("us")


def _spec(
    path: Path, filters: list[Filter] | None = None, **roles: list[str] | str
) -> ScatterSpec:
    """Return the spec of a graph of the temporal columns, as the server makes it."""
    columns = ["at", "day", "clock", "took", "y"]
    kinds = {"at": "datetime", "day": "date", "clock": "time", "took": "duration"}
    return scatter_spec(
        Encoding(**roles),
        {c: [str(path)] for c in columns},
        400,
        300,
        ["#000000"],
        numeric=dict.fromkeys(columns, True),
        filters=filters,
        temporal=kinds,
    )


def test_a_datetime_axis_is_binned_over_milliseconds(path: Path) -> None:
    """A datetime on x is a numeric axis over its milliseconds."""
    spec = _spec(path, x=["at"], y=["y"])
    assert spec.categorical == []
    assert spec.temporal == {"at": "datetime"}
    agg = aggregate(spec)
    start = dt.datetime(2026, 10, 31, tzinfo=dt.UTC).timestamp() * 1000
    lo, hi = agg.x_ranges[0]
    assert lo < start < start + 99 * 60_000 < hi
    assert agg.bins[COUNT].sum() == 100


def test_a_datetime_facet_is_cut_into_intervals_named_by_dates(path: Path) -> None:
    """A datetime on Group X is cut into intervals whose names are datetimes."""
    spec = _spec(path, x=["took"], y=["y"], col="at")
    assert "col" in spec.binned
    agg = aggregate(spec)
    first = agg.levels["col"][0]
    assert first.startswith("[2026-10-31 00:00:00.000000, 2026-10-31 ")


def test_a_date_with_few_values_has_a_level_per_date(path: Path) -> None:
    """A date with few values on Group Y has a level per date."""
    agg = aggregate(_spec(path, x=["took"], y=["y"], row="day"))
    assert agg.levels["row"] == ["2026-10-01", "2026-10-02", "2026-10-03"]


def test_a_filter_on_a_datetime_takes_milliseconds(path: Path) -> None:
    """A filter range on a datetime column is in milliseconds."""
    start = dt.datetime(2026, 10, 31, tzinfo=dt.UTC).timestamp() * 1000
    spec = _spec(
        path,
        x=["clock"],
        y=["y"],
        filters=[Filter("at", range=[start, start + 9 * 60_000])],
    )
    assert aggregate(spec).bins[COUNT].sum() == 10


def test_date_intervals_within_a_day_are_named_apart(path: Path) -> None:
    """Equal-width intervals of a date narrower than a day are named by their times, each once, and rows keep their own interval."""
    spec = _spec(path, x=["took"], y=["y"], color="day")
    spec = replace(spec, gradient=False, binned={"color": Binning(10, "values")})
    agg = aggregate(spec)
    names = agg.levels["color"]
    assert len(names) == len(set(names)) == 10
    assert names[0].startswith("[2026-10-01 00:00:00.000000, 2026-10-01 04:48")
    # 2026-10-01, -02 and -03 lie in the first, middle and last intervals.
    series = agg.grid.unpack(agg.bins[KEY].to_numpy())[1]
    assert {names[s] for s in series.tolist()} == {names[0], names[5], names[9]}
