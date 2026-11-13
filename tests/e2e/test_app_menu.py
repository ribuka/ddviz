"""E2E: the desktop window's title bar and its app menu (Issue #125).

The server is started as the window starts it (`desktop=True`), and an init
script stands in for pywebview's JS API: it records the commands the menu
calls. This checks the page alone: not pywebview's calls into the window,
nor where the OS draws its caption buttons beside the row (the row keeps the
default width for them, as no window tells the page theirs).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_kept_ranges import X_ZOOM, Y_ZOOM, shown, zoom
from tests.e2e.test_scatter import place, placed_names

pytestmark = pytest.mark.e2e

# 80 characters with the extension, wide ones: too long for the row at 800 px.
LONG_NAME = "W" * 72 + ".parquet"
FAKE_API = """
window.desktopCalls = [];
window.pywebview = { api: {} };
for (const name of ["new", "quit", "version"]) {
  window.pywebview.api[name] = async () => {
    window.desktopCalls.push(name);
    return name === "version" ? "9.9.9" : null;
  };
}
"""
# titlebar.css's width for the caption buttons when the window has not told it.
DEFAULT_BUTTONS = 138


@pytest.fixture
def desktop() -> bool:
    """Serve the page as the desktop window does."""
    return True


@pytest.fixture
def scatter_path(scatter_path: Path) -> Path:
    """Give the input a name too long for the title bar."""
    assert len(LONG_NAME) == 80
    return Path(shutil.copy(scatter_path, scatter_path.with_name(LONG_NAME)))


@pytest.fixture
def menu_page(page: Page, app_page: Page) -> Page:
    """Return the page with the window's API replaced, loaded again so that it applies."""
    page.add_init_script(FAKE_API)
    page.reload()
    expect(page.locator("#titlebar")).to_be_visible()
    return page


def calls(page: Page) -> list[str]:
    """Return the window's commands the menu called, in order."""
    return page.evaluate("window.desktopCalls")


def popups(page: Page) -> list[list[str]]:
    """Return the items of the open menu and submenu."""
    return [
        popup.locator(".titlebar-item").all_inner_texts()
        for popup in page.locator(".titlebar-popup").all()
    ]


def focused(page: Page) -> str:
    """Return the text of the focused element."""
    return page.evaluate("document.activeElement.textContent")


def open_item(page: Page, *labels: str) -> None:
    """Click `…` and then each item of `labels`, in the menu and its submenu."""
    page.locator("#titlebar .titlebar-menu").click()
    for label in labels:
        page.locator(".titlebar-popup .titlebar-item").filter(has_text=label).click()


@pytest.mark.parametrize("desktop", [False])
def test_a_browser_page_has_no_title_bar(app_page: Page) -> None:
    """Served for a browser (`--port`), the page has no title bar."""
    expect(app_page.locator("#columns .column").first).to_be_visible()
    expect(app_page.locator("#titlebar")).to_have_count(0)
    assert app_page.title() == "ddviz"


def test_the_title_bar_shows_the_title_and_leaves_the_buttons_room(menu_page: Page) -> None:
    """The row shows `…` and the window's title, cut short before the caption buttons at 800 px."""
    page = menu_page
    page.set_viewport_size({"width": 800, "height": 600})
    title = page.locator("#titlebar .titlebar-title")
    expect(title).to_have_text(f"ddviz - {LONG_NAME}")
    assert page.title() == f"ddviz - {LONG_NAME}"
    menu = page.locator("#titlebar .titlebar-menu").bounding_box()
    box = title.bounding_box()
    assert menu["x"] + menu["width"] <= box["x"]
    assert box["x"] + box["width"] <= 800 - DEFAULT_BUTTONS
    assert title.evaluate("(e) => e.scrollWidth > e.clientWidth")
    assert title.evaluate("(e) => getComputedStyle(e).textOverflow") == "ellipsis"


