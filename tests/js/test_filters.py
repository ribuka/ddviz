"""JS: filters.js writes the numbers of a filter card short and sorts its levels."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def test_huge_numbers_stay_short(js_page: Page) -> None:
    """Integers of 16 digits or more and 1e300 take 4 significant digits, as fractions do; smaller integers are whole with separators."""
    cases = {
        1e300: "1.000e+300",
        -1e300: "-1.000e+300",
        2e299: "2.000e+299",
        1e15: "1.000e+15",
        999999999999999: "999,999,999,999,999",
        1234: "1,234",
        0.123456: "0.1235",
        -2.5: "-2.5",
    }
    result = js_page.evaluate(
        """async (values) => {
          const { formatNumber } = await import("/static/js/filters.js");
          return values.map(formatNumber);
        }""",
        list(cases),
    )
    assert result == list(cases.values())


def _sort(page: Page, levels: list, *orders: str) -> list:
    """Return the levels after sorting them by each of `orders` in turn."""
    return page.evaluate(
        """async ([levels, orders]) => {
          const { sortLevels } = await import("/static/js/filters.js");
          let out = levels;
          for (const order of orders) out = sortLevels(out, order);
          return out;
        }""",
        [levels, list(orders)],
    )


def test_name_keeps_the_order_of_the_summary(js_page: Page) -> None:
    """Name leaves the levels in the natural order the summary gives."""
    levels = [["ID2", 1], ["ID10", 7], ["a", 3], [None, 9]]
    assert _sort(js_page, levels, "name") == levels


def test_count_puts_the_most_rows_first_and_ties_by_name(js_page: Page) -> None:
    """Count sorts by count, descending; equal counts keep the order of Name."""
    levels = [["ID2", 5], ["ID10", 5], ["a", 9]]
    assert [level for level, _ in _sort(js_page, levels, "count")] == [
        "a",
        "ID2",
        "ID10",
    ]


def test_picking_the_same_order_again_changes_nothing(js_page: Page) -> None:
    """Sorting twice by the same order gives the same list as once."""
    levels = [["ID2", 5], ["ID10", 5], ["a", 9], ["b", 1]]
    for order in ("name", "count"):
        assert _sort(js_page, levels, order, order) == _sort(js_page, levels, order)
