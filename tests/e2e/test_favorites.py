"""E2E: the favorites of the drawing settings, saved and recalled from the star button's pull-down (Issue #278)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_app_menu import FAKE_API, GEOMETRY
from tests.e2e.test_axis_format import open_dialog
from tests.e2e.test_scatter import place, wait_idle, watch_errors
from tests.e2e.test_undo import (
    FULL,
    REDO,
    chip_names,
    hold_next_plot,
    plots,
    press,
    x_and_y,
)

pytestmark = pytest.mark.e2e

FAVORITES = "お気に入り"
SAVE = "現在の描画を保存"
CHOOSE = "上書きするものを選んでください"
EMPTY = "保存済みの描画はありません"
TIME = re.compile(r"^\d\d:\d\d$")
# The places of the reference lines on y drawn.
LINES = "() => (document.getElementById('plot').layout.shapes ?? []).filter((s) => s.yref?.startsWith('y') && s.y0 === s.y1).map((s) => s.y0)"


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write x and y around 0, and z around 100."""
    rng = np.random.default_rng(0)
    n = 2000
    frame = pl.DataFrame(
        {
            "x": rng.normal(0, 1, n),
            "y": rng.normal(0, 1, n),
            "z": rng.normal(100, 1, n),
        }
    )
    path = tmp_path / "favorites.parquet"
    frame.write_parquet(path)
    return path


def button(page: Page) -> Locator:
    """Return the star button."""
    return page.get_by_role("button", name=FAVORITES, exact=True)


def menu(page: Page) -> Locator:
    """Return the pull-down."""
    return page.locator(".favorites-menu")


def rows(page: Page) -> Locator:
    """Return the rows of the favorites in the pull-down."""
    return menu(page).locator(".favorites-row")


def open_menu(page: Page) -> Locator:
    """Open the pull-down, unless it is open, and return it."""
    if not menu(page).count():
        button(page).click()
    expect(menu(page)).to_be_visible()
    return menu(page)


def save(page: Page) -> None:
    """Save the current drawing from the pull-down, which stays open."""
    pulled = open_menu(page)
    count = rows(page).count()
    pulled.get_by_role("menuitem", name=SAVE).click()
    expect(rows(page)).to_have_count(count + 1)


def close_menu(page: Page) -> None:
    """Close the pull-down with Escape."""
    page.keyboard.press("Escape")
    expect(menu(page)).to_have_count(0)


def shown_rows(page: Page) -> list[int]:
    """Return the indices of the rows marked shown."""
    marks = rows(page).evaluate_all("(rows) => rows.map((r) => r.querySelector('.favorites-shown') !== null)")
    return [i for i, marked in enumerate(marks) if marked]


def tag_thumbnails(page: Page) -> None:
    """Tag the thumbnail of each row with its index."""
    rows(page).evaluate_all("(rows) => rows.forEach((r, i) => { r.querySelector('canvas').dataset.tag = String(i); })")


def thumbnail_tags(page: Page) -> list[str | None]:
    """Return the tags of the rows' thumbnails (`tag_thumbnails`), None for an untagged one."""
    return rows(page).evaluate_all("(rows) => rows.map((r) => r.querySelector('canvas')?.dataset.tag ?? null)")


def y_middle(page: Page) -> float:
    """Return the middle of the drawn y range."""
    return page.evaluate(f"() => {{ const r = {FULL}.yaxis.range; return (r[0] + r[1]) / 2; }}")


