"""E2E: `… → Edit → Preferences…` on the desktop's pages, and the opacity of the inactive series applied at once (Issue #224).

As in test_app_menu.py, the server is started as the window starts it
(`desktop=True`) and an init script replaces pywebview's JS API: its
`settings` gives the dialog's state as `ddviz.server.preferences` builds it,
its `save_settings` records the changes and answers with the new values. The
chooser and the loading page are the HTML the desktop makes
(`ddviz.desktop.window`), served in Chrome. This checks the pages and their
contract with the window, not pywebview's calls into Python in WebView2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, expect

from ddviz.desktop.window import _CHOOSER, _CLOSING, _LOADING
from ddviz.server.preferences import Preferences
from ddviz.server.settings import Settings
from ddviz.server.settings_store import SettingsStore
from tests.e2e.test_app_menu import GEOMETRY, focused, open_item, popups
from tests.e2e.test_scatter import (
    AGGREGATING,
    PAINTED_PIXEL,
    SETTLED,
    apply_color_bins,
    box_select,
    place,
    wait_idle,
)

pytestmark = pytest.mark.e2e

OPACITY = "plot.legend.inactive_opacity"
STATE = Preferences(SettingsStore(Settings())).state()
FAKE_API = f"""
window.desktopCalls = [];
let state = {json.dumps(STATE)};
window.pywebview = {{ api: {{
  new: async () => {{ window.desktopCalls.push(["new"]); }},
  quit: async () => {{ window.desktopCalls.push(["quit"]); }},
  version: async () => "9.9.9",
  settings: async () => {{
    window.desktopCalls.push(["settings"]);
    return structuredClone(state);
  }},
  save_settings: async (changes) => {{
    window.desktopCalls.push(["save_settings", changes]);
    state.values = {{ ...state.values, ...changes }};
    return {{ values: state.values }};
  }},
}} }};
"""
# The sum of the alpha of the image layers' pixels: how much the series paint.
PAINTED_ALPHA = """() => {
  const canvas = document.querySelector("canvas.image-layers");
  const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  let sum = 0;
  for (let i = 3; i < data.length; i += 4) sum += data[i];
  return sum;
}"""
FRAMES = "() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"


@pytest.fixture
def desktop() -> bool:
    """Serve the page as the desktop window does."""
    return True


@pytest.fixture
def menu_page(page: Page, app_page: Page) -> Page:
    """Return the graph's page with the window's API replaced, loaded again so that it applies."""
    page.add_init_script(GEOMETRY)
    page.add_init_script(FAKE_API)
    page.reload()
    expect(page.locator("#titlebar")).to_be_visible()
    expect(page.locator("#columns .column").first).to_be_visible()
    return page


def calls(page: Page) -> list[list]:
    """Return the window's calls, in order."""
    return page.evaluate("window.desktopCalls")


def open_preferences(page: Page) -> None:
    """Open the dialog with the mouse."""
    open_item(page, "Edit", "Preferences…")
    expect(page.locator(".prefs-dialog")).to_be_visible()


def set_opacity(page: Page, percent: str) -> None:
    """Apply the opacity of the inactive series in the dialog, and wait for the redraw."""
    open_preferences(page)
    page.locator(f'.prefs-item[data-key="{OPACITY}"] .prefs-text').fill(percent)
    page.get_by_role("button", name="適用").click()
    expect(page.locator(".prefs-dialog")).to_have_count(0)
    page.evaluate(FRAMES)


def test_preferences_open_from_the_menu_with_the_mouse(menu_page: Page) -> None:
    """Edit holds Preferences…, which opens the dialog with the values in effect; Escape closes it, saves nothing and gives the focus back to `…`."""
    page = menu_page
    open_item(page, "Edit")
    assert popups(page) == [["File", "Edit", "Help"], ["Preferences…"]]
    page.locator(".titlebar-popup .titlebar-item").filter(has_text="Preferences").click()
    dialog = page.locator(".prefs-dialog")
    expect(dialog.locator(".prefs-title")).to_have_text("設定")
    expect(dialog.locator(".prefs-item")).to_have_count(9)
    expect(dialog.locator(".prefs-timing").first).to_have_text("適用後すぐに反映")
    assert page.evaluate("document.activeElement.classList.contains('prefs-slider')")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    assert focused(page) == "…"
    assert calls(page) == [["settings"]]


