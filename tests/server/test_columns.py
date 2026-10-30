"""Tests of the column list search."""

from __future__ import annotations

import pytest

from ddviz.server.columns import search_columns

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


NONNULL = {"counts": [5, None, 0, 9], "rows": 10}


def test_each_column_carries_its_count_and_share() -> None:
    """Every returned column has its non-null values and their share, None when unknown."""
    found = search_columns(COLUMNS, "", None, 10, NONNULL)
    assert [c["nonnull"] for c in found["columns"]] == [5, None, 0, 9]
    assert [c["share"] for c in found["columns"]] == [0.5, None, 0.0, 0.9]
    column = search_columns(COLUMNS, "", None, 10)["columns"][0]
    assert (column["nonnull"], column["share"]) == (None, None)


def test_min_share_drops_sparser_columns_but_not_unknown_ones() -> None:
    """A lower bound keeps the columns at or above it and those of unknown share."""
    found = search_columns(COLUMNS, "", None, 10, NONNULL, min_share=0.5)
    assert [c["name"] for c in found["columns"]] == ["Temp_A", "lot", "press_A"]
    assert found["matched"] == 3


def test_min_share_zero_drops_columns_of_nulls_only() -> None:
    """A lower bound of 0 drops the columns without any value."""
    found = search_columns(COLUMNS, "", None, 10, NONNULL, min_share=0.0)
    assert [c["name"] for c in found["columns"]] == ["Temp_A", "lot", "press_A"]


def test_order_by_share_ranks_all_matches_before_the_limit() -> None:
    """The highest shares come first, unknown last, over every match before the limit."""
    found = search_columns(COLUMNS, "", None, 2, NONNULL, order="nonnull")
    assert [c["name"] for c in found["columns"]] == ["press_A", "Temp_A"]
    found = search_columns(COLUMNS, "", None, 10, NONNULL, order="nonnull")
    assert [c["name"] for c in found["columns"]][-1] == "lot"
    with pytest.raises(ValueError, match="unknown order"):
        search_columns(COLUMNS, "", None, 10, NONNULL, order="name")