def test_the_button_stands_right_of_redo(app_page: Page) -> None:
    """In a browser the star is right of redo; on an empty graph its pull-down opens under it with the save disabled and no favorites; a second press, Escape or a press outside closes it."""
    page = app_page
    errors = watch_errors(page)
    expect(page.locator("#columns .column").first).to_be_visible()
    top = page.locator("#top > *")
    expect(top.nth(1)).to_have_attribute("aria-label", REDO)
    expect(top.nth(2)).to_have_attribute("aria-label", FAVORITES)
    star = button(page)
    expect(star).to_have_attribute("title", FAVORITES)
    expect(star).to_have_attribute("aria-haspopup", "menu")
    redo = page.get_by_role("button", name=REDO).bounding_box()
    box = star.bounding_box()
    assert redo["x"] + redo["width"] <= box["x"]
    assert box["x"] + box["width"] <= page.locator("#elements").bounding_box()["x"]

    pulled = open_menu(page)
    expect(star).to_have_attribute("aria-expanded", "true")
    assert pulled.bounding_box()["y"] >= box["y"] + box["height"]
    expect(pulled.get_by_role("menuitem", name=SAVE)).to_be_disabled()
    expect(pulled.get_by_text(EMPTY)).to_be_visible()
    expect(rows(page)).to_have_count(0)
    star.click()
    expect(menu(page)).to_have_count(0)
    expect(star).to_have_attribute("aria-expanded", "false")
    open_menu(page)
    close_menu(page)
    open_menu(page)
    page.mouse.click(5, page.viewport_size["height"] - 5)
    expect(menu(page)).to_have_count(0)
    assert errors == []


def test_save_mark_and_recall(app_page: Page) -> None:
    """A drawing saved is a row with a thumbnail, its time and the shown mark, and saves no twin; another column clears the mark; the row recalls its settings, which Ctrl+Z takes back."""
    page = app_page
    errors = watch_errors(page)
    x_and_y(page)
    save(page)
    row = rows(page).first
    canvas = row.locator("canvas")
    expect(canvas).to_have_count(1)
    assert canvas.evaluate("(c) => c.width") > 0
    assert canvas.bounding_box()["width"] > 0
    assert TIME.match(row.locator(".favorites-time").inner_text())
    assert shown_rows(page) == [0]
    expect(menu(page).get_by_role("menuitem", name=SAVE)).to_be_disabled()
    close_menu(page)

    place(page, "z", "y")
    open_menu(page)
    assert shown_rows(page) == []
    expect(menu(page).get_by_role("menuitem", name=SAVE)).to_be_enabled()
    with page.expect_request("**/api/plot") as request:
        rows(page).first.click()
    expect(menu(page)).to_have_count(0)
    assert request.value.post_data_json["encoding"]["y"] == ["y"]
    wait_idle(page)
    assert chip_names(page, "y") == ["y"]
    assert y_middle(page) < 50
    open_menu(page)
    assert shown_rows(page) == [0]
    close_menu(page)

    # Undo goes back to the settings before the recall.
    assert press(page, "Control+z")["encoding"]["y"] == ["z"]
    assert chip_names(page, "y") == ["z"]
    assert errors == []


def three_saved(page: Page) -> None:
    """Save (x, y), (x, z) and (z, z) as the three favorites."""
    x_and_y(page)
    save(page)
    close_menu(page)
    place(page, "z", "y")
    save(page)
    close_menu(page)
    place(page, "z", "x")
    save(page)
    close_menu(page)


def test_a_fourth_save_overwrites_the_row_picked(app_page: Page) -> None:
    """With three saved, a save asks for the row to overwrite: Escape leaves the rows as they were; a pick replaces that row alone, at its place."""
    page = app_page
    errors = watch_errors(page)
    three_saved(page)
    place(page, "y", "x")
    pulled = open_menu(page)
    tag_thumbnails(page)
    pulled.get_by_role("menuitem", name=SAVE).click()
    expect(pulled.get_by_text(CHOOSE)).to_be_visible()
    expect(pulled.get_by_role("menuitem", name="キャンセル")).to_be_visible()
    page.keyboard.press("Escape")
    expect(pulled.get_by_text(CHOOSE)).to_have_count(0)
    expect(pulled).to_be_visible()
    expect(rows(page)).to_have_count(3)
    assert thumbnail_tags(page) == ["0", "1", "2"]
    assert shown_rows(page) == []

    pulled.get_by_role("menuitem", name=SAVE).click()
    expect(pulled.get_by_text(CHOOSE)).to_be_visible()
    rows(page).nth(1).click()
    expect(pulled.get_by_text(CHOOSE)).to_have_count(0)
    expect(rows(page)).to_have_count(3)
    assert thumbnail_tags(page) == ["0", None, "2"]
    assert shown_rows(page) == [1]
    expect(pulled.get_by_role("menuitem", name=SAVE)).to_be_disabled()
    assert errors == []


