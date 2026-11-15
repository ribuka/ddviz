"""JS: keys.js tells a plain Enter from the Enter that commits an IME conversion."""

from __future__ import annotations

import pytest
from playwright.sync_api import Locator, Page

pytestmark = pytest.mark.js

# Sends a field the two Enters of an IME conversion: one `isComposing`, and
# one of `keyCode` 229, which the constructor of the event cannot set.
CONVERSION_ENTERS = """(field) => {
  field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true, cancelable: true }));
  const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
  Object.defineProperty(event, "keyCode", { value: 229 });
  field.dispatchEvent(event);
}"""

PLAIN_ENTER = """(field) => {
  field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
}"""


def press_conversion_enters(field: Locator) -> None:
    """Send `field` the Enters that commit an IME conversion."""
    field.evaluate(CONVERSION_ENTERS)


def press_plain_enter(field: Locator) -> None:
    """Send `field` an Enter that commits no conversion."""
    field.evaluate(PLAIN_ENTER)


def test_plain_enter_leaves_out_the_enter_of_a_conversion(js_page: Page) -> None:
    """Only an Enter that does not commit an IME conversion is plain."""
    got = js_page.evaluate(
        """async () => {
          const { plainEnter } = await import("/static/js/keys.js");
          return [
            { key: "Enter" },
            { key: "Enter", isComposing: true },
            { key: "Enter", keyCode: 229 },
            { key: "a" },
          ].map(plainEnter);
        }"""
    )
    assert got == [True, False, False, False]
