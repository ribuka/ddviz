"""E2E: the axis dialog picks the format of the tick labels of a numeric axis (Issue #107)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_left_margin import (
    FULL,
    assert_aligned,
    assert_whole,
    record,
    settle,
    x_labels,
    y_labels,
)
from tests.e2e.test_scatter import SCROLL_AND_SETTLE, SETTLED, place, watch_errors

pytestmark = pytest.mark.e2e

ROWS = 2_000
DIGITS_ERROR = "0〜15 の整数にしてください"


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write repayments of about 94,000 to 107,000, amounts, rates and facets (overrides the shared data)."""
    rng = np.random.default_rng(107)
    n = np.arange(ROWS)
    path = tmp_path / "loan.parquet"
    pl.DataFrame(
        {
            "n": n,
            "pay": 94_000 + 13_000 * rng.random(ROWS),
            "amount": 40_000 * rng.random(ROWS),
            "rate": 0.03 * rng.random(ROWS),
            "facet": [f"f{i % 12:02d}" for i in n],
            "g": [f"g{i % 2}" for i in n],
        }
    ).write_parquet(path)
    return path


def open_dialog(page: Page, side: str) -> Locator:
    """Double-click the first tick label of the first x or y axis and return the dialog it opens."""
    tick = page.locator(f"#plot .{side}tick text").first.bounding_box()
    page.mouse.dblclick(tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2)
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog).to_be_visible()
    return dialog


def pick(
    dialog: Locator,
    kind: str,
    digits: str | None = None,
    separators: bool | None = None,
) -> None:
    """Pick a format of the labels, and type its digits and check its separators when given."""
    dialog.locator("select[name=format]").select_option(kind)
    if digits is not None:
        dialog.locator("input[name=digits]").fill(digits)
    if separators is not None:
        dialog.locator("input[name=separators]").set_checked(separators)


def plotly_y_labels(page: Page) -> list[str]:
    """Return the texts of plotly's y tick labels, of any y axis (``y<n>tick``)."""
    return page.evaluate(
        r"""() => [...document.querySelectorAll("#plot g > text")]
          .filter((t) => /^y\d*tick$/.test(t.parentNode.getAttribute("class")))
          .map((t) => t.textContent)"""
    )


def formats(page: Page) -> dict[str, str]:
    """Return the ``tickformat`` set on every axis of the drawn figure ("" for none), by its layout key.

    The layout, not the full one: plotly leaves the attributes of an axis
    without labels of its own (the panels right of the first) out of that.
    """
    return page.evaluate(
        r"""() => { const l = document.getElementById("plot").layout;
          return Object.fromEntries(Object.keys(l).filter((k) => /^[xy]axis\d*$/.test(k))
            .map((k) => [k, l[k].tickformat ?? ""])); }"""
    )


