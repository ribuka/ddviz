"""E2E: an error in the status bar has its icon and a toast at the top right."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.test_scatter import SETTLED, place

pytestmark = pytest.mark.e2e


def fail(route: Route) -> None:
    """Answer a plot request as a failed task does (FastAPI's error body)."""
    route.fulfill(
        status=500,
        content_type="application/json",
        body=json.dumps({"detail": "集約に失敗した"}),
    )


def test_an_error_shows_its_icon_and_a_toast(app_page: Page) -> None:
    """A failed plot marks the status as an error and opens a toast; the next plot clears the mark."""
    page = app_page
    page.route("**/api/plot", fail)
    place(page, "x", "x", plots=False)
    place(page, "y", "y", plots=False)

    status = page.locator("#status")
    expect(status).to_have_text("エラー: 集約に失敗した")
    expect(status).to_have_class("notice-error")
    icon = status.evaluate("e => getComputedStyle(e, '::before').content")
    assert "!" in icon

    toast = page.locator("#toasts .toast")
    expect(toast).to_have_count(1)  # the same error again replaces its toast
    expect(toast).to_have_text("エラー: 集約に失敗した×")
    expect(toast).to_have_attribute("role", "alert")
    box = toast.bounding_box()
    viewport = page.viewport_size
    assert box is not None and viewport is not None
    assert box["y"] < 50
    assert box["x"] + box["width"] > viewport["width"] - 50

    toast.get_by_role("button", name="閉じる").click()
    expect(toast).to_have_count(0)

    page.unroute("**/api/plot")
    place(page, "color", "color", plots=False)
    page.wait_for_function(SETTLED)
    expect(status).not_to_have_class("notice-error")
    expect(page.locator("#toasts .toast")).to_have_count(0)
