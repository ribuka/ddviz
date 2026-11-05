"""Tests of the bands of categorical axes."""

from __future__ import annotations

from ddviz.compute.bands import band_range


def test_band_range_holds_one_band_per_level() -> None:
    """Level i is centered on i; the axis ends half a step beyond the outer levels."""
    assert band_range(["a", "b", "c"]) == (-0.5, 2.5)
    assert band_range([]) == (-0.5, 0.5)