def test_preferences_open_and_apply_with_the_keyboard(menu_page: Page) -> None:
    """Tab, Enter and the arrows open Preferences…; Enter in an input applies and the focus goes back to `…`."""
    page = menu_page
    keys = page.keyboard
    page.locator("body").focus()
    keys.press("Tab")
    keys.press("Enter")
    assert focused(page) == "File"
    keys.press("ArrowDown")
    assert focused(page) == "Edit"
    keys.press("ArrowRight")
    assert focused(page) == "Preferences…"
    keys.press("Enter")
    expect(page.locator(".prefs-dialog")).to_be_visible()
    for _ in range(6):
        keys.press("Tab")
    assert page.evaluate("document.activeElement.closest('.prefs-item').dataset.key") == (
        "columns.max_history"
    )
    keys.press("Control+A")
    keys.type("7")
    keys.press("Enter")
    expect(page.locator(".prefs-dialog")).to_have_count(0)
    assert focused(page) == "…"
    assert calls(page) == [["settings"], ["save_settings", {"columns.max_history": 7}]]


def test_the_column_list_searches_again_as_it_is(menu_page: Page) -> None:
    """A saved `columns.max_listed` searches the list again with the keyword and kind shown."""
    page = menu_page
    page.locator(".column-search").fill("x")
    page.locator('.column-kinds [data-kind="numeric"]').click()
    expect(page.locator("#columns .column")).to_have_count(1)
    open_preferences(page)
    page.locator('.prefs-item[data-key="columns.max_listed"] .prefs-text').fill("3")
    with page.expect_request("**/api/columns?*") as asked:
        page.get_by_role("button", name="適用").click()
    assert "q=x" in asked.value.url
    assert "kind=numeric" in asked.value.url
    expect(page.locator(".prefs-dialog")).to_have_count(0)


# Holds the body of the next `/api/columns` answer, read once its fetch is
# done, until `window.releaseBody()`, which gives it without its columns:
# an older list told apart from the one searched after it.
HOLD_COLUMNS_BODY = """
const realFetch = window.fetch;
window.holdColumnsBody = false;
window.releaseBody = null;
window.fetch = async (url, options) => {
  const response = await realFetch(url, options);
  if (String(url).startsWith("/api/columns") && window.holdColumnsBody) {
    window.holdColumnsBody = false;
    const json = response.json.bind(response);
    response.json = () => new Promise((done) => { window.releaseBody = () => json().then((found) => done({ ...found, matched: 0, columns: [] })); });
  }
  return response;
};
"""


def test_an_older_column_list_read_late_does_not_cover_the_new_one(menu_page: Page) -> None:
    """A search whose body is read after the list was searched again for `columns.max_listed` is dropped (the fake window saves nothing on the server: the new list is the same)."""
    page = menu_page
    page.add_init_script(HOLD_COLUMNS_BODY)
    page.reload()
    numeric = page.locator('.column-kinds [data-kind="numeric"]')
    expect(page.locator("#columns .column").first).to_be_visible()
    numeric.click()
    wait_idle(page)
    shown = page.locator("#columns .column").count()
    assert shown > 0
    page.locator('.column-kinds [data-kind=""]').click()
    page.evaluate("window.holdColumnsBody = true")
    numeric.click()
    page.wait_for_function("window.releaseBody !== null")
    open_preferences(page)
    page.locator('.prefs-item[data-key="columns.max_listed"] .prefs-text').fill("1")
    page.get_by_role("button", name="適用").click()
    expect(page.locator(".prefs-dialog")).to_have_count(0)
    expect(page.locator("#columns .column")).to_have_count(shown)
    page.evaluate("window.releaseBody()")
    page.evaluate(FRAMES)
    expect(page.locator("#columns .column")).to_have_count(shown)


