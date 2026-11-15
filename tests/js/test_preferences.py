"""JS: preferences.js, the Preferences dialog: its items, the checks of the inputs, and applying or dropping the edits."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from ddviz.server.preferences import ITEMS, Preferences
from ddviz.server.settings_store import SettingsStore
from tests.js.conftest import open_blank
from tests.js.test_keys import press_conversion_enters, press_plain_enter

pytestmark = pytest.mark.js

OPACITY = "plot.legend.inactive_opacity"

# Opens the dialog with `state`; `save` answers each call with the next of
# `window.saveAnswers` (default: the values with the changes) after
# `window.saveDelay` ms, and `apply` fails while `window.applyFails` holds a
# message. Records the calls in `window.calls`.
OPEN = """(state) => {
  window.calls = [];
  window.saveAnswers = [];
  window.saveDelay = 0;
  window.applyFails = null;
  window.prefsClosed = false;
  const save = async (changes) => {
    window.calls.push(["save", changes]);
    await new Promise((r) => setTimeout(r, window.saveDelay));
    const answer = window.saveAnswers.shift();
    if (answer) return answer;
    state.values = { ...state.values, ...changes };
    return { values: state.values };
  };
  const apply = async (values, changed) => {
    window.calls.push(["apply", changed, values]);
    if (window.applyFails) throw new Error(window.applyFails);
  };
  window.ddvizPreferences.open({ state, save, apply }).then(() => { window.prefsClosed = true; });
}"""


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    """Return a blank page of its own with the dialog's script and style."""
    page = open_blank(browser.new_page())
    page.add_style_tag(url="/static/preferences.css")
    page.add_script_tag(url="/static/js/preferences.js")
    yield page
    page.close()


def _state(tmp_path: Path, values: dict | None = None) -> dict:
    """Return the dialog's state as the window gives it, with `values` over the defaults."""
    path = tmp_path / "settings.toml"
    path.write_text("", encoding="utf-8")
    state = Preferences(SettingsStore.load(path)).state()
    state["values"].update(values or {})
    return state


def _open(page: Page, tmp_path: Path, values: dict | None = None) -> dict:
    """Open the dialog; return its state."""
    state = _state(tmp_path, values)
    page.evaluate(OPEN, state)
    expect(page.locator(".prefs-dialog")).to_be_visible()
    return state


def _text(page: Page, key: str):  # noqa: ANN202 - a Locator
    """Return the text input of an item."""
    return page.locator(f'.prefs-item[data-key="{key}"] .prefs-text')


def _calls(page: Page) -> list:
    """Return the calls of save and apply."""
    return page.evaluate("window.calls")


def test_the_dialog_shows_every_item_in_its_group_with_its_timing(
    page: Page, tmp_path: Path
) -> None:
    """The title, the four groups in order, the nine items with their labels, units, timings and notes, and the values in effect."""
    _open(page, tmp_path)
    dialog = page.locator(".prefs-dialog")
    expect(dialog.locator(".prefs-title")).to_have_text("設定")
    expect(dialog.locator(".prefs-group-title")).to_have_text(
        ["グラフ表示", "列リスト", "キャッシュ", "ホバー"]
    )
    rows = dialog.locator(".prefs-item")
    expect(rows).to_have_count(9)
    expect(rows.locator(".prefs-label")).to_have_text([i.label for i in ITEMS])
    expect(rows.locator(".prefs-timing")).to_have_text([i.timing for i in ITEMS])
    assert rows.locator(".prefs-text").evaluate_all("(es) => es.map((e) => e.value)") == [
        "15", "100", "1000000", "300", "1000", "20", "10", "30", "2"
    ]
    expect(dialog.locator(".prefs-unit")).to_have_text(["%", "DPI", "GB", "日", "GB"])
    expect(dialog.locator(".prefs-note").first).to_have_text("0% で非表示、100% で通常と同じ濃さ")
    groups = dialog.locator(".prefs-group")
    expect(groups.nth(0).locator(".prefs-item")).to_have_count(4)
    expect(groups.nth(1).locator(".prefs-item")).to_have_count(2)
    expect(groups.nth(2).locator(".prefs-item")).to_have_count(2)
    expect(groups.nth(3).locator(".prefs-item")).to_have_count(1)
    expect(dialog.get_by_role("button")).to_have_text(["適用", "キャンセル"])


