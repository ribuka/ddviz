"""E2E: the footer shows the memory of the backend and the frontend, fetched about every second."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.conftest import TOKEN

pytestmark = pytest.mark.e2e

BOTH = {"backend_bytes": 440401920, "frontend_bytes": 1342177280}


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


def test_both_sides_show_in_their_units(opened: Page, app_url: str) -> None:
    """Under 1 GiB in whole MiB, from 1 GiB in GiB with two decimals; the tooltip explains both."""
    page = opened
    page.route("**/api/memory", lambda route: answer(route, BOTH))
    open_app(page, app_url)
    expect(page.locator("#memory-backend")).to_have_text("420 MiB")
    expect(page.locator("#memory-frontend")).to_have_text("1.25 GiB")
    expect(page.locator("#memory")).to_contain_text("メモリ")
    title = page.locator("#memory").get_attribute("title")
    assert "ワーキングセット" in title
    assert "同じプロファイル" in title
    texts = page.evaluate(
        """async () => {
          const { memoryText } = await import("/static/js/memory.js");
          return [0, 1048575, 1073741823, 1073741824, null].map(memoryText);
        }"""
    )
    assert texts == ["0 MiB", "1 MiB", "1023 MiB", "1.00 GiB", "—"]


def test_a_side_not_measured_shows_a_dash(opened: Page, app_url: str) -> None:
    """A null side shows "—", the other its value."""
    page = opened
    page.route(
        "**/api/memory",
        lambda route: answer(route, {"backend_bytes": 440401920, "frontend_bytes": None}),
    )
    open_app(page, app_url)
    expect(page.locator("#memory-backend")).to_have_text("420 MiB")
    expect(page.locator("#memory-frontend")).to_have_text("—")


def test_a_failed_fetch_shows_dashes_and_the_next_one_recovers(
    opened: Page, app_url: str
) -> None:
    """A failed request shows both as "—" without an error; the next good answer shows the values."""
    page = opened
    failing = [True]

    def handle(route: Route) -> None:
        if failing[0]:
            route.fulfill(status=500, body="boom")
        else:
            answer(route, BOTH)

    page.route("**/api/memory", handle)
    open_app(page, app_url)
    page.wait_for_timeout(1500)
    expect(page.locator("#memory-backend")).to_have_text("—")
    expect(page.locator("#memory-frontend")).to_have_text("—")
    expect(page.locator("#status")).not_to_have_class("notice-error")
    expect(page.locator("#toasts .toast")).to_have_count(0)
    failing[0] = False
    expect(page.locator("#memory-backend")).to_have_text("420 MiB")
    expect(page.locator("#memory-frontend")).to_have_text("1.25 GiB")


def test_no_request_starts_while_one_is_pending(opened: Page, app_url: str) -> None:
    """A slow request holds the next; once it ends, one request follows, not a backlog."""
    page = opened
    held: list[Route] = []
    page.route("**/api/memory", lambda route: held.append(route))
    open_app(page, app_url)
    page.wait_for_timeout(3500)
    assert len(held) == 1
    answer(held[0], BOTH)
    expect(page.locator("#memory-backend")).to_have_text("420 MiB")
    page.wait_for_timeout(500)
    assert len(held) == 2  # the next one started at once: its second had passed
    answer(held[1], BOTH)
    page.wait_for_timeout(1500)
    assert 2 <= len(held) <= 4
    for route in held[2:]:
        answer(route, BOTH)
