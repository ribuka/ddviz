"""E2E: the saves of the plot's data show their progress and end in a toast, with a cancel button, the file's actions and a history (Issue #194).

The page's side only: the export is held or answered by routes where its
timing matters; the server's cancel and its 409 of the table's pages are
tested in ``tests/server/test_app.py``. The window's transfer is played by
calling ``window.ddvizSaveProgress`` and ``window.ddvizSaved`` as
``ddviz.desktop.downloads`` does; WebView2 itself is not in these tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Locator, Page, Route, expect

from tests.e2e.test_scatter import box_select, place

pytestmark = pytest.mark.e2e

# The export of a plot's data (`POST /api/plot-data/{task}`), not its cancel.
PLOT_DATA = re.compile(r"/api/plot-data/\d+$")


def open_menu(page: Page) -> Locator:
    """Open the save menu of the mode bar and return it.

    The toasts lie over the mode bar at the top right, a save's for as long
    as it runs: the click is dispatched to the button (`test_scatter.py`
    clicks it).
    """
    page.locator('#plot .modebar-btn[data-title^="データを保存"]').dispatch_event("click")
    menu = page.locator(".data-menu")
    expect(menu).to_be_visible()
    return menu


def draw(page: Page) -> None:
    """Draw y over x."""
    place(page, "x", "x")
    place(page, "y", "y")


def hold(page: Page) -> list[Route]:
    """Hold the exports: their routes are returned to be answered by the test."""
    held: list[Route] = []
    page.route(PLOT_DATA, lambda route: held.append(route))
    return held


def held_one(page: Page, held: list[Route]) -> Route:
    """Wait until an export is held and return it."""
    for _ in range(100):
        if held:
            return held.pop(0)
        page.wait_for_timeout(50)
    raise AssertionError("no export was held")


def test_a_save_shows_its_progress_and_is_cancelled_from_its_toast(app_page: Page) -> None:
    """A format closes the menu and shows the save's toast instead of a cover; the graph can be used and no other save starts meanwhile; its cancel sends the export's token and ends the toast."""
    page = app_page
    draw(page)
    held = hold(page)
    menu = open_menu(page)
    with page.expect_request(PLOT_DATA) as started:
        menu.get_by_role("button", name="CSV").click()
    expect(menu).to_have_count(0)
    expect(page.locator("#exporting")).to_have_count(0)
    toast = page.locator("#toasts .toast-save")
    expect(toast).to_have_count(1)
    expect(toast).to_have_attribute("role", "status")
    expect(toast.locator(".save-name")).to_have_text("CSV を書き出しています")
    expect(toast.locator(".save-status")).to_have_text("書き出す行を数えています…")
    assert toast.locator("progress").get_attribute("value") is None
    token = started.value.post_data_json["export"]
    route = held_one(page, held)

    # The graph pans meanwhile.
    stage = page.locator("#stage").bounding_box()
    x, y = stage["x"] + stage["width"] / 3, stage["y"] + stage["height"] / 2
    with page.expect_request("**/api/view"):
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 60, y + 20, steps=5)
        page.mouse.up()

    # No other save while one is written.
    menu = open_menu(page)
    expect(menu.get_by_role("button", name="CSV")).to_be_disabled()
    expect(menu.get_by_role("button", name="Parquet")).to_be_disabled()
    expect(menu.locator(".data-menu-note")).to_have_text("書き出しが終わると保存できます")
    page.keyboard.press("Escape")

    with page.expect_request("**/api/plot-data/cancel") as cancelled:
        toast.get_by_role("button", name="中止").click()
    assert cancelled.value.post_data_json == {"export": token}
    expect(toast.locator(".save-status")).to_have_text("中止しています…")
    expect(toast.get_by_role("button", name="中止")).to_be_disabled()
    route.fulfill(status=409, content_type="application/json", body='{"cancelled": true}')
    expect(toast.locator(".save-status")).to_have_text("保存を中止しました")
    expect(toast.locator("progress")).to_be_hidden()
    expect(toast).to_have_class(re.compile(r"\btoast-success\b"))
    page.unroute(PLOT_DATA)
    # Saves start again.
    expect(open_menu(page).get_by_role("button", name="CSV")).to_be_enabled()


def test_a_save_ends_in_its_toast(app_page: Page) -> None:
    """In a browser a save ends as its download starts; a failure turns its toast into an error; a toast closed while its save runs leaves the save going, which ends in a new toast."""
    page = app_page
    draw(page)
    with page.expect_download() as info:
        open_menu(page).get_by_role("button", name="CSV").click()
    name = info.value.suggested_filename
    started = page.locator("#toasts .toast-save").filter(has_text=f"ダウンロードを開始しました（{name}）")
    expect(started).to_have_count(1)
    expect(started.locator(".save-open")).to_be_hidden()
    expect(started.locator(".save-reveal")).to_be_hidden()

    page.route(
        PLOT_DATA,
        lambda route: route.fulfill(
            status=500, content_type="application/json", body='{"detail": "壊れた"}'
        ),
    )
    open_menu(page).get_by_role("button", name="CSV").click()
    failed = page.locator("#toasts .toast-save").filter(has_text="保存できませんでした：壊れた")
    expect(failed).to_have_count(1)
    expect(failed).to_have_class(re.compile(r"\bnotice-error\b"))
    expect(failed).to_have_attribute("role", "alert")
    page.unroute(PLOT_DATA)

    held = hold(page)
    open_menu(page).get_by_role("button", name="Parquet").click()
    running = page.locator("#toasts .toast-save").filter(has_text="Parquet を書き出しています")
    expect(running).to_have_count(1)
    running.get_by_role("button", name="閉じる").click()
    expect(running).to_have_count(0)
    route = held_one(page, held)
    with page.expect_download() as info:
        route.continue_()
    name = info.value.suggested_filename
    expect(
        page.locator("#toasts .toast-save").filter(has_text=f"ダウンロードを開始しました（{name}）")
    ).to_have_count(1)
    page.unroute(PLOT_DATA)


def test_the_table_waits_for_an_export(app_page: Page) -> None:
    """A page of the table refused while the plot's data is written (409 ``exporting``) says so, and is fetched once the export ends."""
    page = app_page
    draw(page)
    exporting = [True]

    def table(route: Route) -> None:
        if exporting[0]:
            route.fulfill(status=409, content_type="application/json", body='{"detail": "exporting"}')
        else:
            route.continue_()

    page.route("**/api/table*", table)
    box_select(page)
    wait = page.locator("#table .table-wait")
    page.locator("#table .table-up").click()
    expect(wait).to_be_visible()
    expect(wait).to_have_text(
        "データを書き出している間は表を表示できません。書き出しが終わると表示します。"
    )

    held = hold(page)
    open_menu(page).get_by_role("button", name="CSV").click()
    route = held_one(page, held)
    exporting[0] = False
    with page.expect_download(), page.expect_request("**/api/table*"):
        route.continue_()
    expect(wait).to_be_hidden()
    expect(page.locator("#table .table-grid .tc.num").first).to_be_visible()
    page.unroute(PLOT_DATA)


