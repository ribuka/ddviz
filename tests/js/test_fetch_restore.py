"""JS: after a test that uses `js_page`, `window.fetch` is the page's own again (Issue #341).

The two tests run in the written order on the same shared page: the first stubs
`window.fetch` and leaves it, the second sees the native one.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

NATIVE = "() => Function.prototype.toString.call(window.fetch).includes('[native code]')"


def test_stub_left_in_place(js_page: Page) -> None:
    """Stub `window.fetch` on the shared page and leave it."""
    js_page.evaluate("() => { window.fetch = async () => new Response('stub'); }")
    assert js_page.evaluate(NATIVE) is False


def test_fetch_is_native_again(js_page: Page) -> None:
    """The next test on the shared page sees the native `fetch`."""
    assert js_page.evaluate(NATIVE) is True
