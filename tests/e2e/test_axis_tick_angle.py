"""E2E: the axis dialog sets the angle of the tick labels of linear numeric and categorical axes."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_scatter import (
    PAINTED_PIXEL,
    SCROLL_AND_SETTLE,
    SETTLED,
    drop_at,
    place,
    watch_errors,
)

pytestmark = pytest.mark.e2e

ROWS = 2_000
FULL = "document.getElementById('plot')._fullLayout"
# The requests that aggregate a result.
AGGREGATING = re.compile(r"/api/(plot|view|overview)\b")
ANGLE_ERROR = "−90〜90 の整数にしてください"
# Wait before a double click, longer than plotly's (`doubleClickDelay`, 500ms
# in plotly 4.1.1): its first press reaches plotly, which would count it
# with the previous press.
APART_MS = 600

# The tick labels of an axis role shown: plotly's of a grid that fits (the
# text of each ``<role><n>tick`` group), or the strip's of one that scrolls,
# with their boxes, their transforms and the figure's (or the strip's) box.
LABELS = r"""(role) => {
  const gd = document.getElementById("plot");
  const side = role === "x" ? "bottom" : "left";
  const strip = document.querySelector(`.sticky-labels:not([hidden]) .sticky-strip.${side}`);
  const pattern = new RegExp(`^${role}\\d*tick$`);
  const els = strip
    ? [...strip.querySelectorAll(`.tick.${role}`)]
    : [...gd.querySelectorAll("g > text")].filter((t) => pattern.test(t.parentNode.getAttribute("class")));
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
  };
  return {
    scroll: Boolean(strip),
    edge: box(strip ?? gd),
    labels: els
      .map((e) => ({
        text: e.textContent,
        transform: strip ? e.style.transform : e.getAttribute("transform") ?? "",
        ...box(e),
      }))
      .filter((l) => l.right > l.left),
  };
}"""


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write numbers, long and short levels, and facets (overrides the shared data)."""
    rng = np.random.default_rng(127)
    n = np.arange(ROWS)
    path = tmp_path / "angles.parquet"
    pl.DataFrame(
        {
            "n": n,
            "small": rng.random(ROWS),
            "interest": -1_234_567.891 - 0.002 * rng.random(ROWS),
            "other": rng.random(ROWS) * 10,
            "name": [f"category_name_{i % 5}_" + "x" * 30 for i in n],
            "kind": [f"k{i % 4}" for i in n],
            "facet": [f"f{i % 12:02d}" for i in n],
            "g": [f"g{i % 8}" for i in n],
            "two": [f"t{i % 2}" for i in n],
            "when": [datetime(2024, 1, 1) + timedelta(hours=int(i)) for i in n],  # noqa: DTZ001
        }
    ).write_parquet(path)
    return path


def labels(page: Page, role: str) -> dict:
    """Return the tick labels of `role` shown, and whether the grid scrolls."""
    return page.evaluate(LABELS, role)


def margins(page: Page) -> dict:
    """Return the figure's margins and the bottom of its x axis."""
    return page.evaluate(
        f"""() => {{ const f = {FULL};
          return {{ l: f.margin.l, b: f.margin.b, height: f.height,
            bottom: f.yaxis._offset + f.yaxis._length, offset: f.xaxis._offset }}; }}"""
    )


def settle(page: Page) -> None:
    """Wait for the results of the margins' requests: the status settled and the margins stay."""
    for _ in range(20):
        page.wait_for_timeout(600)
        page.wait_for_function(SETTLED)
        before = margins(page)
        page.wait_for_timeout(600)
        page.wait_for_function(SETTLED)
        if margins(page) == before:
            return
    raise AssertionError("the margins did not settle")


def record(page: Page) -> list[str]:
    """Record the URLs of the requests that aggregate a result from now on."""
    urls: list[str] = []
    page.on(
        "request",
        lambda request: AGGREGATING.search(request.url) and urls.append(request.url),
    )
    return urls