def test_a_table_page_refused_after_the_export_ended_is_fetched_again(app_page: Page) -> None:
    """A 409 ``exporting`` that comes once the page's export has ended (its end told already) is fetched again by itself."""
    page = app_page
    draw(page)
    refused: list[str] = []

    def table(route: Route) -> None:
        if not refused:
            refused.append(route.request.url)
            route.fulfill(status=409, content_type="application/json", body='{"detail": "exporting"}')
        else:
            route.continue_()

    page.route("**/api/table*", table)
    # A Box Select drag; the table stays open (`box_select` folds it).
    page.evaluate("Plotly.relayout('plot', {dragmode: 'select'})")
    stage = page.locator("#stage").bounding_box()
    x, y = stage["x"] + stage["width"] / 2, stage["y"] + stage["height"] / 2
    page.mouse.move(x - 30, y - 30)
    page.mouse.down()
    page.mouse.move(x + 30, y + 30, steps=5)
    page.mouse.up()
    wait = page.locator("#table .table-wait")
    expect(wait).to_be_visible()
    expect(page.locator("#table .table-grid .tc.num").first).to_be_visible()
    expect(wait).to_be_hidden()
    assert len(refused) == 1


def test_the_history_in_a_browser(app_page: Page) -> None:
    """The save menu's last item opens the history once a save started: the browser's downloads, newest first; Esc and a click outside close it."""
    page = app_page
    draw(page)
    menu = open_menu(page)
    expect(menu.get_by_role("button", name="保存の履歴…")).to_be_disabled()
    page.keyboard.press("Escape")
    names = []
    for format in ("CSV", "Parquet"):
        with page.expect_download() as info:
            open_menu(page).get_by_role("button", name=format).click()
        names.append(info.value.suggested_filename)

    open_menu(page).get_by_role("button", name="保存の履歴…").click()
    expect(page.locator(".data-menu")).to_have_count(0)
    panel = page.get_by_role("dialog", name="保存の履歴")
    expect(panel).to_be_visible()
    rows = panel.locator(".save-row")
    expect(rows.locator(".save-name")).to_have_text(names[::-1])
    for status in rows.locator(".save-status").all_text_contents():
        assert re.fullmatch(r"ブラウザーのダウンロード · \d\d:\d\d", status)
    expect(rows.locator(".save-open")).to_have_count(2)
    expect(rows.locator(".save-open").first).to_be_hidden()
    page.keyboard.press("Escape")
    expect(panel).to_have_count(0)

    open_menu(page).get_by_role("button", name="保存の履歴…").click()
    expect(panel).to_be_visible()
    page.locator("#columns").click()
    expect(panel).to_have_count(0)


