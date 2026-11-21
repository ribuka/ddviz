"""E2E: a filter card's list takes the height its bottom edge is dragged to, and the cards move by their heads (Issue #210)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_color_levels import card
from tests.e2e.test_scatter import (
    SETTLED,
    drag_filter_edge,
    drawn_task,
    drop_on_filters,
    new_result,
    place,
    wait_idle,
    watch_errors,
)

pytestmark = pytest.mark.e2e

ROWS = 3000
# Numeric columns that only make more cards.
MORE = [f"k{i}" for i in range(1, 7)]


@pytest.fixture
def scatter_frame() -> pl.DataFrame:
    """Return x, y, a datetime, a column of 40 levels (cat), two of 1,500 levels (label, word) and the numeric `MORE`."""
    rng = np.random.default_rng(0)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "x": rng.normal(0, 1, ROWS),
            "y": rng.normal(0, 1, ROWS),
            "when": [start + timedelta(hours=i) for i in range(ROWS)],
            "cat": [f"c{i % 40:02d}" for i in range(ROWS)],
            "label": [f"L{i % 1500}" for i in range(ROWS)],
            "word": [f"W{i % 1500}" for i in range(ROWS)],
            **{name: rng.normal(0, 1, ROWS) for name in MORE},
        }
    )


@pytest.fixture
def scatter_path(tmp_path: Path, scatter_frame: pl.DataFrame) -> Path:
    """Write `scatter_frame`."""
    path = tmp_path / "cards.parquet"
    scatter_frame.write_parquet(path)
    return path


def add_cards(page: Page, *names: str) -> None:
    """Drop the columns `names` on the filter pane, one after another."""
    columns = page.locator("#columns .column")
    for name in names:
        count = page.locator(".filter-card").count()
        drop_on_filters(
            page, columns.filter(has=page.get_by_text(name, exact=True)), count + 1
        )
        if name in ("label", "word"):
            expect(card(page, name).locator(".filter-mode")).to_be_visible()


def list_of(page: Page, name: str) -> Locator:
    """Return the list of levels (or of candidates) of a card."""
    return card(page, name).locator(".filter-card-body > .filter-levels")


def height(locator: Locator) -> float:
    """Return the height of an element on the page."""
    return locator.evaluate("e => e.getBoundingClientRect().height")


def drag_edge(
    page: Page, name: str, dy: float, *, button: str = "left", check: list | None = None
) -> None:
    """Drag the bottom edge of a card by `dy` px in steps; `check` gets the list's height after each step."""
    handle = card(page, name).locator(".filter-list-resize")
    # Room in the window for the drag: the edge near the top of the pane to go down, near its bottom to go up.
    handle.evaluate(
        "(e, down) => e.scrollIntoView({ block: down ? 'start' : 'end' })", dy > 0
    )
    box = handle.bounding_box()
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down(button=button)
    for i in range(1, 5):
        page.mouse.move(x, y + dy * i / 4)
        if check is not None:
            check.append(height(list_of(page, name)))
    page.mouse.up(button=button)


def api_calls(page: Page) -> list[str]:
    """Collect the `/api/` requests from now on, but the footer's memory, fetched every second."""
    calls: list[str] = []
    page.on(
        "request",
        lambda r: (
            calls.append(r.url)
            if "/api/" in r.url and "/api/memory" not in r.url
            else None
        ),
    )
    return calls


def pane_state(page: Page) -> dict:
    """Return what the filter pane shows of its conditions and its own height."""
    return page.evaluate(
        """() => {
          const pane = document.getElementById("filters");
          return {
            summary: document.querySelector(".filter-summary").textContent,
            classes: pane.className,
            dragged: pane.style.getPropertyValue("--filter-height"),
            checked: [...document.querySelectorAll(".filter-card input:checked")].length,
          };
        }"""
    )