def open_dialog(page: Page, role: str, first: bool = False) -> Locator:
    """Double-click the middle (or the first) tick label of `role` in sight, and return the dialog it opens."""
    found = labels(page, role)
    edge = found["edge"]
    shown = [
        label
        for label in found["labels"]
        if edge["left"] <= (label["left"] + label["right"]) / 2 <= edge["right"]
        and edge["top"] <= (label["top"] + label["bottom"]) / 2 <= edge["bottom"]
    ]
    label = shown[0 if first else len(shown) // 2]
    page.wait_for_timeout(APART_MS)
    page.mouse.dblclick(
        (label["left"] + label["right"]) / 2, (label["top"] + label["bottom"]) / 2
    )
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog).to_be_visible()
    return dialog


def set_angle(
    page: Page, role: str, angle: str, button: str = "OK", first: bool = False
) -> Locator:
    """Open the dialog of `role`, type an angle and press a button (or Enter); return the dialog."""
    dialog = open_dialog(page, role, first)
    field = dialog.locator("input[name=angle]")
    field.fill(angle)
    if button == "Enter":
        field.press("Enter")
    else:
        dialog.get_by_role("button", name=button).click()
    return dialog


def tick_angle(page: Page, key: str) -> object:
    """Return the angle set on an axis of the figure drawn (None for plotly's own)."""
    return page.evaluate(f"document.getElementById('plot').layout.{key}.tickangle ?? null")


def place_second(page: Page, column: str, role: str) -> None:
    """Drop a column after the zone's first axis column: a second panel column or row."""
    zone = page.locator(f'.zone[data-role="{role}"]').bounding_box()
    if role == "y":
        drop_at(page, column, role, zone["width"] / 2, zone["height"] * 0.95)
    else:
        drop_at(page, column, role, zone["width"] * 0.95, zone["height"] / 2)


def test_a_categorical_axis_sets_the_angle_alone(app_page: Page) -> None:
    """A categorical x opens the dialog with every field but the angle disabled; the angle is drawn and its margin follows."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "kind", "x")
    place(page, "small", "y")
    settle(page)
    dialog = open_dialog(page, "x")
    expect(dialog.locator("h2")).to_have_text("X 軸: kind")
    angle = dialog.locator("input[name=angle]")
    expect(angle).to_be_focused()
    expect(angle).to_be_enabled()
    controls = dialog.locator(".axis-dialog-section").locator("input, select, button")
    enabled = controls.evaluate_all("(els) => els.filter((e) => !e.disabled).map((e) => e.name)")
    assert enabled == ["angle"]
    # Disabled fields take no keyboard focus.
    page.keyboard.press("Shift+Tab")
    expect(dialog.locator("input[name=min]")).not_to_be_focused()

    urls = record(page)
    range_before = page.evaluate(f"{FULL}.xaxis.range")
    angle.fill("45")
    dialog.get_by_role("button", name="適用").click()
    expect(dialog).to_be_visible()
    page.wait_for_function("() => document.getElementById('plot').layout.xaxis.tickangle === 45")
    settle(page)
    assert page.evaluate(f"{FULL}.xaxis.range") == range_before
    assert all("rotate(45" in label["transform"] for label in labels(page, "x")["labels"])
    # The settings of a numeric axis are not kept for a categorical one.
    assert page.evaluate(f"{FULL}.shapes.length") == 0
    dialog.get_by_role("button", name="キャンセル").click()
    expect(dialog).to_have_count(0)
    assert all(AGGREGATING.search(u) for u in urls)
    assert not errors


@pytest.mark.parametrize("angle", ["-90", "-45", "0", "45", "90"])
def test_the_angles_draw_as_set(app_page: Page, angle: str) -> None:
    """−90°, −45°, 0°, 45° and 90° turn the labels of a numeric x and y clockwise as set; an empty field gives plotly's own back."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x")
    place(page, "small", "y")
    settle(page)
    for role in ["x", "y"]:
        set_angle(page, role, angle)
        page.wait_for_function(
            f"() => document.getElementById('plot').layout.{role}axis.tickangle === {angle}"
        )
        settle(page)
        assert page.evaluate(f"{FULL}.{role}axis.tickangle") == int(angle)
        shown = labels(page, role)["labels"]
        assert shown
        for label in shown:
            if angle == "0":
                assert "rotate" not in label["transform"] or "rotate(0" in label["transform"]
            else:
                assert f"rotate({angle}" in label["transform"], label
    # A label of several digits turned by 90 degrees is higher than wide.
    if angle in ("-90", "90"):
        label = max(labels(page, "x")["labels"], key=lambda label: len(label["text"]))
        assert label["bottom"] - label["top"] > label["right"] - label["left"]
    for role in ["x", "y"]:
        set_angle(page, role, "  ")
        page.wait_for_function(
            f"() => document.getElementById('plot').layout.{role}axis.tickangle === undefined"
        )
    settle(page)
    assert margins(page)["b"] == 30
    assert not errors