def save_in_window(page: Page, format: str) -> str:
    """Save as the window's page does, up to the start of the transfer, and return the file's id."""
    with page.expect_response(PLOT_DATA) as response, page.expect_download():
        open_menu(page).get_by_role("button", name=format).click()
    return response.value.json()["file"]


@pytest.mark.parametrize("desktop", [True])
def test_the_windows_saves(app_page: Page) -> None:
    """In the window: the title bar's button shows from the first save, 8px left of the OS buttons; the transfer's progress fills the bar past 90%; a saved file opens and shows in its folder; a file gone says so; the history lists every end."""
    page = app_page
    draw(page)
    button = page.locator("#titlebar .titlebar-saves")
    expect(button).to_be_hidden()
    acted: list[str] = []

    def act(route: Route) -> None:
        acted.append(route.request.url.split("/api/saves/")[1])
        route.fulfill(status=204)

    page.route("**/api/saves/**", act)
    file = save_in_window(page, "CSV")
    expect(button).to_be_visible()
    gap = page.evaluate(
        """() => {
          const bar = document.getElementById("titlebar");
          const right = bar.getBoundingClientRect().right - parseFloat(getComputedStyle(bar).paddingRight);
          return right - document.querySelector("#titlebar .titlebar-saves").getBoundingClientRect().right;
        }"""
    )
    assert gap == pytest.approx(8, abs=0.5)

    toast = page.locator("#toasts .toast-save").first
    expect(toast.locator(".save-status")).to_have_text("保存しています…")
    page.evaluate(
        "(file) => window.ddvizSaveProgress({file, received: 500000, total: 1400000})", file
    )
    expect(toast.locator(".save-status")).to_have_text("保存しています（0.5 / 1.4 MB）")
    value = float(toast.locator("progress").get_attribute("value"))
    assert 90 < value < 100
    expect(button).to_have_attribute("data-percent", str(round(value)))
    ring = button.locator(".saves-ring")
    expect(ring).to_be_visible()
    dash = ring.locator(".saves-ring-value").evaluate(
        "e => parseFloat(getComputedStyle(e).strokeDasharray)"
    )
    assert dash == pytest.approx(value, abs=0.01)

    with page.expect_request("**/api/saves/*/cancel"):
        toast.get_by_role("button", name="中止").click()
    page.evaluate("(file) => window.ddvizSaved({file, saved: 'a.csv', size: 1234})", file)
    expect(toast.locator(".save-status")).to_have_text("ダウンロードに保存しました（a.csv）")
    expect(toast.locator("progress")).to_be_hidden()
    with page.expect_request("**/api/saves/*/open"):
        toast.get_by_role("button", name="ファイルを開く").click()
    with page.expect_request("**/api/saves/*/reveal"):
        toast.get_by_role("button", name="フォルダーに表示").click()
    assert acted == [f"{file}/cancel", f"{file}/open", f"{file}/reveal"]

    page.unroute("**/api/saves/**")
    page.route(
        "**/api/saves/**",
        lambda route: route.fulfill(
            status=404, content_type="application/json", body='{"detail": "missing"}'
        ),
    )
    toast.get_by_role("button", name="ファイルを開く").click()
    expect(
        page.locator("#toasts .toast").filter(
            has_text="ファイルが見つかりません。移動または削除されました（a.csv）"
        )
    ).to_have_count(1)
    expect(toast.locator(".save-open")).to_be_hidden()

    second = save_in_window(page, "Parquet")
    page.evaluate("(file) => window.ddvizSaved({file, error: 'x'})", second)
    third = save_in_window(page, "CSV")
    page.evaluate("(file) => window.ddvizSaved({file, cancelled: true})", third)
    button.click()
    expect(button).to_have_attribute("aria-expanded", "true")
    panel = page.get_by_role("dialog", name="保存の履歴")
    expect(panel.locator(".save-row .save-status")).to_have_text(
        ["中止しました", "失敗：x", "移動または削除されました"]
    )
    button.click()
    expect(panel).to_have_count(0)


