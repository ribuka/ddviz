"""Tests of the natural order of text."""

from __future__ import annotations

from ddviz.shared.natural import natural_key


def test_numbers_compare_by_value() -> None:
    """Runs of digits compare by value, so ``2_`` comes before ``10_``."""
    assert sorted(["10_", "1_", "2_"], key=natural_key) == ["1_", "2_", "10_"]


def test_letters_compare_without_case_and_text_comes_before_digits() -> None:
    """Letters compare without case; at the same place, text sorts before digits."""
    names = ["b", "A2", "a10", "a", "1", ""]
    assert sorted(names, key=natural_key) == ["", "a", "A2", "a10", "b", "1"]


def test_the_order_is_total() -> None:
    """Texts equal but for case or leading zeros keep a fixed order whatever the input order."""
    expected = ["A", "a", "01", "1"]
    for names in (["a", "A", "1", "01"], ["1", "01", "A", "a"]):
        assert sorted(names, key=natural_key) == expected


def test_other_decimal_digits_and_superscripts() -> None:
    """Decimal digits of other scripts count by value; a superscript is text, not a number (no error)."""
    assert sorted(["x²", "x١٠", "x٢"], key=natural_key) == ["x٢", "x١٠", "x²"]
