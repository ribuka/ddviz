"""JS: wrapmenu.js reads the number of panels to a row."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.js.test_keys import press_conversion_enters, press_plain_enter

pytestmark = pytest.mark.js

WRAP_COLS_MAX = 9007199254740991


def test_the_number_of_panels_takes_whole_numbers_only(js_page: Page) -> None:
    """Blank, zero, signs, fractions, exponents, full-width digits and numbers past the safe integers are refused; blanks around and leading zeros are taken."""
    wrong = ["", " ", "0", "-1", "+2", "1.5", "1e2", "２", "9007199254740992", "a"]
    good = {" 01 ": 1, "3": 3, str(WRAP_COLS_MAX): WRAP_COLS_MAX}
    result = js_page.evaluate(
        """async (texts) => {
          const { parseWrapCols, WRAP_COLS_ERROR } = await import("/static/js/wrapmenu.js");
          return [texts.map(parseWrapCols), WRAP_COLS_ERROR];
        }""",
        [*wrong, *good],
    )
    assert result[0] == [None] * len(wrong) + list(good.values())
    assert result[1] == f"1 以上 {WRAP_COLS_MAX} 以下の整数を入力してください"


def test_enter_in_the_number_applies_unless_it_commits_a_conversion(js_page: Page) -> None:
    """Enter in the number of panels, after picking 指定, applies it; the Enter of an IME conversion does not."""
    js_page.evaluate(
        """async () => {
          const { openWrapMenu } = await import("/static/js/wrapmenu.js");
          window.applied = [];
          openWrapMenu({ clientX: 10, clientY: 10 }, null, 2, (cols) => window.applied.push(cols), {
            showNullRows: true,
            onNullRows: () => {},
          });
        }"""
    )
    js_page.get_by_label("指定").check()
    number = js_page.locator("#wrap-cols-input")
    number.fill("3")
    press_conversion_enters(number)
    assert js_page.evaluate("window.applied") == []
    press_plain_enter(number)
    assert js_page.evaluate("window.applied") == [3]
