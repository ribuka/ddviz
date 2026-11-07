"""E2E: the column search box keeps the keywords of the columns placed."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

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
