"""JS: filters.js writes the numbers of a filter card short."""

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