def test_the_bottom_edge_sets_the_height_of_a_list_alone(app_page: Page) -> None:  # noqa: PLR0915
    """A drag of a card's bottom edge makes its list taller or lower as it moves, 40px at least, with no upper bound; the rest of the card, the ticked ones apart and other cards stay; the pane scrolls to what is below; the height stays over folding, maximizing, the left pane and the window, and is gone on a new page; nothing is sent."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1280, "height": 800})
    place(page, "x", "x")
    place(page, "y", "y")
    add_cards(page, "cat", "label", "x")
    cat = list_of(page, "cat")
    label = list_of(page, "label")
    assert abs(height(cat) - 180) <= 1
    expect(card(page, "x").locator(".filter-list-resize")).to_have_count(0)
    handle = card(page, "cat").locator(".filter-list-resize")
    expect(handle).to_have_attribute("title", "ドラッグで一覧の高さを変える")
    assert handle.evaluate("e => getComputedStyle(e).cursor") == "ns-resize"

    # A condition, applied, and a search that shows the ticked one apart.
    label_card = card(page, "label")
    task = drawn_task(page)
    label_card.locator(".filter-card-body > .filter-levels input").first.check()
    new_result(page, task)
    page.wait_for_function(SETTLED)
    search = label_card.locator(".filter-search input")
    search.fill("L14")
    with page.expect_response("**/api/filter-levels?*"):
        search.press("Enter")
    picked = label_card.locator(".filter-picked")
    expect(picked).to_be_visible()
    wait_idle(page)
    calls = api_calls(page)
    state = pane_state(page)

    # A click or the right button change nothing.
    box = handle.bounding_box()
    page.mouse.click(box["x"] + 5, box["y"] + 3)
    drag_edge(page, "cat", 80, button="right")
    assert abs(height(cat) - 180) <= 1
    hidden = cat.evaluate("e => e.scrollHeight - e.clientHeight")

    # Down, taller as it moves: more rows show and less is left to scroll.
    steps: list[float] = []
    drag_edge(page, "cat", 120, check=steps)
    assert [round(s - 180) for s in steps] == [30, 60, 90, 120], steps
    assert cat.evaluate("e => e.scrollHeight - e.clientHeight") < hidden - 100
    # Moves after letting go change nothing; the next drag works.
    page.mouse.move(box["x"] + 5, box["y"] + 300)
    assert abs(height(cat) - 300) <= 1
    drag_edge(page, "cat", -1000 + 700)
    drag_edge(page, "cat", -300)
    assert abs(height(cat) - 40) <= 1
    drag_edge(page, "cat", 60)
    assert abs(height(cat) - 100) <= 1

    # The candidates' list alone; the search, its status, the ticked one apart and the other card stay.
    fixed = label_card.locator(
        ".filter-search, .filter-mode, .filter-card-head, .filter-note"
    )
    before = [height(fixed.nth(i)) for i in range(fixed.count())]
    apart = height(picked.locator(".filter-levels"))
    drag_edge(page, "label", 100)
    assert abs(height(label) - 280) <= 1
    assert [height(fixed.nth(i)) for i in range(fixed.count())] == before
    assert height(picked.locator(".filter-levels")) == apart <= 181
    assert abs(height(cat) - 100) <= 1

    # Taller than the pane: the pane scrolls to the edge, the next card and
    # the bottom of the last card (no drop zone with cards), 8px above its end.
    body = page.locator(".filter-body")
    pane = height(body)
    for _ in range(4):
        drag_edge(page, "label", 300)
    assert height(label) > pane + 600
    body.evaluate("e => (e.scrollTop = e.scrollHeight)")
    expect(page.locator(".filter-drop")).to_be_hidden()
    assert abs(below_last_card(page) - 8) <= 1
    for target in (
        label_card.locator(".filter-list-resize"),
        card(page, "x"),
    ):
        target.scroll_into_view_if_needed()
        expect(target).to_be_in_viewport()
    for _ in range(4):
        drag_edge(page, "label", -300)
    assert abs(height(label) - 280) <= 2
    # The drags sent nothing and changed no condition, tick or height of the pane.
    assert calls == []
    assert pane_state(page) == state

    # Folding, maximizing, the left pane and the window keep the heights.
    heights = [height(cat), height(label)]
    page.locator(".filter-down").click()
    page.locator(".filter-up").click()
    page.locator(".filter-up").click()
    page.locator(".filter-down").click()
    page.locator(".left-close").click()
    page.locator("#left-strip").click()
    left = page.locator(".left-resize").bounding_box()
    page.mouse.move(left["x"] + left["width"] / 2, left["y"] + 200)
    page.mouse.down()
    page.mouse.move(left["x"] + 60, left["y"] + 200, steps=4)
    page.mouse.up()
    page.set_viewport_size({"width": 900, "height": 500})
    page.set_viewport_size({"width": 1280, "height": 800})
    wait_idle(page)
    assert [height(cat), height(label)] == heights
    expect(page.locator(".filter-summary")).to_have_text(state["summary"])

    # A new page starts undragged.
    page.reload()
    place(page, "x", "x")
    place(page, "y", "y")
    add_cards(page, "cat")
    assert abs(height(list_of(page, "cat")) - 180) <= 1
    assert errors == []


def names(page: Page) -> list[str]:
    """Return the names of the cards in the order shown."""
    return page.locator(
        ".filter-list > .filter-card .filter-card-name"
    ).all_inner_texts()


def below_last_card(page: Page) -> float:
    """Return how far the bottom of the pane's body is below the last card, both in the viewport."""
    gap = page.locator(".filter-body").evaluate(
        """(body) => {
          const c = body.querySelector('.filter-list > .filter-card:last-child').getBoundingClientRect();
          const b = body.getBoundingClientRect();
          return b.top < c.bottom && b.bottom <= innerHeight ? b.bottom - c.bottom : null;
        }"""
    )
    assert gap is not None
    return gap


