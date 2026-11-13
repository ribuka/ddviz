"""E2E: the footer shows the memory of the backend and the frontend, fetched about every second."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.conftest import TOKEN

pytestmark = pytest.mark.e2e


def answer(route: Route, body: dict) -> None:
    """Answer a memory request with `body`."""
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


@pytest.fixture
def opened(page: Page, app_url: str) -> Iterator[Page]:
    """Return the page, to open once its routes are set (`open_app`)."""
    yield page
    page.close()


def open_app(page: Page, app_url: str) -> None:
    """Open the app with its token."""
    page.goto(f"{app_url}/?token={TOKEN}")


def test_the_footer_shows_both_sides_and_explains_them(opened: Page, app_url: str) -> None:
    """The footer shows each side's value, "—" for one not measured, and a tooltip that explains both (the units and the schedule: `tests/js/test_memory.py`)."""
    page = opened
    page.route(
        "**/api/memory",
        lambda route: answer(route, {"backend_bytes": 440401920, "frontend_bytes": None}),
    )
    open_app(page, app_url)
    expect(page.locator("#memory-backend")).to_have_text("420 MiB")
    expect(page.locator("#memory-frontend")).to_have_text("—")
    expect(page.locator("#memory")).to_contain_text("メモリ")
    title = page.locator("#memory").get_attribute("title")
    assert "ワーキングセット" in title
    assert "WebView2 のプロセス" in title
    assert "同じプロファイル" not in title
