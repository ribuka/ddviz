"""Tests of the codes of text values."""

from __future__ import annotations

import numpy as np
import polars as pl

from ddviz.compute.codes import text_codes


def test_text_codes_index_the_sorted_labels() -> None:
    """Each value is the index of its label among the sorted distinct values; a null is -1."""
    codes, labels = text_codes(pl.Series(["b", None, "a", "b"]))
    assert codes.dtype == np.int32
    assert codes.tolist() == [1, -1, 0, 1]
    assert labels == ["a", "b"]