def test_the_slider_and_the_number_follow_each_other(page: Page, tmp_path: Path) -> None:
    """Moving the slider writes the percentage; a whole percentage typed moves the slider; 15% is saved as 0.15."""
    _open(page, tmp_path)
    slider = page.locator(".prefs-slider")
    text = _text(page, OPACITY)
    expect(slider).to_have_value("15")
    slider.fill("40")
    expect(text).to_have_value("40")
    text.fill("7")
    expect(slider).to_have_value("7")
    text.fill("abc")
    expect(slider).to_have_value("7")
    text.fill("15")
    text.fill("23")
    page.get_by_role("button", name="適用").click()
    page.wait_for_function("window.prefsClosed")
    assert _calls(page)[0] == ["save", {OPACITY: 0.23}]


def test_a_fraction_of_a_percent_is_shown_and_kept_unless_changed(
    page: Page, tmp_path: Path
) -> None:
    """A value read with a fraction of a percent shows exactly and is not rounded or saved when untouched; changed, it takes whole percentages."""
    _open(page, tmp_path, {OPACITY: 0.123})
    text = _text(page, OPACITY)
    expect(text).to_have_value("12.3")
    page.get_by_role("button", name="適用").click()
    page.wait_for_function("window.prefsClosed")
    assert _calls(page) == []
    _open(page, tmp_path, {OPACITY: 0.07})
    expect(text).to_have_value("7")
    _open_again = page.locator(".prefs-dialog")
    expect(_open_again).to_have_count(1)
    page.keyboard.press("Escape")
    _open(page, tmp_path, {OPACITY: 0.123})
    text.fill("12.5")
    page.get_by_role("button", name="適用").click()
    expect(page.locator(".prefs-item.invalid .prefs-error")).to_have_text(
        "0 以上 100 以下の整数（%）を入力してください"
    )
    text.fill("12")
    page.get_by_role("button", name="適用").click()
    page.wait_for_function("window.prefsClosed")
    assert _calls(page)[0] == ["save", {OPACITY: 0.12}]


@pytest.mark.parametrize(
    ("key", "good", "wrong", "error"),
    [
        (
            OPACITY,
            {"0": 0, " 100 ": 1, "1": 0.01},
            ["", "-1", "101", "1.5", "NaN", "Infinity", "true", "1e1", "５"],
            "0 以上 100 以下の整数（%）を入力してください",
        ),
        (
            "plot.max_levels",
            {"1": 1, " 25 ": 25, "1000000000": 1_000_000_000},
            ["", "0", "-3", "2.5", "1e3", "NaN", "Infinity", "true", "9007199254740993"],
            "1 以上の整数を入力してください",
        ),
        (
            "plot.image_copy.dpi",
            {"96": 96, "300": 300},
            ["", "0", "72", "96.0", "1e2", "true"],
            "96 か 300 を選んでください",
        ),
        (
            "cache.max_gb",
            {"0": 0, "0.5": 0.5, " 12 ": 12, ".25": 0.25},
            ["", "-0.5", "NaN", "Infinity", "1e3", "true", "abc"],
            "0 以上の数値を入力してください",
        ),
        (
            "cache.max_unused_days",
            {"0": 0, "1.5": 1.5},
            ["", "-1", "inf"],
            "0 以上の数値を入力してください",
        ),
        (
            "hover.max_temp_gb",
            {"0.1": 0.1, "3": 3},
            ["", "0", "0.0", "-1", "NaN", "Infinity"],
            "0 より大きい数値を入力してください",
        ),
    ],
)
def test_the_inputs_are_checked_without_rounding(
    page: Page, key: str, good: dict, wrong: list[str], error: str
) -> None:
    """Each kind of input takes its range only, after trimming blanks; blanks, out of range, fractions of an integer, NaN, infinity and booleans get the item's error."""
    item = next(i for i in ITEMS if i.key == key)
    found = page.evaluate(
        """([item, texts]) => texts.map((t) => window.ddvizPreferences.parse(item, t))""",
        [
            {
                "input": item.input,
                "minimum": item.minimum,
                "above_minimum": item.above_minimum,
                "choices": list(item.choices),
            },
            [*good, *wrong],
        ],
    )
    assert found == [{"value": v} for v in good.values()] + [{"error": error}] * len(wrong)


