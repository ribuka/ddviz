"""Tests of the text of temporal values."""

from __future__ import annotations

import pytest

from ddviz.shared.temporal import text

# 2026-10-31 12:34:56.789 in milliseconds since the epoch.
NOON_MS = 1_793_450_096_789.0


@pytest.mark.parametrize(
    ("kind", "ms", "expected"),
    [
        ("datetime", NOON_MS, "2026-10-31 12:34:56.789000"),
        ("datetime", 0.0015, "1970-01-01 00:00:00.000002"),
        ("datetime", -1.0, "1969-12-31 23:59:59.999000"),
        ("date", NOON_MS, "2026-10-31"),
        ("time", 45_296_789.25, "12:34:56.789250"),
        ("duration", 1.5, None),
        ("datetime", 1e20, None),
    ],
)
def test_text(kind: str, ms: float, expected: str | None) -> None:
    """A datetime always shows microseconds, a date its day, a time its time; a duration has no text of its own."""
    assert text(kind, ms) == expected
