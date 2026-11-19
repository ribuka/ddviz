"""E2E: the file of the drawing settings, saved from the graph's page and applied by a server opened with it (Issue #287).

The window's chooser, which opens the file and the data, is checked in
`tests/desktop/test_window.py`; here a server is started with the file's
content (`create_app(initial_draw=...)`) as the window starts it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, expect

from ddviz.server.settings_store import SettingsStore
from ddviz.shared.drawfile import parse
from tests.e2e.conftest import TOKEN, make_app, served
from tests.e2e.test_app_menu import FAKE_API, GEOMETRY, open_item, popups
from tests.e2e.test_favorites import menu, open_menu, set_line
from tests.e2e.test_scatter import drop_on_filters, wait_idle, watch_errors
from tests.e2e.test_undo import REDO, UNDO, chip_names, x_and_y

pytestmark = pytest.mark.e2e

SAVE_FILE = "描画設定を保存…"
# Stands in for the window's `save_draw_file`: records the file's content.
FAKE_SAVE = """
window.savedDrawFiles = [];
window.pywebview.api.save_draw_file = async (text) => {
  window.savedDrawFiles.push(text);
  return { saved: "scatter.ddviz.json" };
};
"""


def set_marker_size(page: Page, size: int) -> None:
    """Pick the size of every series' markers in the points' menu, and wait for its plot."""
    page.locator('#elements .element[data-element="points"]').click(button="right")
    with page.expect_request("**/api/plot"):
        page.locator(".shape-menu").get_by_text(f"{size} px", exact=True).click()
    wait_idle(page)


def download(page: Page) -> tuple[str, dict]:
    """Save the drawing settings from the favorites' pull-down; return the file's name and content."""
    item = open_menu(page).get_by_role("menuitem", name=SAVE_FILE)
    expect(item).to_be_enabled()
    with page.expect_download() as downloaded:
        item.click()
    expect(menu(page)).to_have_count(0)
    path = Path(downloaded.value.path())
    return downloaded.value.suggested_filename, json.loads(path.read_text(encoding="utf-8"))


def saved_file(page: Page) -> dict:
    """Draw x against y with 9 px markers and return the file of its drawing settings."""
    x_and_y(page)
    set_marker_size(page, 9)
    return download(page)[1]


@contextmanager
def opened_with(
    page: Page,
    content: dict,
    tmp_path: Path,
    scatter_path: Path,
    settings_store: SettingsStore,
) -> Iterator[str]:
    """Serve the input again, opened with the file `content`; leave its page before it stops."""
    app = make_app(tmp_path, scatter_path, settings_store, False, content, run="again")
    with served(app) as url:
        try:
            yield f"{url}/?token={TOKEN}"
        finally:
            page.goto("about:blank")


def test_a_saved_file_draws_the_same_graph_again(
    page: Page, app_page: Page, tmp_path: Path, scatter_path: Path, settings_store: SettingsStore
) -> None:
    """The file downloaded holds the zones, the size, the filter card, a reference line and the columns; a server opened with it draws them, with no step to undo."""
    errors = watch_errors(page)
    expect(app_page.locator("#columns .column").first).to_be_visible()
    # Nothing drawn: nothing to save.
    expect(open_menu(page).get_by_role("menuitem", name=SAVE_FILE)).to_be_disabled()
    page.keyboard.press("Escape")
    x_and_y(page)
    set_marker_size(page, 9)
    drop_on_filters(page, page.locator("#columns .column").filter(has=page.get_by_text("label", exact=True)), 1)
    wait_idle(page)
    set_line(page, "0.5")
    name, content = download(page)
    assert name == "scatter.ddviz.json"
    assert content["format"] == "ddviz-draw-settings"
    assert content["version"] == 1
    assert content["source"] == {"paths": [str(scatter_path)], "relative": None, "recursive": False}
    assert content["columns"] == {"label": "categorical", "x": "numeric", "y": "numeric"}
    settings = content["settings"]
    assert settings["zones"]["encoding"]["x"] == ["x"]
    assert settings["zones"]["encoding"]["y"] == ["y"]
    assert settings["options"]["shapeSize"] == 9
    assert [[line["type"], line["value"]] for line in dict(settings["axes"]["dialog"])["y"]["lines"]] == [["value", 0.5]]
    # The chooser reads what the page saved (`SETTINGS_SHAPE`).
    assert parse(json.dumps(content)).content == content
    assert errors == []

    with opened_with(page, content, tmp_path, scatter_path, settings_store) as url:
        with page.expect_request("**/api/plot") as request:
            page.goto(url)
        body = request.value.post_data_json
        assert body["encoding"]["x"] == ["x"]
        assert body["encoding"]["y"] == ["y"]
        assert body["shape_size"] == 9
        wait_idle(page)
        assert chip_names(page, "x") == ["x"]
        assert chip_names(page, "y") == ["y"]
        expect(page.locator(".filter-card")).to_have_count(1)
        expect(page.locator("#empty")).to_be_hidden()
        # The settings read are the first step: nothing to undo.
        expect(page.get_by_role("button", name=UNDO)).to_be_disabled()
        expect(page.get_by_role("button", name=REDO)).to_be_disabled()
        expect(page.locator("#toasts .toast")).to_have_count(0)


def test_a_column_the_data_lacks_is_left_out_with_a_warning(
    page: Page, app_page: Page, tmp_path: Path, scatter_path: Path, settings_store: SettingsStore
) -> None:
    """The settings' color column the data lacks is drawn without, and the toast names it."""
    content = saved_file(app_page)
    zones = content["settings"]["zones"]
    zones["encoding"]["color"] = "gone"
    zones["numeric"] = sorted([*zones["numeric"], ["gone", False]])
    zones["temporal"] = sorted([*zones["temporal"], ["gone", None]])
    content["columns"]["gone"] = "categorical"

    with opened_with(page, content, tmp_path, scatter_path, settings_store) as url:
        with page.expect_request("**/api/plot") as request:
            page.goto(url)
        assert request.value.post_data_json["encoding"]["color"] is None
        wait_idle(page)
        expect(page.locator('.zone[data-role="color"] .chip')).to_have_count(0)
        assert chip_names(page, "x") == ["x"]
        expect(page.locator("#toasts .toast")).to_contain_text(
            "描画設定のうち、データに無い列か種類の違う列を外しました：gone"
        )
        expect(page.get_by_role("button", name=UNDO)).to_be_disabled()


