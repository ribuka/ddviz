"""E2E: the join dialog, opened with Ctrl+J, joins another table to the input (Issue #344).

The input is `scatter_path` (2,003 rows, ``label`` unique); the table to
join is `join_paths` (conftest.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_axis_format import open_dialog
from tests.e2e.test_scatter import drawn_task, place

pytestmark = pytest.mark.e2e

# The columns the join by `label` adds, in the column list's order.
ADDED = ["_joined", "color_joined", "score", "source_joined", "filename_joined"]
# 1,500 of the 2,003 rows of the input match.
JOINED_TOAST = "5 列を結合しました。元の表の 74.9% の行が結合できました。"
ONCE_TOAST = "結合は 1 回だけです。やり直すには File → New で開き直してください。"
# Records whether the page took the last Ctrl+J (its default prevented),
# after the page's listeners.
WATCH_J = """window.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key.toLowerCase() === "j") window.lastJ = event.defaultPrevented;
});"""


def join_dialog(page: Page) -> Locator:
    """Return the join dialog."""
    return page.locator("dialog#join")


def press_ctrl_j(page: Page) -> bool:
    """Press Ctrl+J and return whether the page took it (prevented the browser's)."""
    page.evaluate("window.lastJ = undefined")
    page.keyboard.press("Control+j")
    page.wait_for_function("window.lastJ !== undefined")
    return page.evaluate("window.lastJ")


def key_field(page: Page, row: int, side: int) -> Locator:
    """Return a key's field: `side` 0 for the input's column, 1 for the joined table's."""
    return join_dialog(page).locator(".join-key").nth(row).locator(".join-key-input").nth(side)


def pick(page: Page, row: int, side: int, typed: str, name: str) -> None:
    """Type `typed` in a key's field and pick `name` among the candidates."""
    field = key_field(page, row, side)
    field.fill(typed)
    join_dialog(page).locator(".join-candidate").filter(has_text=name).first.click()
    expect(field).to_have_value(name)


def read_source(page: Page, paths: list[Path]) -> None:
    """Enter `paths` in the dialog and read them."""
    dialog = join_dialog(page)
    dialog.locator(".join-paths").fill("\n".join(str(p) for p in paths))
    dialog.get_by_role("button", name="読む").click()
    expect(dialog.locator(".join-source-result")).to_have_text("2 ファイル・1,500 行・5 列")


def run_join(page: Page) -> None:
    """Press `結合` and wait for the dialog to close and the toast."""
    join_dialog(page).get_by_role("button", name="結合", exact=True).click()
    expect(join_dialog(page)).not_to_be_visible()
    expect(page.locator("#toasts .toast-text").filter(has_text=JOINED_TOAST)).to_be_visible()


def joined_marks(page: Page) -> list[list[str]]:
    """Return the listed columns with the mark of the join, and the mark's title."""
    return page.evaluate(
        """() => [...document.querySelectorAll("#columns .column")]
          .filter((item) => item.querySelector(".joined"))
          .map((item) => [item.dataset.name, item.querySelector(".joined").textContent, item.querySelector(".joined").title])"""
    )


@pytest.fixture
def join_page(app_page: Page) -> Page:
    """Return the page once its columns are listed, recording whether it takes Ctrl+J."""
    app_page.evaluate(WATCH_J)
    expect(app_page.locator("#columns .column").first).to_be_visible()
    app_page.wait_for_function("window.ddvizCanJoin()")
    return app_page


def test_ctrl_j_opens_the_dialog_but_not_from_a_field_or_a_dialog(join_page: Page) -> None:
    """Ctrl+J opens the dialog from the graph's page; in a filter's field or with the axis dialog open, the key is the browser's."""
    page = join_page
    dialog = join_dialog(page)
    page.evaluate("document.activeElement.blur()")
    assert press_ctrl_j(page) is True
    expect(dialog).to_be_visible()
    expect(dialog.locator(".join-paths")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()

    page.locator("#columns .column").filter(has=page.get_by_text("label", exact=True)).drag_to(
        page.locator("#filters")
    )
    search = page.locator(".filter-card .filter-search input")
    search.focus()
    assert press_ctrl_j(page) is False
    expect(dialog).not_to_be_visible()

    place(page, "x", "x")
    place(page, "y", "y")
    axis = open_dialog(page, "x")
    assert press_ctrl_j(page) is False
    expect(dialog).not_to_be_visible()
    page.keyboard.press("Escape")
    expect(axis).not_to_be_visible()
    page.evaluate("document.activeElement.blur()")
    assert press_ctrl_j(page) is True
    expect(dialog).to_be_visible()


def test_a_join_by_keys_lists_the_joined_columns_marked_and_they_draw(
    join_page: Page, join_paths: list[Path]
) -> None:
    """Read two files, pick a key (its same name filled), join: the toast tells the share, the columns are marked and draw."""
    page = join_page
    page.keyboard.press("Control+j")
    read_source(page, join_paths)
    pick(page, 0, 0, "lab", "label")
    expect(key_field(page, 0, 1)).to_have_value("label")
    run_join(page)

    names = page.locator("#columns .column").evaluate_all("(items) => items.map((i) => i.dataset.name)")
    assert names[-len(ADDED) :] == ADDED
    title = "結合：a.parquet and 1 more"
    expect(page.locator("#columns .column .joined")).to_have_count(len(ADDED))
    assert joined_marks(page) == [[name, "J", title] for name in ADDED]

    place(page, "score", "x")
    place(page, "y", "y")
    drawn_task(page)
    expect(page.locator("#status")).to_contain_text("行")
    expect(page.locator("#empty")).to_be_hidden()


def test_a_refused_read_or_join_tells_why_and_the_join_is_done_once(
    join_page: Page, join_paths: list[Path], tmp_path: Path
) -> None:
    """A missing path and a repeated key are told in the dialog, which stays open; another key joins, and Ctrl+J then tells it is done."""
    page = join_page
    dialog = join_dialog(page)
    page.keyboard.press("Control+j")
    missing = tmp_path / "missing.parquet"
    dialog.locator(".join-paths").fill(str(missing))
    with page.expect_response("**/api/join/source") as answered:
        dialog.get_by_role("button", name="読む").click()
    detail = answered.value.json()["detail"]
    assert answered.value.status == 400
    result = dialog.locator(".join-source-result")
    expect(result).to_have_text(detail)
    expect(result).to_have_class("join-source-result join-failed")
    expect(key_field(page, 0, 0)).to_be_disabled()

    read_source(page, join_paths)
    pick(page, 0, 0, "colo", "color")
    expect(key_field(page, 0, 1)).to_have_value("color")
    with page.expect_response("**/api/join") as answered:
        dialog.get_by_role("button", name="結合", exact=True).click()
    detail = answered.value.json()["detail"]
    assert answered.value.status == 400
    assert detail.startswith("結合する表でキーが重複しています：3 組")
    expect(dialog.locator(".join-error")).to_have_text(detail)
    expect(dialog).to_be_visible()
    expect(key_field(page, 0, 0)).to_be_enabled()

    pick(page, 0, 0, "lab", "label")
    pick(page, 0, 1, "lab", "label")
    run_join(page)
    expect(page.locator("#columns .column .joined")).to_have_count(len(ADDED))

    page.evaluate("document.activeElement.blur()")
    assert press_ctrl_j(page) is True
    expect(page.locator("#toasts .toast-text").filter(has_text=ONCE_TOAST)).to_be_visible()
    expect(dialog).not_to_be_visible()
    assert page.evaluate("window.ddvizCanJoin()") is False