def test_wrong_angles_tell_why_and_change_nothing(app_page: Page) -> None:
    """−91, 91, 22.5, text and full-width digits are refused beside the field, with the other edits."""
    page = app_page
    place(page, "n", "x")
    place(page, "small", "y")
    settle(page)
    urls = record(page)
    dialog = open_dialog(page, "y")
    error = dialog.locator("input[name=angle] ~ .axis-dialog-error")
    for wrong in ["-91", "91", "22.5", "abc", "４５", "+-4", "1e1"]:
        dialog.locator("input[name=dtick]").fill("0.25")
        dialog.locator("input[name=angle]").fill(wrong)
        dialog.get_by_role("button", name="OK").click()
        expect(error).to_have_text(ANGLE_ERROR)
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="適用").click()
        expect(error).to_have_text(ANGLE_ERROR)
        dialog.locator("input[name=angle]").press("Enter")
        expect(dialog).to_be_visible()
    assert tick_angle(page, "yaxis") is None
    assert page.evaluate(f"{FULL}.yaxis.tickmode") == "auto"
    # The bounds and a sign are taken; the error goes.
    dialog.locator("input[name=angle]").fill(" +90 ")
    dialog.get_by_role("button", name="適用").click()
    expect(error).to_have_text("")
    page.wait_for_function("() => document.getElementById('plot').layout.yaxis.tickangle === 90")
    assert page.evaluate(f"{FULL}.yaxis.dtick") == 0.25
    dialog.get_by_role("button", name="キャンセル").click()
    assert not [u for u in urls if "/api/view" in u and "range" in u]


def test_apply_ok_enter_cancel_and_esc(app_page: Page) -> None:
    """Apply keeps the dialog open, OK and Enter close it; Cancel and Esc drop the edits since the last apply; the dialog opens with the angle applied."""
    page = app_page
    place(page, "n", "x")
    place(page, "small", "y")
    settle(page)
    dialog = set_angle(page, "x", "30", "適用")
    expect(dialog).to_be_visible()
    page.wait_for_function("() => document.getElementById('plot').layout.xaxis.tickangle === 30")
    settle(page)
    dialog.locator("input[name=angle]").fill("60")
    dialog.get_by_role("button", name="キャンセル").click()
    expect(dialog).to_have_count(0)
    page.wait_for_timeout(300)
    assert tick_angle(page, "xaxis") == 30

    dialog = set_angle(page, "x", "-60", "Enter")
    expect(dialog).to_have_count(0)
    page.wait_for_function("() => document.getElementById('plot').layout.xaxis.tickangle === -60")
    settle(page)

    dialog = open_dialog(page, "x")
    expect(dialog.locator("input[name=angle]")).to_have_value("-60")
    dialog.locator("input[name=angle]").fill("10")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    page.wait_for_timeout(300)
    assert tick_angle(page, "xaxis") == -60

    dialog = set_angle(page, "x", "0", "OK")
    expect(dialog).to_have_count(0)
    page.wait_for_function("() => document.getElementById('plot').layout.xaxis.tickangle === 0")
    settle(page)
    dialog = open_dialog(page, "x")
    expect(dialog.locator("input[name=angle]")).to_have_value("0")
    page.keyboard.press("Escape")