def test_a_file_that_fails_to_plot_leaves_the_empty_graph_as_the_first_step(
    page: Page, app_page: Page, tmp_path: Path, scatter_path: Path, settings_store: SettingsStore
) -> None:
    """A failed first plot goes back to the empty graph with nothing to undo; the edits after it undo back to it."""
    content = saved_file(app_page)
    failed: list[str] = []

    def fail_first(route: Route) -> None:
        if failed:
            route.continue_()
        else:
            failed.append(route.request.url)
            route.fulfill(status=500, body="broken")

    page.route("**/api/plot", fail_first)
    with opened_with(page, content, tmp_path, scatter_path, settings_store) as url:
        page.goto(url)
        expect(page.locator("#status")).to_contain_text("broken")
        assert len(failed) == 1
        expect(page.locator('.zone[data-role="x"] .chip')).to_have_count(0)
        expect(page.locator('.zone[data-role="y"] .chip')).to_have_count(0)
        undo = page.get_by_role("button", name=UNDO)
        expect(undo).to_be_disabled()

        x_and_y(page)
        expect(undo).to_be_enabled()
        page.evaluate("document.activeElement?.blur()")
        # x alone (not drawable) was a step of its own, then x and y.
        page.keyboard.press("Control+z")
        expect(page.locator('.zone[data-role="y"] .chip')).to_have_count(0)
        page.keyboard.press("Control+z")
        expect(page.locator('.zone[data-role="x"] .chip')).to_have_count(0)
        expect(undo).to_be_disabled()


@pytest.mark.parametrize("desktop", [True])
def test_the_window_saves_the_file_from_its_menu(page: Page, app_page: Page) -> None:
    """`File` has 描画設定を保存… below `New`, disabled on the empty graph; once drawn it hands the file to the window."""
    page.add_init_script(GEOMETRY)
    page.add_init_script(FAKE_API)
    page.add_init_script(FAKE_SAVE)
    page.reload()
    expect(page.locator("#columns .column").first).to_be_visible()
    # A browser's item is the menu's in the window.
    expect(open_menu(page).get_by_role("menuitem", name=SAVE_FILE)).to_have_count(0)
    page.keyboard.press("Escape")
    open_item(page, "File")
    assert popups(page) == [["File", "Edit", "Help"], ["New", SAVE_FILE, "Quit"]]
    expect(page.locator(".titlebar-popup .titlebar-item").filter(has_text=SAVE_FILE)).to_be_disabled()
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")

    x_and_y(page)
    open_item(page, "File", SAVE_FILE)
    page.wait_for_function("window.savedDrawFiles.length === 1")
    content = json.loads(page.evaluate("window.savedDrawFiles[0]"))
    assert content["settings"]["zones"]["encoding"]["x"] == ["x"]
    assert content["source"]["paths"][0].endswith(".parquet")
    expect(page.locator("#toasts .toast")).to_contain_text("描画設定を保存しました（scatter.ddviz.json）")
