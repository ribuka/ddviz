"""JS: scalemenu.js reads the number of intervals of a numeric color column."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.js.test_keys import press_conversion_enters, press_plain_enter

pytestmark = pytest.mark.js

SAFE = 9007199254740991


def _parse(page: Page, texts: list[str], limit: int) -> list[int | None]:
    """Return `parseColorBins` of each text under `limit`."""
    return page.evaluate(
        """async ([texts, limit]) => {
          const { parseColorBins } = await import("/static/js/scalemenu.js");
          return texts.map((text) => parseColorBins(text, limit));
        }""",
        [texts, limit],
    )


def test_the_number_of_intervals_takes_whole_numbers_from_2_to_the_limit(
    js_page: Page,
) -> None:
    """Under the limit 100, 2, 4, 7, 12 and 100 are taken, with blanks around and leading zeros; blank, 0, 1, negatives, signs, fractions, exponents, full-width digits, letters, 101 and numbers past the safe integers are refused."""
    good = {"2": 2, "4": 4, "7": 7, "12": 12, "100": 100, " 007 ": 7, "\t12\n": 12}
    wrong = ["", " ", "0", "1", "-2", "+3", "7.0", "1.5", "1e1", "７", "a", "7a", "101"]
    wrong += [str(SAFE), str(SAFE + 1)]
    found = _parse(js_page, [*good, *wrong], 100)
    assert found == list(good.values()) + [None] * len(wrong)


def test_the_number_of_intervals_follows_the_limit(js_page: Page) -> None:
    """The limit 12 takes 12 and refuses 13; the limit 1 takes nothing; a limit past the safe integers stops at them."""
    assert _parse(js_page, ["2", "12", "13"], 12) == [2, 12, None]
    assert _parse(js_page, ["1", "2"], 1) == [None, None]
    assert _parse(js_page, [str(SAFE), str(SAFE + 1)], SAFE + 10) == [SAFE, None]
    errors = js_page.evaluate(
        """async () => {
          const { colorBinsError } = await import("/static/js/scalemenu.js");
          return [colorBinsError(100), colorBinsError(12)];
        }"""
    )
    assert errors == [
        "2 以上 100 以下の整数を入力してください",
        "2 以上 12 以下の整数を入力してください",
    ]


def _open(page: Page, bins: dict | None, limit: int | None) -> None:
    """Open the menu with the cutting `bins` and the limit; `window.picked` gets each cutting passed to `onBins`."""
    page.evaluate(
        """async ([bins, limit]) => {
          const { openScaleMenu } = await import("/static/js/scalemenu.js");
          window.picked = [];
          openScaleMenu({ clientX: 10, clientY: 10 }, bins, (b) => window.picked.push(b),
            () => {}, 5, () => {}, limit);
        }""",
        [bins, limit],
    )


def test_the_menu_has_no_fixed_counts_and_shows_the_number_applied(js_page: Page) -> None:
    """The fixed counts are gone; the number is blank on a gradient and the number applied on intervals."""
    _open(js_page, None, 100)
    menu = js_page.locator(".scale-menu")
    expect(menu.get_by_label("区間数")).to_have_value("")
    for gone in ("2 個", "3 個", "5 個", "10 個"):
        expect(menu.get_by_text(gone, exact=True)).to_have_count(0)
    _open(js_page, {"n": 7, "by": "rows"}, 100)
    expect(js_page.locator(".scale-menu").get_by_label("区間数")).to_have_value("7")


def test_apply_and_enter_cut_only_into_a_new_number(js_page: Page) -> None:
    """Apply or Enter closes the menu and cuts into the number typed, the way to cut kept; the number applied already cuts nothing."""
    _open(js_page, {"n": 7, "by": "rows"}, 100)
    js_page.get_by_role("button", name="適用").click()
    expect(js_page.locator(".scale-menu")).to_have_count(0)
    assert js_page.evaluate("window.picked") == []
    _open(js_page, {"n": 7, "by": "rows"}, 100)
    number = js_page.get_by_label("区間数")
    number.fill(" 04 ")
    press_conversion_enters(number)
    assert js_page.evaluate("window.picked") == []
    press_plain_enter(number)
    expect(js_page.locator(".scale-menu")).to_have_count(0)
    assert js_page.evaluate("window.picked") == [{"n": 4, "by": "rows"}]


def test_a_wrong_number_shows_the_error_and_cuts_nothing(js_page: Page) -> None:
    """A wrong number keeps the menu open with the error and the focus on the field; typing again hides the error."""
    _open(js_page, None, 12)
    number = js_page.get_by_label("区間数")
    number.fill("13")
    js_page.get_by_role("button", name="適用").click()
    error = js_page.locator(".scale-menu-count-error")
    expect(error).to_have_text("2 以上 12 以下の整数を入力してください")
    expect(number).to_be_focused()
    assert js_page.evaluate("window.picked") == []
    number.fill("12")
    expect(error).to_be_hidden()
    press_plain_enter(number)
    assert js_page.evaluate("window.picked") == [{"n": 12, "by": "values"}]


def test_escape_drops_the_draft(js_page: Page) -> None:
    """Escape closes the menu without cutting; it opens again on the number applied."""
    _open(js_page, {"n": 7, "by": "values"}, 100)
    js_page.get_by_label("区間数").fill("4")
    js_page.keyboard.press("Escape")
    expect(js_page.locator(".scale-menu")).to_have_count(0)
    assert js_page.evaluate("window.picked") == []
    _open(js_page, {"n": 7, "by": "values"}, 100)
    expect(js_page.get_by_label("区間数")).to_have_value("7")


@pytest.mark.parametrize(
    ("limit", "note"),
    [
        (None, "区間数の上限を取得できません"),
        (1, "区間に分けるには plot.max_levels を 2 以上にしてください"),
    ],
)
def test_without_a_limit_of_2_or_more_the_number_is_off(
    js_page: Page, limit: int | None, note: str
) -> None:
    """Without the limit, or under a limit of 1, the number and its apply are off with a note; the gradient stays."""
    _open(js_page, {"n": 7, "by": "values"}, limit)
    menu = js_page.locator(".scale-menu")
    expect(menu.get_by_label("区間数")).to_be_disabled()
    expect(menu.get_by_role("button", name="適用")).to_be_disabled()
    expect(menu.locator(".scale-menu-count-note")).to_have_text(note)
    menu.get_by_text("連続（グラデーション）").click()
    assert js_page.evaluate("window.picked") == [None]


def test_the_error_keeps_the_menu_in_the_window(js_page: Page) -> None:
    """Opened at the window's bottom right, the menu made taller by the error moves up and its last item stays in the window."""
    js_page.set_viewport_size({"width": 1000, "height": 900})
    js_page.add_style_tag(url="/static/app.css")
    js_page.evaluate(
        """async () => {
          const { openScaleMenu } = await import("/static/js/scalemenu.js");
          openScaleMenu({ clientX: 999, clientY: 899 }, null, () => {}, () => {}, 5, () => {}, 100);
        }"""
    )
    menu = js_page.locator(".scale-menu")
    js_page.get_by_label("区間数").fill("101")
    js_page.get_by_role("button", name="適用").click()
    expect(menu.locator(".scale-menu-count-error")).to_be_visible()
    box = menu.bounding_box()
    assert box["y"] >= 0
    assert box["y"] + box["height"] <= 900
    last = menu.get_by_text("15 px", exact=True)
    last.scroll_into_view_if_needed()
    expect(last).to_be_in_viewport()
