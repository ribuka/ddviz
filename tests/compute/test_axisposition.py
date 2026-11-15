"""Tests of the positions of the rows on the axes."""

from __future__ import annotations

import math

import polars as pl

from ddviz.compute.axisposition import within


def test_within_keeps_finite_positions_in_the_range() -> None:
    """Only a finite position from lo to hi is within; a null position gives null."""
    frame = pl.DataFrame({"p": [0.5, 2.0, math.inf, math.nan, None]})
    assert frame.select(within(pl.col("p"), 0, 1))["p"].to_list() == [
        True,
        False,
        False,
        False,
        None,
    ]
    assert frame.filter(within(pl.col("p"), 0, 1))["p"].to_list() == [0.5]
