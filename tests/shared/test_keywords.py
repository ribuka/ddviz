"""Tests of the keywords of a search input and their match (`ddviz.shared.keywords`)."""

from __future__ import annotations

import polars as pl
import pytest

from ddviz.shared.keywords import keywords, matches

# Texts the rule meets: ASCII, symbols of patterns, and letters whose lower
# case Python and polars must agree on.
TEXTS = [
    "ABC-123",
    "123-abc",
    "a.c",
    "A*B(C)",
    "ÄÖÜ äöü",
    "ΣΑΣ σας",
    "Straße STRASSE",
    "İstanbul",
    "ǅ ǈ ǋ",
    "Ⅻ ⓐ Ⓐ",
    "ＡＢＣ ａｂｃ",
    "",
]


def test_keywords_are_lower_case_words() -> None:
    """White space splits the input; each word is lower-cased."""
    assert keywords("  Abc\t123\n") == ["abc", "123"]


@pytest.mark.parametrize("query", ["", " ", " \t\n　"])
def test_a_blank_input_has_no_keywords(query: str) -> None:
    """An empty or blank input (the ideographic space included) has none, which matches every value."""
    assert keywords(query) == []
    assert matches("anything", keywords(query))
    assert matches("", keywords(query))


def test_case_and_order_do_not_matter() -> None:
    """``abc 123`` matches ``ABC-123`` and ``123-abc``, not ``ABC`` or ``abc-12``."""
    words = keywords("abc 123")
    assert matches("ABC-123", words)
    assert matches("123-abc", words)
    assert not matches("ABC", words)
    assert not matches("abc-12", words)
    assert not matches("", words)


@pytest.mark.parametrize(
    ("query", "value", "expected"),
    [
        ("a.c", "abc", False),
        ("a.c", "xA.Cx", True),
        ("a*", "aaa", False),
        ("a*", "A*B", True),
        ("(c", "c", False),
        ("(c", "B(C)", True),
    ],
)
def test_symbols_of_patterns_are_literal(
    query: str, value: str, expected: bool
) -> None:
    """``.``, ``*`` and ``(`` are compared as characters, not as a pattern."""
    assert matches(value, keywords(query)) is expected


@pytest.mark.parametrize(
    ("query", "value"),
    [("ä", "Ä"), ("Ä", "ä"), ("σ", "Σ"), ("Σ", "σ")],
)
def test_unicode_letters_match_either_case(query: str, value: str) -> None:
    """Letters beyond ASCII match in either case."""
    assert matches(value, keywords(query))


def test_lower_case_is_not_casefold() -> None:
    """``ß`` and ``ss`` stay apart: the rule lower-cases, it does not casefold."""
    assert not matches("Straße", keywords("strasse"))
    assert not matches("STRASSE", keywords("ß"))


def test_python_and_polars_lower_case_alike() -> None:
    """`str.lower` and polars' `str.to_lowercase` give the same text, so the filter and the search agree."""
    lowered = pl.Series(TEXTS).str.to_lowercase().to_list()
    assert lowered == [t.lower() for t in TEXTS]