def move_card(
    page: Page,
    name: str,
    to: Locator | None,
    *,
    below: bool = False,
    part: str = ".filter-card-name",
) -> None:
    """Drag a card by `part` of its head to just above `to`'s middle (or just below it), or past the last card into the space below it."""
    grip = card(page, name).locator(part)
    grip.scroll_into_view_if_needed()
    box = grip.bounding_box()
    x = (
        box["x"] + min(box["width"] / 2, 4)
        if part == ".filter-card-head"
        else box["x"] + box["width"] / 2
    )
    y = box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y + 8)
    if to is None:
        # The 8px below the last card (no drop zone with cards).
        last = page.locator(".filter-list > .filter-card").last.bounding_box()
        ty = last["y"] + last["height"] + 4
    else:
        tbox = to.bounding_box()
        ty = tbox["y"] + tbox["height"] / 2 + (2 if below else -2)
    page.mouse.move(x, ty, steps=6)
    expect(page.locator(".filter-card-preview")).to_have_count(1)
    expect(page.locator(".filter-card-line")).to_be_visible()
    page.mouse.up()
    expect(page.locator(".filter-card-preview")).to_have_count(0)


def test_every_kind_of_card_moves_by_its_head(app_page: Page) -> None:  # noqa: PLR0915
    """The numeric, datetime, listed, candidates and 部分一致 cards move up and down to the top, the middle and the end by the name, the icon or the padding; the order only shows: nothing is sent, a commit of the same values sends nothing again, another value is applied; the buttons, the body and the edge keep their own work; the column drop, a list's edge and the pane's edge still work."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1280, "height": 1000})
    place(page, "x", "x")
    place(page, "y", "y")
    add_cards(page, "x", "when", "cat", "label", "word")
    card(page, "word").locator('.filter-mode [data-mode="contains"]').click()
    page.locator("#filters").evaluate("e => (e.style.maxHeight = 'none')")
    drag_edge(page, "cat", -140)
    drag_edge(page, "label", -140)
    # Conditions on two cards.
    task = drawn_task(page)
    card(page, "cat").locator(".filter-level input").first.check()
    new_result(page, task)
    page.wait_for_function(SETTLED)
    word = card(page, "word").locator(".filter-contains input")
    task = drawn_task(page)
    word.fill("W1")
    word.press("Enter")
    new_result(page, task)
    page.wait_for_function(SETTLED)
    wait_idle(page)
    summary = page.locator(".filter-summary")
    expect(summary).to_have_text("（2）cat: 1/40、word: 「W1」を含む")
    calls = api_calls(page)
    assert (
        card(page, "x")
        .locator(".filter-card-head")
        .evaluate("e => getComputedStyle(e).cursor")
        == "grab"
    )

    # Down to the end by the name, from the top.
    move_card(page, "x", None)
    assert names(page) == ["when", "cat", "label", "word", "x"]
    # Up to the top by the icon, from the middle.
    move_card(page, "label", card(page, "when"), part=".column-type")
    assert names(page) == ["label", "when", "cat", "word", "x"]
    # Down into the middle by the padding.
    move_card(page, "when", card(page, "word"), below=True, part=".filter-card-head")
    assert names(page) == ["label", "cat", "word", "when", "x"]
    # Up into the middle, the 部分一致 and the numeric cards.
    move_card(page, "x", card(page, "cat"))
    move_card(page, "word", card(page, "label"))
    order = ["word", "label", "x", "cat", "when"]
    assert names(page) == order
    assert page.evaluate(
        "() => [...document.querySelectorAll('.filter-list > .filter-card')].every((e, i, all) => !i || all[i - 1].getBoundingClientRect().bottom <= e.getBoundingClientRect().top)"
    )
    expect(summary).to_have_text("（2）word: 「W1」を含む、cat: 1/40")
    assert word.input_value() == "W1"
    assert calls == []

    # The same values again send nothing; another value is applied.
    card(page, "x").locator(".filter-reset").click()
    page.wait_for_timeout(500)
    assert calls == []
    task = drawn_task(page)
    card(page, "cat").locator(".filter-level input").nth(1).check()
    new_result(page, task)
    expect(summary).to_have_text("（2）word: 「W1」を含む、cat: 2/40")

    # The buttons, the body and the edge move no card: … opens its menu, × removes.
    for part in (".filter-card-sort", ".filter-level", ".filter-list-resize"):
        box = card(page, "cat").locator(part).first.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 80, steps=4)
        expect(page.locator(".filter-card-preview")).to_have_count(0)
        page.mouse.up()
    wait_idle(page)
    assert names(page) == order
    card(page, "cat").locator(".filter-card-sort").click()
    expect(page.locator(".filter-sort-menu")).to_be_visible()
    page.keyboard.press("Escape")
    task = drawn_task(page)
    card(page, "x").locator(".filter-card-remove").click()
    assert names(page) == ["word", "label", "cat", "when"]

    # The column drop adds at the end; the edges still drag.
    add_cards(page, "k1")
    assert names(page) == ["word", "label", "cat", "when", "k1"]
    before = height(list_of(page, "cat"))
    drag_edge(page, "cat", 30)
    assert abs(height(list_of(page, "cat")) - before - 30) <= 1
    move_card(page, "k1", card(page, "word"))
    assert names(page) == ["k1", "word", "label", "cat", "when"]
    page.locator("#filters").evaluate("e => e.style.removeProperty('max-height')")
    pane = height(page.locator("#filters"))
    drag_filter_edge(page, -60)
    assert abs(height(page.locator("#filters")) - pane - 60) <= 2
    assert errors == []


def test_the_pane_scrolls_at_its_edges_to_a_card_out_of_view(app_page: Page) -> None:  # noqa: PLR0915
    """With more cards than the pane shows, a card held at the bottom edge scrolls the pane to its end and goes last, one held at the top edge scrolls back and goes first; a list's own scroll stays; Escape and letting go outside leave the order, and nothing is sent."""
    page = app_page
    errors = watch_errors(page)
    page.set_viewport_size({"width": 1280, "height": 600})
    place(page, "x", "x")
    place(page, "y", "y")
    add_cards(page, "cat", *MORE)
    body = page.locator(".filter-body")
    assert body.evaluate("e => e.scrollHeight - e.clientHeight") > 300
    cat = list_of(page, "cat")
    cat.evaluate("e => (e.scrollTop = 60)")
    wait_idle(page)
    calls = api_calls(page)
    order = ["cat", *MORE]
    last = card(page, MORE[-1])
    expect(last).not_to_be_in_viewport()

    def hold(name: str, at_bottom: bool) -> None:
        grip = card(page, name).locator(".filter-card-name")
        grip.scroll_into_view_if_needed()
        g = grip.bounding_box()
        b = body.bounding_box()
        x = g["x"] + g["width"] / 2
        page.mouse.move(x, g["y"] + g["height"] / 2)
        page.mouse.down()
        page.mouse.move(x, g["y"] + 20, steps=2)
        y = b["y"] + b["height"] - 8 if at_bottom else b["y"] + 8
        page.mouse.move(x, y, steps=4)
        page.wait_for_function(
            "(down) => { const e = document.querySelector('.filter-body'); return down ? e.scrollTop >= e.scrollHeight - e.clientHeight - 1 : e.scrollTop === 0; }",
            arg=at_bottom,
        )

    body.evaluate("e => (e.scrollTop = 0)")
    hold("cat", True)
    page.keyboard.press("Escape")
    page.mouse.up()
    assert names(page) == order
    expect(page.locator(".filter-card-preview")).to_have_count(0)

    body.evaluate("e => (e.scrollTop = 0)")
    hold("cat", True)
    page.mouse.up()
    order = [*MORE, "cat"]
    assert names(page) == order
    assert cat.evaluate("e => e.scrollTop") == 60

    hold(MORE[-1], False)
    page.mouse.move(1000, 300, steps=3)
    page.mouse.up()
    assert names(page) == order
    hold(MORE[-1], False)
    page.mouse.up()
    assert names(page) == [MORE[-1], *MORE[:-1], "cat"]
    expect(page.locator("#filters")).not_to_have_class(
        re.compile(r"\b(collapsed|maximized)\b")
    )
    assert page.evaluate("() => window.scrollY") == 0
    assert calls == []
    assert errors == []


def test_the_drop_zone_shows_only_without_cards(app_page: Page) -> None:
    """The drop zone shows on a new page, hides once a column is dropped on the pane, stays hidden while the pane still takes another column, and shows again once every card is removed."""
    page = app_page
    errors = watch_errors(page)
    drop = page.locator(".filter-drop")
    expect(drop).to_be_visible()
    expect(drop).to_have_text("Drop a column to filter")
    columns = page.locator("#columns .column")
    drop_on_filters(page, columns.filter(has=page.get_by_text("cat", exact=True)), 1)
    expect(drop).to_be_hidden()
    drop_on_filters(page, columns.filter(has=page.get_by_text("x", exact=True)), 2)
    expect(drop).to_be_hidden()
    for _ in range(2):
        page.locator(".filter-card-remove").first.click()
    expect(page.locator(".filter-card")).to_have_count(0)
    expect(drop).to_be_visible()
    assert errors == []