def test_the_settings_of_the_start_do_not_undo_the_applied_ones(menu_page: Page) -> None:
    """The page's first `/api/settings`, answered after an apply, does not take the applied value back."""
    page = menu_page
    held = []
    page.route("**/api/settings", lambda route: held.append(route))
    page.reload()
    expect(page.locator("#columns .column").first).to_be_visible()
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert len(held) == 1
    open_preferences(page)
    page.locator('.prefs-item[data-key="plot.max_levels"] .prefs-text').fill("4")
    page.get_by_role("button", name="適用").click()
    expect(page.locator(".prefs-dialog")).to_have_count(0)
    held[0].continue_()
    page.unroute("**/api/settings")
    page.evaluate(FRAMES)
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "x", "color")
    bar = page.locator("#legend .colorbar")
    expect(bar).to_be_visible()
    bar.click(button="right")
    menu = page.locator(".scale-menu")
    menu.get_by_label("区間数").fill("5")
    menu.get_by_role("button", name="適用").click()
    expect(menu.locator(".scale-menu-count-error")).to_have_text("2 以上 4 以下の整数を入力してください")
    page.keyboard.press("Escape")


def test_the_limit_of_the_color_bins_follows_at_once(menu_page: Page) -> None:
    """A saved `plot.max_levels` is the limit of the next number of intervals entered; the intervals shown stay."""
    page = menu_page
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "x", "color")
    bar = page.locator("#legend .colorbar")
    expect(bar).to_be_visible()
    apply_color_bins(page, bar, "6")
    page.wait_for_function(SETTLED)
    expect(page.locator("#legend .legend-item")).to_have_count(6 + 1)
    open_preferences(page)
    expect(page.locator('.prefs-item[data-key="plot.max_levels"] .prefs-timing')).to_have_text(
        "次のグラフ作成・フィルタの変更から反映。Colorの区間数の入力上限は適用後すぐ"
    )
    page.locator('.prefs-item[data-key="plot.max_levels"] .prefs-text').fill("4")
    plots = []
    page.on("request", lambda r: r.url.endswith("/api/plot") and plots.append(r.url))
    page.get_by_role("button", name="適用").click()
    expect(page.locator(".prefs-dialog")).to_have_count(0)
    page.evaluate(FRAMES)
    assert plots == []
    expect(page.locator("#legend .legend-item")).to_have_count(6 + 1)
    page.locator("#legend .legend-title").click(button="right")
    menu = page.locator(".scale-menu")
    menu.get_by_label("区間数").fill("5")
    menu.get_by_role("button", name="適用").click()
    expect(menu.locator(".scale-menu-count-error")).to_have_text("2 以上 4 以下の整数を入力してください")
    page.keyboard.press("Escape")


@pytest.mark.parametrize("drawn", ["points-smooth-lines", "boxes"])
def test_the_opacity_of_inactive_series_redraws_at_once(menu_page: Page, drawn: str) -> None:
    """0, 15 and 100 % redraw the inactive series (points, smoothing lines and lines, or box plots) without aggregating again; the active series and the legend's items stay; 0 is not hovered and 15 is again; Cancel changes nothing."""
    page = menu_page
    if drawn == "boxes":
        place(page, "color", "x")
        place(page, "y", "y")
        place(page, "facet", "color")
        page.locator('#elements .element[data-element="box"]').click()
    else:
        place(page, "x", "x")
        place(page, "y", "y")
        place(page, "facet", "color")
        page.locator('#elements .element[data-element="smooth"]').click()
        page.locator('#elements .element[data-element="line"]').click()
    pixel = page.wait_for_function(PAINTED_PIXEL).json_value()
    wait_idle(page)
    everything = page.evaluate(PAINTED_ALPHA)
    aggregated: list[str] = []
    page.on("request", lambda r: r.url.endswith(AGGREGATING) and aggregated.append(r.url))

    items = page.locator("#legend .legend-item")
    for i in range(items.count()):
        items.nth(i).click()
    page.evaluate(FRAMES)
    default = page.evaluate(PAINTED_ALPHA)
    set_opacity(page, "0")
    hidden = page.evaluate(PAINTED_ALPHA)
    set_opacity(page, "100")
    full = page.evaluate(PAINTED_ALPHA)
    set_opacity(page, "15")
    again = page.evaluate(PAINTED_ALPHA)
    assert hidden < default < full
    if drawn != "boxes":
        assert hidden == 0
    # At 100 % the inactive series paint as the active ones (within the
    # rounding of the canvas's blending).
    assert abs(full - everything) <= everything / 1000
    assert again == default
    expect(items.first).to_have_css("opacity", "0.35")

    # An active series still paints at 0 %, and as before back at 15 %.
    items.first.click()
    page.evaluate(FRAMES)
    one_active = page.evaluate(PAINTED_ALPHA)
    set_opacity(page, "0")
    assert 0 < page.evaluate(PAINTED_ALPHA) < one_active
    set_opacity(page, "15")
    assert page.evaluate(PAINTED_ALPHA) == one_active
    items.first.click()

    # Cancel leaves the drawing and saves nothing.
    open_preferences(page)
    page.locator(f'.prefs-item[data-key="{OPACITY}"] .prefs-text').fill("60")
    page.get_by_role("button", name="キャンセル").click()
    page.evaluate(FRAMES)
    assert page.evaluate(PAINTED_ALPHA) == default
    assert [c for c in calls(page) if c[0] == "save_settings"] == [
        ["save_settings", {OPACITY: 0}],
        ["save_settings", {OPACITY: 1}],
        ["save_settings", {OPACITY: 0.15}],
        ["save_settings", {OPACITY: 0}],
        ["save_settings", {OPACITY: 0.15}],
    ]
    page.wait_for_timeout(600)
    assert aggregated == []

    if drawn == "boxes":
        return
    # At 0 the inactive series are not hovered; at 15 % they are again.
    set_opacity(page, "0")
    with page.expect_response(lambda r: "/api/hover" in r.url) as hover:
        page.mouse.move(pixel["x"], pixel["y"])
    assert hover.value.json()["hit"] is None
    expect(page.locator("#hover-label")).to_be_hidden()
    page.mouse.move(0, 0)
    set_opacity(page, "15")
    page.mouse.move(pixel["x"], pixel["y"])
    expect(page.locator("#hover-label")).to_be_visible()