def test_delete_moves_the_rows_up(app_page: Page) -> None:
    """The × of a row removes it and the rows below move up; by keys, the pull-down opens on its first enabled item, the arrows move to a row, and Delete removes it."""
    page = app_page
    errors = watch_errors(page)
    three_saved(page)
    open_menu(page)
    tag_thumbnails(page)
    rows(page).first.get_by_role("button", name="削除").click()
    expect(rows(page)).to_have_count(2)
    assert thumbnail_tags(page) == ["1", "2"]
    close_menu(page)

    button(page).focus()
    page.keyboard.press("Enter")
    expect(menu(page)).to_be_visible()
    # The save is disabled (the drawing is the last row's): the first row has the focus.
    expect(rows(page).first).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(rows(page).nth(1)).to_be_focused()
    page.keyboard.press("Delete")
    expect(rows(page)).to_have_count(1)
    assert thumbnail_tags(page) == ["1"]
    expect(menu(page).get_by_role("menuitem", name=SAVE)).to_be_enabled()
    assert errors == []


@pytest.mark.parametrize("height", [300])
def test_the_pull_down_stays_in_a_small_window(app_page: Page, height: int) -> None:
    """In a window 300px high the pull-down of three rows lies inside it, placed at its size with its rows, and the third row's × is reached."""
    page = app_page
    errors = watch_errors(page)
    three_saved(page)
    page.set_viewport_size({"width": page.viewport_size["width"], "height": height})
    wait_idle(page)
    pulled = open_menu(page)
    expect(rows(page)).to_have_count(3)
    box = pulled.bounding_box()
    assert box["y"] >= 0
    assert box["y"] + box["height"] <= height
    remove = rows(page).nth(2).get_by_role("button", name="削除")
    remove.scroll_into_view_if_needed()
    target = remove.bounding_box()
    assert 0 <= target["y"] and target["y"] + target["height"] <= height
    remove.click()
    expect(rows(page)).to_have_count(2)
    box = pulled.bounding_box()
    assert box["y"] + box["height"] <= height
    assert errors == []


def test_a_recall_while_plotting_replaces_the_plot(app_page: Page) -> None:
    """A row recalled while a plot is held draws the row's settings; the held plot, let go, is not drawn."""
    page = app_page
    errors = watch_errors(page)
    x_and_y(page)
    save(page)
    close_menu(page)
    place(page, "z", "y")
    assert y_middle(page) > 50
    # X to y while Y stays z (around 100): held.
    held = hold_next_plot(page)
    source = page.locator("#columns .column").filter(has=page.get_by_text("y", exact=True))
    source.drag_to(page.locator('.zone[data-role="x"]'))
    page.wait_for_function("() => document.getElementById('plot').classList.contains('busy')")
    with page.expect_request("**/api/plot") as request:
        open_menu(page)
        rows(page).first.click()
    assert request.value.post_data_json["encoding"]["y"] == ["y"]
    wait_idle(page)
    assert chip_names(page, "x") == ["x"]
    assert chip_names(page, "y") == ["y"]
    assert y_middle(page) < 50
    held[0].continue_()
    page.wait_for_timeout(300)
    wait_idle(page)
    page.unroute("**/api/plot")
    assert chip_names(page, "x") == ["x"]
    assert chip_names(page, "y") == ["y"]
    assert y_middle(page) < 50
    assert errors == []


def set_line(page: Page, value: str) -> None:
    """Set the y axis' fixed reference lines to one at `value` in the dialog, without a plot."""
    dialog = open_dialog(page, "y")
    for remove in dialog.locator(".axis-dialog-line").get_by_role("button", name="削除").all():
        remove.click()
    dialog.locator("select[name=line-type]").select_option("value")
    dialog.locator("input[name=line]").fill(value)
    dialog.get_by_role("button", name="追加").click()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    page.wait_for_function(f"(v) => ({LINES})().includes(v)", arg=float(value))