def test_a_wrong_input_saves_nothing_and_takes_the_focus(
    page: Page, tmp_path: Path
) -> None:
    """Apply with wrong inputs shows each error beside its item, focuses the first one and saves nothing; fixed, it saves the changed items alone."""
    _open(page, tmp_path)
    _text(page, "columns.max_listed").fill("0")
    _text(page, "plot.max_levels").fill("2.5")
    _text(page, "hover.max_temp_gb").fill("1.5")
    page.get_by_role("button", name="適用").click()
    errors = page.locator(".prefs-item.invalid")
    expect(errors).to_have_count(2)
    expect(errors.locator(".prefs-error")).to_have_text(
        ["1 以上の整数を入力してください", "1 以上の整数を入力してください"]
    )
    assert page.evaluate("document.activeElement.closest('.prefs-item').dataset.key") == (
        "plot.max_levels"
    )
    assert _calls(page) == []
    _text(page, "plot.max_levels").fill("12")
    _text(page, "columns.max_listed").fill(" 1000 ")
    page.get_by_role("button", name="適用").click()
    page.wait_for_function("window.prefsClosed")
    assert _calls(page)[0] == ["save", {"plot.max_levels": 12, "hover.max_temp_gb": 1.5}]
    assert _calls(page)[1][:2] == ["apply", ["plot.max_levels", "hover.max_temp_gb"]]


def test_an_apply_without_changes_closes_and_saves_nothing(
    page: Page, tmp_path: Path
) -> None:
    """Apply with nothing changed, or values typed as they were, closes without saving or applying."""
    _open(page, tmp_path)
    _text(page, "cache.max_gb").fill("10.0")
    page.get_by_role("button", name="適用").click()
    page.wait_for_function("window.prefsClosed")
    assert _calls(page) == []


def test_enter_applies_and_the_enter_of_a_conversion_does_not(
    page: Page, tmp_path: Path
) -> None:
    """A plain Enter in an input applies; the Enters that commit an IME conversion do nothing."""
    _open(page, tmp_path)
    text = _text(page, "columns.max_history")
    text.fill("5")
    press_conversion_enters(text)
    page.wait_for_timeout(100)
    assert _calls(page) == []
    expect(page.locator(".prefs-dialog")).to_be_visible()
    press_plain_enter(text)
    page.wait_for_function("window.prefsClosed")
    assert _calls(page)[0] == ["save", {"columns.max_history": 5}]


@pytest.mark.parametrize("how", ["cancel", "escape", "outside"])
def test_cancel_escape_and_a_press_outside_drop_the_edits(
    page: Page, tmp_path: Path, how: str
) -> None:
    """Cancel, Escape and a press outside the dialog close it without saving."""
    _open(page, tmp_path)
    _text(page, "columns.max_history").fill("5")
    if how == "cancel":
        page.get_by_role("button", name="キャンセル").click()
    elif how == "escape":
        page.keyboard.press("Escape")
    else:
        page.mouse.click(2, 2)
    page.wait_for_function("window.prefsClosed")
    expect(page.locator(".prefs-backdrop")).to_have_count(0)
    assert _calls(page) == []


def test_a_press_inside_the_dialog_keeps_it(page: Page, tmp_path: Path) -> None:
    """A press on the dialog's own space does not close it."""
    _open(page, tmp_path)
    page.locator(".prefs-title").click()
    expect(page.locator(".prefs-dialog")).to_be_visible()


def test_the_focus_starts_in_the_first_input_and_tab_stays_in_the_dialog(
    page: Page, tmp_path: Path
) -> None:
    """The first input has the focus; Tab and Shift+Tab go round the inputs and buttons of the dialog alone."""
    _open(page, tmp_path)
    inside = "document.activeElement.closest('.prefs-dialog') !== null"
    assert page.evaluate("document.activeElement.classList.contains('prefs-slider')")
    # The slider, 8 text inputs and the DPI's select, Apply and Cancel.
    seen = []
    for _ in range(12):
        page.keyboard.press("Tab")
        assert page.evaluate(inside)
        seen.append(page.evaluate("document.activeElement.className"))
    choice = "prefs-text prefs-choice"
    assert seen == ["prefs-text"] * 3 + [choice] + ["prefs-text"] * 5 + ["prefs-apply", "prefs-cancel", "prefs-slider"]
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.classList.contains('prefs-cancel')")


