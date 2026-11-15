"""JS: axiskey.js turns a plotly axis id into its layout key."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def test_axis_key_of_first_and_numbered_axes(js_page: Page) -> None:
    """The first axis and numbered ones, also of two digits, take the key of their layout."""
    keys = js_page.evaluate(
        """async () => {
          const { axisKey } = await import("/static/js/axiskey.js");
          return [axisKey("x"), axisKey("x2"), axisKey("y13")];
        }"""
    )
    assert keys == ["xaxis", "xaxis2", "yaxis13"]
