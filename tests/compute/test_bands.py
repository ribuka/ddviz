"""Tests of the bands of categorical axes."""

from __future__ import annotations

from ddviz.compute.bands import band_range


def test_band_range_holds_one_band_per_level() -> None:
    """Level i is centered on i; the axis ends half a step beyond the outer levels."""
    assert band_range(["a", "b", "c"]) == (-0.5, 2.5)
    assert band_range([]) == (-0.5, 0.5)


def test_band_range_of_a_million_levels() -> None:
    """The axis of the most levels a categorical x or y may have by default spans them all."""
    assert band_range([f"L{i}" for i in range(1_000_000)]) == (-0.5, 999_999.5)