def test_the_format_of_y_labels_applies_without_aggregating(app_page: Page) -> None:
    """Decimal with 0 digits and separators shows 100,000; only the fields of the format are usable, wrong digits and Cancel/Esc apply nothing, and the applied fields come back."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x", plots=False)
    place(page, "pay", "y")
    settle(page)
    # The automatic labels turn to exponents, as before.
    assert "1e+5" in plotly_y_labels(page)
    assert set(formats(page).values()) == {""}

    dialog = open_dialog(page, "y")
    form = dialog.locator("select[name=format]")
    digits = dialog.locator("input[name=digits]")
    separators = dialog.locator("input[name=separators]")
    expect(form).to_have_value("auto")
    expect(digits).to_have_value("2")
    expect(digits).to_be_disabled()
    expect(separators).not_to_be_checked()
    expect(separators).to_be_enabled()

    # Each format enables only its fields; what was typed comes back.
    pick(dialog, "fixed", "0", True)
    expect(digits).to_be_enabled()
    pick(dialog, "exponent")
    expect(digits).to_be_enabled()
    expect(separators).to_be_disabled()
    pick(dialog, "percent")
    expect(separators).to_be_enabled()
    expect(separators).to_be_checked()
    expect(digits).to_have_value("0")

    margin = y_labels(page)["margin"]
    urls = record(page)
    pick(dialog, "fixed")
    dialog.get_by_role("button", name="適用").click()
    expect(dialog).to_be_visible()
    page.wait_for_function("() => document.querySelector('#plot .ytick text') !== null")
    settle(page)
    assert "100,000" in plotly_y_labels(page)
    assert formats(page)["yaxis"] == ",.0f"
    # Labels alone aggregate nothing; the margin follows them (Issue #104):
    # a new width aggregates the shown range again for its size
    # (``/api/overview`` at the overview), the same one asks for nothing.
    assert not [u for u in urls if "/api/plot" in u], urls
    assert len(urls) == (0 if y_labels(page)["margin"] == margin else 1), urls
    assert_whole(y_labels(page))
    assert_aligned(page)

    # Wrong digits apply nothing, not even the other fields.
    before = formats(page)
    for wrong in ["16", "", "1.5", "-1", "a"]:
        pick(dialog, "exponent", wrong)
        dialog.locator("input[name=dtick]").fill("5000")
        dialog.get_by_role("button", name="OK").click()
        expect(dialog).to_be_visible()
        expect(dialog.locator(".axis-dialog-error").nth(4)).to_have_text(DIGITS_ERROR)
    assert formats(page) == before
    assert page.evaluate(f"{FULL}.yaxis.tickmode") == "auto"
    # A disabled field is not checked.
    pick(dialog, "auto")
    expect(dialog.locator(".axis-dialog-error").nth(4)).to_have_text("")

    # Cancel and Esc drop what was not applied.
    dialog.get_by_role("button", name="キャンセル").click()
    expect(dialog).to_have_count(0)
    for close in ["cancel", "esc"]:
        dialog = open_dialog(page, "y")
        expect(dialog.locator("select[name=format]")).to_have_value("fixed")
        expect(dialog.locator("input[name=digits]")).to_have_value("0")
        expect(dialog.locator("input[name=separators]")).to_be_checked()
        expect(dialog.locator("input[name=dtick]")).to_have_value("")
        pick(dialog, "percent", "3", False)
        if close == "cancel":
            dialog.get_by_role("button", name="キャンセル").click()
        else:
            page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        assert formats(page)["yaxis"] == ",.0f"

    # Automatic with separators puts them in 4 digits too; the x labels
    # leave the left margin as it is: nothing is aggregated.
    urls = record(page)
    dialog = open_dialog(page, "x")
    pick(dialog, "auto", separators=True)
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    page.wait_for_timeout(1_000)
    assert "1,000" in x_labels(page), x_labels(page)
    assert formats(page)["xaxis"] == ""
    assert page.evaluate(f"{FULL}.xaxis.separatethousands") is True
    assert urls == []
    assert not errors


def test_exponent_and_percent_keep_the_values(app_page: Page) -> None:
    """Exponent with 2 digits shows 5.00e+3 and 3.50e+4; percent with 2 digits shows 1.50% at the place of 0.015, where its line stays."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "amount", "x", plots=False)
    place(page, "rate", "y")
    settle(page)

    dialog = open_dialog(page, "x")
    dialog.locator("input[name=min]").fill("0")
    dialog.locator("input[name=max]").fill("40000")
    dialog.locator("input[name=dtick]").fill("5000")
    pick(dialog, "exponent", "2")
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    page.wait_for_function(SETTLED)
    labels = x_labels(page)
    assert "5.00e+3" in labels, labels
    assert "3.50e+4" in labels, labels

    dialog = open_dialog(page, "y")
    dialog.locator("input[name=dtick]").fill("0.005")
    dialog.locator("input[name=line]").fill("0.015")
    dialog.get_by_role("button", name="追加").click()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    settle(page)
    # The place of 0.015 on the page, and of the line drawn at it.
    place_of = f"""() => {{ const ya = {FULL}.yaxis;
      const line = document.querySelector("#plot .shapelayer path").getBoundingClientRect();
      return {{ at: ya._offset + ya.l2p(0.015), line: line.top + line.height / 2,
        range: ya.range }}; }}"""
    before = page.evaluate(place_of)

    urls = record(page)
    dialog = open_dialog(page, "y")
    pick(dialog, "percent", "2", True)
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    settle(page)
    assert "1.50%" in plotly_y_labels(page), plotly_y_labels(page)
    assert formats(page)["yaxis"] == ",.2%"
    after = page.evaluate(place_of)
    assert after["range"] == pytest.approx(before["range"])
    assert after["at"] == pytest.approx(before["at"])
    assert after["line"] == pytest.approx(before["line"], abs=0.5)
    assert after["line"] == pytest.approx(
        after["at"] + page.locator("#plot").bounding_box()["y"], abs=1
    )
    assert page.evaluate(f"{FULL}.shapes.map((s) => s.y0)") == [0.015]
    # Only a new width of the margin (Issue #104) aggregates, for its size.
    assert not [u for u in urls if "/api/plot" in u], urls
    assert len(urls) <= 1, urls
    # Reopened, the fields are the applied ones.
    dialog = open_dialog(page, "y")
    expect(dialog.locator("select[name=format]")).to_have_value("percent")
    expect(dialog.locator("input[name=digits]")).to_have_value("2")
    expect(dialog.locator("input[name=separators]")).to_be_checked()
    page.keyboard.press("Escape")
    assert not errors