def test_the_opacity_keeps_the_selection(menu_page: Page) -> None:
    """A selection stays through a change of the opacity, and is not asked again."""
    page = menu_page
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "facet", "color")
    page.wait_for_function(PAINTED_PIXEL)
    asked = box_select(page)
    paths = page.locator("#plot .selectionlayer path")
    expect(paths.first).to_be_attached()
    shapes = paths.evaluate_all("(ps) => ps.map((p) => p.getAttribute('d'))")
    page.locator("#legend .legend-item").first.click()
    set_opacity(page, "50")
    assert paths.evaluate_all("(ps) => ps.map((p) => p.getAttribute('d'))") == shapes
    page.wait_for_timeout(300)
    assert asked == []


def _serve_page(page: Page, html: str) -> Page:
    """Open the desktop's own `html` at a URL of its own, with the window stood in for."""

    def fulfill(route: Route) -> None:
        route.fulfill(body=html, content_type="text/html")

    page.route("http://desktop.test/**", fulfill)
    page.add_init_script(GEOMETRY)
    page.add_init_script(FAKE_API)
    page.goto("http://desktop.test/")
    expect(page.locator("#titlebar")).to_be_visible()
    return page


def test_preferences_open_on_the_chooser(page: Page) -> None:
    """On the chooser the dialog opens, saves through the window and closes."""
    _serve_page(page, _CHOOSER)
    open_preferences(page)
    page.locator('.prefs-item[data-key="cache.max_gb"] .prefs-text').fill("2.5")
    page.get_by_role("button", name="適用").click()
    expect(page.locator(".prefs-dialog")).to_have_count(0)
    assert calls(page) == [["settings"], ["save_settings", {"cache.max_gb": 2.5}]]
    assert focused(page) == "…"


@pytest.mark.parametrize("html", [_LOADING, _CLOSING], ids=["starting", "closing"])
def test_preferences_are_disabled_while_starting_or_closing(page: Page, html: str) -> None:
    """While starting and while `New` closes the data, Preferences… is disabled."""
    _serve_page(page, html)
    open_item(page, "Edit")
    expect(page.locator(".titlebar-popup .titlebar-item").filter(has_text="Preferences")).to_be_disabled()


@pytest.mark.parametrize("desktop", [False])
def test_a_browser_page_has_no_preferences(app_page: Page, tmp_path: Path) -> None:
    """The page for a browser (`--port`) has no title bar, so no way to the dialog."""
    expect(app_page.locator("#columns .column").first).to_be_visible()
    expect(app_page.locator("#titlebar")).to_have_count(0)
    expect(app_page.locator(".prefs-dialog")).to_have_count(0)