def test_a_row_of_other_lines_alone_draws_without_a_plot(app_page: Page) -> None:
    """Two rows whose fixed reference lines alone differ recall each other without a plot, and mark the row recalled; Ctrl+Z goes back without a plot."""
    page = app_page
    errors = watch_errors(page)
    x_and_y(page)
    sent = plots(page)
    set_line(page, "1")
    save(page)
    close_menu(page)
    set_line(page, "0.5")
    save(page)
    assert shown_rows(page) == [1]
    rows(page).first.click()
    page.wait_for_function(f"() => JSON.stringify(({LINES})()) === '[1]'")
    wait_idle(page)
    open_menu(page)
    assert shown_rows(page) == [0]
    close_menu(page)
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("Control+z")
    page.wait_for_function(f"() => JSON.stringify(({LINES})()) === '[0.5]'")
    wait_idle(page)
    assert sent == []
    assert errors == []


# Remembers the page's list of favorites (`window.favoritesList`) at its
# first `add`: a row of settings the save never takes (no figure drawn) is
# put in through it.
CATCH_LIST = """async () => {
  const m = await import("/static/js/favorites.js");
  const add = m.Favorites.prototype.add;
  m.Favorites.prototype.add = function (...args) {
    window.favoritesList = this;
    return add.apply(this, args);
  };
}"""

# Turns the first favorite into its settings without the Y column.
X_ONLY = """() => {
  const list = window.favoritesList;
  const settings = structuredClone(list.items[0].settings);
  const zones = settings.zones;
  zones.encoding.y = [];
  zones.numeric = zones.numeric.filter(([name]) => name !== "y");
  zones.temporal = zones.temporal.filter(([name]) => name !== "y");
  list.replace(0, settings, list.items[0].thumbnail);
}"""


def test_a_row_without_a_figure_is_committed_at_once(app_page: Page) -> None:
    """A row of X alone (put in the list by the test: no figure, no save) is recalled without a plot, and Ctrl+Z goes back to the graph before."""
    page = app_page
    errors = watch_errors(page)
    page.evaluate(CATCH_LIST)
    x_and_y(page)
    save(page)
    close_menu(page)
    page.evaluate(X_ONLY)
    sent = plots(page)
    open_menu(page)
    assert shown_rows(page) == []
    rows(page).first.click()
    expect(page.locator('.zone[data-role="y"] .chip-name')).to_have_count(0)
    assert chip_names(page, "x") == ["x"]
    wait_idle(page)
    assert sent == []
    open_menu(page)
    assert shown_rows(page) == [0]
    expect(menu(page).get_by_role("menuitem", name=SAVE)).to_be_disabled()
    close_menu(page)
    assert press(page, "Control+z")["encoding"]["y"] == ["y"]
    assert chip_names(page, "y") == ["y"]
    assert errors == []


@pytest.mark.parametrize("desktop", [True])
def test_the_window_has_the_button_in_its_title_bar(page: Page, app_page: Page) -> None:
    """In the window the star is right of redo and left of the title, out of the caption's drag, and its pull-down opens under it."""
    page.add_init_script(GEOMETRY)
    page.add_init_script(FAKE_API)
    page.reload()
    expect(page.locator("#titlebar")).to_be_visible()
    expect(page.locator("#top .favorites-button")).to_have_count(0)
    star = page.locator("#titlebar").get_by_role("button", name=FAVORITES, exact=True)
    redo = page.locator("#titlebar").get_by_role("button", name=REDO).bounding_box()
    title = page.locator("#titlebar .titlebar-title").bounding_box()
    menu_button = page.locator("#titlebar .titlebar-menu").bounding_box()
    box = star.bounding_box()
    assert redo["x"] + redo["width"] <= box["x"]
    assert box["x"] + box["width"] <= title["x"]
    assert star.evaluate("(e) => getComputedStyle(e).appRegion") == "no-drag"
    assert box["height"] == pytest.approx(menu_button["height"])
    assert box["width"] == pytest.approx(menu_button["width"], abs=0.5)
    star.click()
    pulled = menu(page)
    expect(pulled).to_be_visible()
    under = pulled.bounding_box()
    assert under["y"] >= box["y"] + box["height"]
    assert under["x"] == pytest.approx(box["x"], abs=1)