def test_an_angle_alone_asks_nothing(app_page: Page) -> None:
    """An angle whose labels keep the margins draws without a request, keeping the view, the reversed axis and the selection."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x")
    place(page, "small", "y")
    settle(page)
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [100, 900]})")
    settle(page)
    shown = page.evaluate(f"[{FULL}.xaxis.range, {FULL}.yaxis.range]")
    urls = record(page)
    set_angle(page, "x", "0")
    page.wait_for_function("() => document.getElementById('plot').layout.xaxis.tickangle === 0")
    set_angle(page, "y", "-10")
    page.wait_for_function("() => document.getElementById('plot').layout.yaxis.tickangle === -10")
    settle(page)
    assert margins(page)["b"] == 30
    assert margins(page)["l"] == 50
    assert urls == []
    assert page.evaluate(f"[{FULL}.xaxis.range, {FULL}.yaxis.range]") == shown
    assert not errors


def test_x_and_y_of_one_column_keep_their_own_angles(app_page: Page) -> None:
    """The same column on X and Y takes an angle of each, on its own panels of every facet; another axis column keeps plotly's; zooms, the overview and drawing again keep them."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1300, "height": 800})
    place(page, "small", "x")
    place(page, "small", "y")
    place(page, "two", "col")
    place_second(page, "other", "y")
    settle(page)
    set_angle(page, "x", "30")
    page.wait_for_function("() => document.getElementById('plot').layout.xaxis.tickangle === 30")
    settle(page)
    set_angle(page, "y", "-20", first=True)
    page.wait_for_function("() => document.getElementById('plot').layout.yaxis.tickangle === -20")
    settle(page)

    def angles() -> dict:
        return page.evaluate(
            """() => {
              const gd = document.getElementById("plot");
              const meta = gd._fullLayout;
              const out = {};
              for (const key of Object.keys(gd.layout).filter((k) => /^[xy]axis\\d*$/.test(k))) {
                out[key] = gd.layout[key].tickangle ?? null;
              }
              return out;
            }"""
        )

    def check() -> None:
        meta = page.evaluate(
            "() => [...document.querySelectorAll('#plot .subplot')].length"
        )
        assert meta
        drawn = angles()
        # Panels: 2 facets x 2 y columns; the first y column (small) is the
        # top row.
        ys = {k: v for k, v in drawn.items() if k.startswith("y")}
        xs = {k: v for k, v in drawn.items() if k.startswith("x")}
        assert set(xs.values()) == {30}, drawn
        small_rows = [v for k, v in ys.items() if k in ("yaxis", "yaxis2")]
        other_rows = [v for k, v in ys.items() if k in ("yaxis3", "yaxis4")]
        assert small_rows == [-20, -20], drawn
        assert other_rows == [None, None], drawn

    check()
    page.evaluate("Plotly.relayout('plot', {'xaxis.range': [0.2, 0.6], 'yaxis.range': [0.1, 0.4]})")
    settle(page)
    check()
    # Reset axes from the plot area's double click.
    box = page.locator("#plot .nsewdrag").first.bounding_box()
    page.wait_for_timeout(APART_MS)
    page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    settle(page)
    check()
    # The same column placed again on X, and a new graph drawn.
    place(page, "small", "x")
    settle(page)
    check()
    assert not errors


