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
from tests.e2e.test_scatter import SCROLL_AND_SETTLE, place, watch_errors

pytestmark = pytest.mark.e2e

ROWS = 2_000


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write repayments of about 94,000 to 107,000 and facets (overrides the shared data)."""
    rng = np.random.default_rng(107)
    n = np.arange(ROWS)
    path = tmp_path / "loan.parquet"
    pl.DataFrame(
        {
            "n": n,
            "pay": 94_000 + 13_000 * rng.random(ROWS),
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


# The place of 100,000 on the page, of the line drawn at it, and the range of y.
PLACE_OF = f"""() => {{ const ya = {FULL}.yaxis;
  const line = document.querySelector("#plot .shapelayer path").getBoundingClientRect();
  return {{ at: ya._offset + ya.l2p(100000), line: line.top + line.height / 2,
    range: ya.range }}; }}"""


def test_the_format_of_y_labels_applies_without_aggregating(app_page: Page) -> None:
    """Decimal with 0 digits and separators shows 100,000 without aggregating, the margin following the labels; percent changes the labels alone, not the range nor a line's place (the fields and formats: `tests/js/test_axisdialog.py`)."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x")
    place(page, "pay", "y")
    settle(page)
    # The automatic labels turn to exponents, as before.
    assert "1e+5" in plotly_y_labels(page)
    assert set(formats(page).values()) == {""}

    margin = y_labels(page)["margin"]
    urls = record(page)
    dialog = open_dialog(page, "y")
    pick(dialog, "fixed", "0", True)
    dialog.locator("input[name=line]").fill("100000")
    dialog.get_by_role("button", name="追加").click()
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

    # Percent changes the labels alone: the range and the line stay in place.
    before = page.evaluate(PLACE_OF)
    urls = record(page)
    pick(dialog, "percent", "2", True)
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    settle(page)
    assert formats(page)["yaxis"] == ",.2%"
    shown = plotly_y_labels(page)
    assert shown and all(t.endswith("%") for t in shown), shown
    after = page.evaluate(PLACE_OF)
    assert after["range"] == pytest.approx(before["range"])
    assert after["at"] == pytest.approx(before["at"])
    assert after["line"] == pytest.approx(
        after["at"] + page.locator("#plot").bounding_box()["y"], abs=1
    )
    assert page.evaluate(f"{FULL}.shapes.map((s) => s.y0)") == [100000]
    assert not [u for u in urls if "/api/plot" in u], urls
    assert len(urls) <= 1, urls
    assert not errors


def test_a_column_format_follows_it_to_every_axis_and_view(app_page: Page) -> None:
    """A column's format labels all its panels, on X and Y, the scrolled strips, zoomed and back at the overview; other columns keep theirs, and automatic without separators drops it."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x")
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
