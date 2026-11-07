"""E2E: the column search box keeps the keywords of the columns placed."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ddviz.server.settings import ColumnsSettings, Settings

pytestmark = pytest.mark.e2e


def test_placing_a_found_column_keeps_its_keyword(app_page: Page) -> None:
    """Placing a column keeps the keyword; focusing the box offers it back, and × and the last row remove."""
    page = app_page
    search = page.locator(".column-search")
    columns = page.locator("#columns .column")
    history = page.locator(".search-history")
    words = history.locator(".search-history-word")
    expect(columns.filter(has_text="label")).to_be_visible()

    # Typing alone keeps nothing.
    search.fill("lab")
    expect(columns).to_have_count(1)
    search.blur()
    search.focus()
    expect(history).to_have_count(0)
    # A column dropped on the filter pane, then one on a role.
    columns.first.drag_to(page.locator("#filters"))
    expect(page.locator("#filters .filter-card")).to_have_count(1)
    search.fill(" X ")
    column = columns.filter(has=page.get_by_text("x", exact=True))
    zone = page.locator('.zone[data-role="x"]')
    column.drag_to(zone)
    expect(zone.locator(".chip-name")).to_have_text("x")

    search.fill("")
    search.blur()
    search.focus()
    expect(words).to_have_text(["X", "lab"])
    # Typing closes the list.
    search.press_sequentially("y")
    expect(history).to_have_count(0)
    search.fill("")
    search.press("ArrowDown")
    expect(words).to_have_count(2)
    search.press("ArrowDown")
    search.press("ArrowDown")
    search.press("Enter")
    expect(search).to_have_value("lab")
    expect(history).to_have_count(0)
    expect(columns).to_have_count(1)

    # The history stays with the input after a reload.
    page.reload()
    search.focus()
    expect(words).to_have_text(["X", "lab"])
    words.first.click()
    expect(search).to_have_value("X")
    expect(search).to_be_focused()
    search.fill("")
    search.press("ArrowDown")
    history.locator(".search-history-row").first.locator(
        ".search-history-remove"
    ).click()
    expect(words).to_have_text(["lab"])
    expect(search).to_be_focused()
    history.locator(".search-history-clear").click()
    expect(history).to_have_count(0)
    search.blur()
    search.focus()
    expect(history).to_have_count(0)


@pytest.mark.parametrize(
    "settings", [Settings(columns=ColumnsSettings(max_history=50))]
)
def test_a_long_history_scrolls_within_the_window(app_page: Page, app_url: str) -> None:
    """A history taller than the room below the box scrolls; ↓ keeps the keyword it reaches in sight."""
    page = app_page
    page.set_viewport_size({"width": 1000, "height": 600})
    for i in range(50):
        response = page.request.post(
            f"{app_url}/api/search-history", data={"word": f"word{i}"}
        )
        assert response.ok
    search = page.locator(".column-search")
    history = page.locator(".search-history")
    expect(page.locator("#columns .column").first).to_be_visible()
    search.focus()
    expect(history.locator(".search-history-word")).to_have_count(50)
    box = history.bounding_box()
    assert box["y"] + box["height"] <= 600
    clear = history.locator(".search-history-clear")
    clear.scroll_into_view_if_needed()
    expect(clear).to_be_in_viewport()

    history.evaluate("menu => { menu.scrollTop = 0; }")
    for _ in range(35):
        search.press("ArrowDown")
    active = history.locator(".search-history-row.active")
    expect(active).to_have_text("word15×")
    expect(active).to_be_in_viewport()
    search.press("Enter")
    expect(search).to_have_value("word15")