def test_one_dialog_at_a_time(page: Page, tmp_path: Path) -> None:
    """Opening again while open shows no second dialog."""
    _open(page, tmp_path)
    page.evaluate(OPEN, _state(tmp_path))
    expect(page.locator(".prefs-dialog")).to_have_count(1)


def test_a_save_in_flight_is_not_sent_twice(page: Page, tmp_path: Path) -> None:
    """While a save is in flight, Apply, Enter, Escape and Cancel do nothing; then the dialog closes once."""
    _open(page, tmp_path)
    page.evaluate("window.saveDelay = 300")
    text = _text(page, "columns.max_history")
    text.fill("5")
    page.get_by_role("button", name="適用").click()
    expect(page.get_by_role("button", name="適用")).to_be_disabled()
    expect(page.get_by_role("button", name="キャンセル")).to_be_disabled()
    press_plain_enter(text)
    page.keyboard.press("Escape")
    page.wait_for_function("window.prefsClosed")
    assert [c[0] for c in _calls(page)] == ["save", "apply"]


def test_a_failed_save_keeps_the_edits_and_tells_why(page: Page, tmp_path: Path) -> None:
    """A save that fails shows its error in the dialog, keeps it open with the edits, applies nothing, and can be tried again."""
    _open(page, tmp_path)
    page.evaluate(
        "window.saveAnswers = [{ error: '設定を保存できませんでした：denied' }]"
    )
    _text(page, "columns.max_history").fill("5")
    page.get_by_role("button", name="適用").click()
    expect(page.locator(".prefs-message")).to_have_text("設定を保存できませんでした：denied")
    expect(_text(page, "columns.max_history")).to_have_value("5")
    expect(page.get_by_role("button", name="適用")).to_be_enabled()
    assert [c[0] for c in _calls(page)] == ["save"]
    page.get_by_role("button", name="適用").click()
    page.wait_for_function("window.prefsClosed")
    assert [c[0] for c in _calls(page)] == ["save", "save", "apply"]


def test_a_failed_redraw_says_the_save_is_done_and_retries(
    page: Page, tmp_path: Path
) -> None:
    """A save whose redraw fails says the settings are saved and the page is not updated; Apply then retries the redraw without saving again."""
    _open(page, tmp_path)
    page.evaluate("window.applyFails = 'redraw broke'")
    _text(page, OPACITY).fill("40")
    page.get_by_role("button", name="適用").click()
    message = page.locator(".prefs-message")
    expect(message).to_contain_text("設定は保存しました。ただし表示を更新できませんでした：redraw broke")
    expect(message).to_contain_text("もう一度「適用」を押すと、表示の更新をやり直します。")
    assert "保存できませんでした" not in message.inner_text()
    page.evaluate("window.applyFails = null")
    page.get_by_role("button", name="適用").click()
    page.wait_for_function("window.prefsClosed")
    calls = _calls(page)
    assert [c[0] for c in calls] == ["save", "apply", "apply"]
    assert calls[2][1] == [OPACITY]
    assert calls[2][2][OPACITY] == 0.4


def test_the_dpi_is_chosen_from_its_choices(page: Page, tmp_path: Path) -> None:
    """The DPI is a select of 96 and 300 showing the value in effect; choosing the other one saves and applies it."""
    _open(page, tmp_path)
    select = _text(page, "plot.image_copy.dpi")
    assert select.evaluate("(e) => [e.tagName, [...e.options].map((o) => o.value), e.value]") == [
        "SELECT", ["96", "300"], "300"
    ]
    select.select_option("96")
    page.locator(".prefs-apply").click()
    page.wait_for_function("window.prefsClosed")
    calls = _calls(page)
    assert calls[0] == ["save", {"plot.image_copy.dpi": 96}]
    assert calls[1][:2] == ["apply", ["plot.image_copy.dpi"]]