def test_a_log_axis_hides_its_angle_until_linear(app_page: Page) -> None:
    """A numeric axis on a log scale draws plotly's labels and opens no dialog; linear again, its angle comes back."""
    page = app_page
    place(page, "n", "x")
    place(page, "other", "y")
    settle(page)
    set_angle(page, "y", "45")
    page.wait_for_function("() => document.getElementById('plot').layout.yaxis.tickangle === 45")
    settle(page)
    shown = labels(page, "y")["labels"]
    label = shown[len(shown) // 2]
    point = (label["right"] - 3, (label["top"] + label["bottom"]) / 2)
    page.mouse.click(*point, button="right")
    page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    page.wait_for_function(f"() => {FULL}.yaxis.type === 'log'")
    settle(page)
    assert tick_angle(page, "yaxis") is None
    shown = labels(page, "y")["labels"]
    label = shown[len(shown) // 2]
    page.wait_for_timeout(APART_MS)
    page.mouse.dblclick(label["right"] - 3, (label["top"] + label["bottom"]) / 2)
    page.wait_for_timeout(300)
    expect(page.locator("dialog.axis-dialog")).to_have_count(0)
    page.wait_for_function(SETTLED)
    page.mouse.click(label["right"] - 3, (label["top"] + label["bottom"]) / 2, button="right")
    page.locator(".axis-menu").get_by_role("button", name="対数表示").click()
    page.wait_for_function(f"() => {FULL}.yaxis.type === 'linear'")
    settle(page)
    assert tick_angle(page, "yaxis") == 45


@pytest.mark.parametrize("angle", ["90", "-90"])
def test_long_x_labels_at_90_fit_the_bottom_margin(app_page: Page, angle: str) -> None:
    """Long levels on X at ±90° widen the bottom margin to show them whole; the frame and the images follow, and a turned label opens the dialog again."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 900})
    place(page, "name", "x")
    place(page, "small", "y")
    settle(page)
    assert margins(page)["b"] == 30
    urls = record(page)
    set_angle(page, "x", angle)
    page.wait_for_function(f"() => {FULL}.margin.b > 100")
    settle(page)
    assert [u for u in urls if "/api/overview" in u]
    drawn = margins(page)
    # The frame of the plot area ends at the margin.
    assert drawn["bottom"] == drawn["height"] - drawn["b"]
    shown = labels(page, "x")
    assert shown["labels"]
    for label in shown["labels"]:
        assert label["bottom"] <= shown["edge"]["bottom"] - 2 + 0.5, (label, shown["edge"])
        assert label["text"].startswith("category_name_")
    pixel = page.evaluate(PAINTED_PIXEL)
    assert pixel is not None
    top = page.locator("#plot").bounding_box()["y"]
    assert pixel["y"] <= top + drawn["bottom"]
    # The far end of a turned label is below plotly's drag area of the axis.
    label = shown["labels"][0]
    page.wait_for_timeout(APART_MS)
    page.mouse.dblclick((label["left"] + label["right"]) / 2, label["bottom"] - 4)
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog.locator("h2")).to_have_text("X 軸: name")
    expect(dialog.locator("input[name=angle]")).to_have_value(angle)
    # Emptied, the margin is 30 again.
    dialog.locator("input[name=angle]").fill("")
    dialog.get_by_role("button", name="OK").click()
    page.wait_for_function(f"() => {FULL}.margin.b === 30")
    settle(page)
    assert not errors


def test_a_turned_y_sets_the_left_margin(app_page: Page) -> None:
    """The left margin follows the width of the y labels turned: long amounts at 90° need less than level ones."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1200, "height": 800})
    place(page, "n", "x")
    place(page, "interest", "y")
    settle(page)
    level = margins(page)["l"]
    assert level > 100
    set_angle(page, "y", "90")
    page.wait_for_function(f"() => {FULL}.margin.l < {level}")
    settle(page)
    shown = labels(page, "y")
    for label in shown["labels"]:
        assert label["left"] >= shown["edge"]["left"] + 2 - 0.5
    # A turned label reaching above its panel opens the dialog from there.
    top = page.evaluate(
        f"document.getElementById('plot').getBoundingClientRect().top + {FULL}.yaxis._offset"
    )
    above = [label for label in shown["labels"] if label["top"] < top - 8]
    assert above
    label = above[0]
    page.wait_for_timeout(APART_MS)
    page.mouse.dblclick((label["left"] + label["right"]) / 2, label["top"] + 3)
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog.locator("h2")).to_have_text("Y 軸: interest")
    expect(dialog.locator("input[name=angle]")).to_have_value("90")
    dialog.get_by_role("button", name="キャンセル").click()
    expect(dialog).to_have_count(0)
    set_angle(page, "y", "-45")
    settle(page)
    shown = labels(page, "y")
    turned = margins(page)["l"]
    assert margins(page)["l"] < level
    for label in shown["labels"]:
        assert label["left"] >= shown["edge"]["left"] + 2 - 0.5
    assert turned > 50
    assert not errors


def test_the_strips_of_a_scrolled_grid_turn_their_labels(app_page: Page) -> None:
    """Scrolled both ways, the strips turn the labels of the angles set, keep them whole in the margins, and open the dialog from a turned label."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 900, "height": 700})
    place(page, "name", "x")
    place(page, "interest", "y")
    place(page, "facet", "row")
    place(page, "g", "col")
    settle(page)
    expect(page.locator("#stage")).to_have_class(re.compile(r"\bscrolls\b"))
    scroller = page.locator("#scroller")
    scroller.evaluate(SCROLL_AND_SETTLE, 10_000)
    scroller.evaluate(
        "async (s) => { s.scrollTop = 10000; s.dispatchEvent(new Event('scroll'));"
        " for (let i = 0; i < 2; i++) await new Promise((r) => requestAnimationFrame(r)); }"
    )
    assert scroller.evaluate("(s) => s.scrollLeft") > 0
    assert scroller.evaluate("(s) => s.scrollTop") > 0
    before = margins(page)
    set_angle(page, "x", "60")
    page.wait_for_function(f"() => {FULL}.margin.b > 60")
    settle(page)
    set_angle(page, "y", "-30")
    settle(page)
    assert margins(page)["l"] < before["l"]
    for role in ["x", "y"]:
        shown = labels(page, role)
        assert shown["scroll"]
        assert shown["labels"]
        angle = "60" if role == "x" else "-30"
        for label in shown["labels"]:
            assert f"rotate({angle}deg)" in label["transform"], label
        if role == "x":
            for label in shown["labels"]:
                assert label["top"] >= shown["edge"]["top"]
                assert label["bottom"] <= shown["edge"]["bottom"] - 2 + 0.5
        else:
            for label in shown["labels"]:
                assert label["left"] >= shown["edge"]["left"] + 2 - 0.5
                assert label["right"] <= shown["edge"]["right"]
    # A turned x label in sight opens its axis's dialog at its far end.
    found = labels(page, "x")
    shown = [
        label
        for label in found["labels"]
        if found["edge"]["left"] < label["left"] and label["right"] < found["edge"]["right"]
    ]
    label = shown[len(shown) // 2]
    page.wait_for_timeout(APART_MS)
    page.mouse.dblclick(label["right"] - 4, label["bottom"] - 4)
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog.locator("h2")).to_have_text("X 軸: name")
    expect(dialog.locator("input[name=angle]")).to_have_value("60")
    dialog.get_by_role("button", name="キャンセル").click()
    open_dialog(page, "y")
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog.locator("h2")).to_have_text("Y 軸: interest")
    expect(dialog.locator("input[name=angle]")).to_have_value("-30")
    dialog.get_by_role("button", name="キャンセル").click()
    assert not errors


def test_temporal_axes_and_the_one_band_have_no_angle(app_page: Page) -> None:
    """A temporal axis's dialog has no angle; the one band of an empty X opens no dialog."""
    page = app_page
    place(page, "when", "x")
    place(page, "small", "y")
    settle(page)
    dialog = open_dialog(page, "x")
    expect(dialog.locator("h2")).to_have_text("X 軸: when")
    expect(dialog.locator("input[name=angle]")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)

    page.locator('.zone[data-role="x"] .chip-remove').click()
    page.wait_for_function(SETTLED)
    # The box plots of the one band are ticked by series.
    place(page, "kind", "color")
    page.locator("#elements .element").nth(1).click()
    expect(page.locator("#plot .xtick text")).not_to_have_count(0)
    settle(page)
    shown = labels(page, "x")["labels"]
    assert shown
    label = shown[0]
    page.wait_for_timeout(APART_MS)
    page.mouse.dblclick(
        (label["left"] + label["right"]) / 2, (label["top"] + label["bottom"]) / 2
    )
    page.wait_for_timeout(300)
    expect(page.locator("dialog.axis-dialog")).to_have_count(0)