# The export of the selected rows (`POST /api/plot-data/selection`).
SELECTION_DATA = "**/api/plot-data/selection"


def open_table_menu(page: Page) -> Locator:
    """Open the save menu of the selection table's bar and return it."""
    page.locator("#table .table-save").click()
    menu = page.locator(".data-menu")
    expect(menu).to_be_visible()
    return menu


def test_the_tables_save_button_saves_the_selected_rows(
    app_page: Page, scatter_path: Path
) -> None:
    """The table bar's save button, left of ▲, opens a menu of the columns and formats; a format downloads every selected row; the columns picked are the mode bar menu's too (Issue #328)."""
    page = app_page
    draw(page)
    box_select(page)
    save = page.locator("#table .table-save").bounding_box()
    up = page.locator("#table .table-up").bounding_box()
    assert save["x"] + save["width"] <= up["x"]
    assert abs((save["y"] + save["height"] / 2) - (up["y"] + up["height"] / 2)) <= 2
    title = page.locator("#table .table-title").text_content()
    rows = int(re.fullmatch(r"選んだ行：([\d,]+) 行", title)[1].replace(",", ""))
    assert rows > 0

    menu = open_table_menu(page)
    expect(menu.locator(".scale-menu-heading, .scale-menu-item")).to_have_text(
        ["選んだ行を保存", "Columns", "Drawn columns", "All columns", "CSV", "Parquet"]
    )
    for absent in ("Drawn rows", "All filtered rows", "保存の履歴…"):
        expect(menu.get_by_role("button", name=absent)).to_have_count(0)
    menu.get_by_role("radio", name="All columns").click()
    expect(menu.get_by_role("radio", name="All columns")).to_have_attribute("aria-checked", "true")
    with page.expect_download() as info:
        menu.get_by_role("button", name="CSV").click()
    expect(menu).to_have_count(0)
    name = info.value.suggested_filename
    assert re.search(r"_selected_\d{8}-\d{6}\.csv$", name)
    saved = pl.read_csv(info.value.path())
    assert saved.height == rows
    assert saved.columns == ["index", *pl.read_parquet_schema(scatter_path)]
    assert saved["index"].is_sorted() and saved["index"].n_unique() == rows
    expect(
        page.locator("#toasts .toast-save").filter(has_text=f"ダウンロードを開始しました（{name}）")
    ).to_have_count(1)

    # The columns picked are shared with the mode bar's menu, both ways.
    menu = open_menu(page)
    expect(menu.get_by_role("radio", name="All columns")).to_have_attribute("aria-checked", "true")
    menu.get_by_role("radio", name="Drawn columns").click()
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    menu = open_table_menu(page)
    expect(menu.get_by_role("radio", name="Drawn columns")).to_have_attribute(
        "aria-checked", "true"
    )


def test_the_tables_save_waits_for_an_export_and_says_a_lost_selection(
    app_page: Page,
) -> None:
    """While the mode bar's save is written, the table's menu disables its formats and says why, its radios still picked; a selection gone by the time it is asked for ends in an error toast."""
    page = app_page
    draw(page)
    box_select(page)
    held = hold(page)
    open_menu(page).get_by_role("button", name="CSV").click()
    route = held_one(page, held)
    menu = open_table_menu(page)
    expect(menu.get_by_role("button", name="CSV")).to_be_disabled()
    expect(menu.get_by_role("button", name="Parquet")).to_be_disabled()
    expect(menu.locator(".data-menu-note")).to_have_text("書き出しが終わると保存できます")
    menu.get_by_role("radio", name="All columns").click()
    expect(menu.get_by_role("radio", name="All columns")).to_have_attribute("aria-checked", "true")
    page.keyboard.press("Escape")
    with page.expect_download():
        route.continue_()
    page.unroute(PLOT_DATA)
    expect(open_table_menu(page).get_by_role("button", name="CSV")).to_be_enabled()

    page.route(
        SELECTION_DATA,
        lambda route: route.fulfill(
            status=409, content_type="application/json", body='{"detail": "no selection"}'
        ),
    )
    page.locator(".data-menu").get_by_role("button", name="CSV").click()
    lost = page.locator("#toasts .toast-save").filter(
        has_text="保存できませんでした：範囲選択が解除されました"
    )
    expect(lost).to_have_count(1)
    expect(lost).to_have_class(re.compile(r"\bnotice-error\b"))
    page.unroute(SELECTION_DATA)