def test_the_menu_works_with_the_mouse(menu_page: Page) -> None:
    """`…` opens File, Edit (disabled) and Help; one submenu at a time; commands call the window."""
    page = menu_page
    button = page.locator("#titlebar .titlebar-menu")
    button.click()
    assert popups(page) == [["File", "Edit", "Help"]]
    assert focused(page) == "File"
    expect(page.locator(".titlebar-item").filter(has_text="Edit")).to_be_disabled()
    page.locator(".titlebar-item").filter(has_text="Edit").click(force=True)
    assert popups(page) == [["File", "Edit", "Help"]]
    page.locator(".titlebar-item").filter(has_text="Help").click()
    assert popups(page) == [["File", "Edit", "Help"], ["Version"]]
    page.locator(".titlebar-item").filter(has_text="File").click()
    assert popups(page) == [["File", "Edit", "Help"], ["New", "Quit"]]
    # The submenu opens on the right of the menu.
    menu, submenu = (p.bounding_box() for p in page.locator(".titlebar-popup").all())
    assert submenu["x"] >= menu["x"] + menu["width"] - 1

    page.mouse.click(400, 400)
    assert popups(page) == []
    button.click()
    button.click()
    assert popups(page) == []

    open_item(page, "File", "Quit")
    assert popups(page) == []
    open_item(page, "Help", "Version")
    dialog = page.locator(".titlebar-dialog")
    expect(dialog).to_contain_text("ddviz 9.9.9")
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    assert calls(page) == ["quit", "version"]


def test_the_menu_works_with_the_keyboard(menu_page: Page) -> None:
    """Tab reaches `…`; arrows, Enter, Space and Esc move through the menu and run commands."""
    page = menu_page
    keys = page.keyboard
    page.locator("body").focus()
    keys.press("Tab")
    assert page.evaluate("document.activeElement.classList.contains('titlebar-menu')")
    keys.press("Enter")
    assert focused(page) == "File"
    keys.press("ArrowDown")
    assert focused(page) == "Help"  # Edit is skipped
    keys.press("ArrowRight")
    assert popups(page) == [["File", "Edit", "Help"], ["Version"]]
    assert focused(page) == "Version"
    keys.press("ArrowLeft")
    assert popups(page) == [["File", "Edit", "Help"]]
    assert focused(page) == "Help"
    keys.press("ArrowUp")
    keys.press("Space")
    assert popups(page) == [["File", "Edit", "Help"], ["New", "Quit"]]
    assert focused(page) == "New"
    keys.press("ArrowDown")
    assert focused(page) == "Quit"
    keys.press("ArrowDown")
    assert focused(page) == "New"
    keys.press("Escape")
    assert popups(page) == [["File", "Edit", "Help"]]
    assert focused(page) == "File"
    keys.press("Escape")
    assert popups(page) == []
    assert focused(page) == "…"

    keys.press("Space")
    keys.press("ArrowUp")
    assert focused(page) == "Help"
    keys.press("Enter")
    keys.press("Enter")
    expect(page.locator(".titlebar-dialog")).to_contain_text("ddviz 9.9.9")
    keys.press("Escape")
    expect(page.locator(".titlebar-dialog")).to_have_count(0)
    assert popups(page) == []
    assert calls(page) == ["version"]


def test_new_asks_first_and_keeps_the_graph_when_cancelled(menu_page: Page) -> None:
    """`New` asks with the focus on Cancel; Cancel and Esc keep the columns, filter and ranges; 戻る calls the window."""
    page = menu_page
    place(page, "x", "x")
    place(page, "y", "y")
    page.locator("#columns .column").filter(
        has=page.get_by_text("label", exact=True)
    ).drag_to(page.locator("#filters"))
    expect(page.locator(".filter-card")).to_have_count(1)
    zoom(page, {"xaxis.range": X_ZOOM, "yaxis.range": Y_ZOOM})
    before = (placed_names(page), shown(page, "xaxis"), shown(page, "yaxis"))
    dialog = page.locator(".titlebar-dialog")

    open_item(page, "File", "New")
    expect(dialog).to_contain_text(
        "現在のグラフ設定とフィルタを破棄し、Parquet 選択画面に戻りますか？"
    )
    assert dialog.get_by_role("button").all_inner_texts() == ["戻る", "キャンセル"]
    assert focused(page) == "キャンセル"
    dialog.get_by_role("button", name="キャンセル").click()
    expect(dialog).to_have_count(0)

    open_item(page, "File", "New")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    assert calls(page) == []
    assert (placed_names(page), shown(page, "xaxis"), shown(page, "yaxis")) == before
    expect(page.locator(".filter-card")).to_have_count(1)

    open_item(page, "File", "New")
    dialog.get_by_role("button", name="戻る").click()
    expect(dialog).to_have_count(0)
    page.wait_for_function("window.desktopCalls.length === 1")
    assert calls(page) == ["new"]
