"""Tests of the column list search."""

from __future__ import annotations

import pytest

from ddviz.columns import search_columns

COLUMNS = [
    {"name": "Temp_A", "dtype": "Float64", "numeric": True},
    {"name": "lot", "dtype": "String", "numeric": False},
    {"name": "a_temp_b", "dtype": "Float64", "numeric": True},
    {"name": "press_A", "dtype": "Float64", "numeric": True},
]


def test_words_match_in_any_order_and_case() -> None:
    """Every word must be in the name, in any order and case."""
    found = search_columns(COLUMNS, "a TEMP", None, 10)
    assert [c["name"] for c in found["columns"]] == ["Temp_A", "a_temp_b"]
    assert (found["total"], found["matched"]) == (4, 2)


def test_limit_keeps_the_count_of_all_matches() -> None:
    """Only the first matches return, with the count of all of them."""
    found = search_columns(COLUMNS, "", None, 2)
    assert [c["name"] for c in found["columns"]] == ["Temp_A", "lot"]
    assert found["matched"] == 4


def test_kind_keeps_numeric_or_categorical_columns() -> None:
    """A kind keeps only the numeric or only the categorical columns."""
    assert [
        c["name"] for c in search_columns(COLUMNS, "", "categorical", 10)["columns"]
    ] == ["lot"]
    assert search_columns(COLUMNS, "a", "numeric", 10)["matched"] == 3
    with pytest.raises(ValueError, match="unknown kind"):
        search_columns(COLUMNS, "", "text", 10)