def test_a_column_format_follows_it_to_every_axis_and_view(app_page: Page) -> None:
    """A column's format labels all its panels, on X and Y, the scrolled strips, zoomed and back at the overview; other columns keep theirs, and automatic without separators drops it."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x", plots=False)
    place(page, "pay", "y")
    place(page, "g", "col")
    settle(page)

    dialog = open_dialog(page, "y")
    pick(dialog, "fixed", "0", True)
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    settle(page)
    shown = formats(page)
    assert shown == {"xaxis": "", "xaxis2": "", "yaxis": ",.0f", "yaxis2": ",.0f"}

    # The same column on X takes the same format; n on Y keeps its own.
    place(page, "pay", "x")
    place(page, "n", "y")
    settle(page)
    shown = formats(page)
    assert shown == {"xaxis": ",.0f", "xaxis2": ",.0f", "yaxis": "", "yaxis2": ""}
    assert "100,000" in x_labels(page)
    place(page, "n", "x")
    place(page, "pay", "y")
    settle(page)

    # A zoom and the overview keep it.
    page.evaluate(
        "Plotly.relayout(document.getElementById('plot'), {'yaxis.range': [99000, 101000]})"
    )
    expect(page.locator("#status")).to_contain_text("表示範囲に")
    settle(page)
    assert formats(page)["yaxis"] == ",.0f"
    assert "100,000" in plotly_y_labels(page)
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator("#status")).not_to_contain_text("表示範囲に")
    settle(page)
    assert formats(page)["yaxis"] == ",.0f"
    assert "100,000" in plotly_y_labels(page)

    # The strips of a grid that scrolls show the same labels.
    page.set_viewport_size({"width": 800, "height": 600})
    place(page, "facet", "col")
    settle(page)
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    page.locator("#scroller").evaluate(SCROLL_AND_SETTLE, 10_000)
    strip = page.locator(".sticky-strip .tick.y").all_text_contents()
    assert "100,000" in strip, strip
    assert_whole(y_labels(page))

    # Automatic without separators is plotly's own labels again.
    tick = page.locator(".sticky-strip .tick.y").last.bounding_box()
    page.mouse.dblclick(tick["x"] + tick["width"] / 2, tick["y"] + tick["height"] / 2)
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog.locator("h2")).to_have_text("Y 軸: pay")
    pick(dialog, "auto", separators=False)
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    settle(page)
    assert set(formats(page).values()) == {""}
    assert "1e+5" in page.locator(".sticky-strip .tick.y").all_text_contents()
    assert not errors
