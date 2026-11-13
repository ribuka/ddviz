"""JS: colorpanel.js reads a color's code typed in HEX."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def test_a_code_takes_3_or_6_digits_with_or_without_its_hash(js_page: Page) -> None:
    """6 or 3 hex digits, with or without "#", in any case and between blanks, are a color; anything else is not."""
    cases = {
        "#1F77B4": "#1f77b4",
        "1f77b4": "#1f77b4",
        " 0f0 ": "#00ff00",
        "#ABC": "#aabbcc",
        "#12345": None,
        "#1234567": None,
        "##000": None,
        "#ggg": None,
        "": None,
        "rgb(0,0,0)": None,
    }
    result = js_page.evaluate(
        """async (texts) => {
          const { parseHex } = await import("/static/js/colorpanel.js");
          return texts.map(parseHex);
        }""",
        list(cases),
    )
    assert result == list(cases.values())
