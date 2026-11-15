"""JS: a filter card's list of levels takes the height its bottom edge is dragged to, and a card moves by its head (Issue #210)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# A filter pane with the app's styles, in a left pane `height` px high, of
# cards n (numeric), g (40 levels), s (3 levels), id (candidates of 300
# levels, answered at once, or with an error while `window.fail`), t (too
# many levels to search: the text box alone), and more numeric cards named
# in `extra`. `window.changes` counts the calls of `onChange`, `window.errors`
# the page's errors; `window.card(name)` is a card, `window.at(name, sel)`
# the middle of an element of its card on the page, scrolled into view.
CARDS = """async ([height, extra]) => {
  const levels = Array.from({ length: 40 }, (_, i) => [`g${i}`, 40 - i]);
  const universe = Array.from({ length: 300 }, (_, i) => [`v${i + 1}`, i + 1]);
  const numeric = { numeric: true, min: 0, max: 10, nulls: 0, integer: true, temporal: null };
  const summaries = {
    n: numeric,
    g: { numeric: false, levels, n_levels: 40, nulls: 0 },
    s: { numeric: false, levels: [["a", 5], ["b", 3], ["c", 1]], n_levels: 3, nulls: 0 },
    id: { numeric: false, levels: null, n_levels: 300, nulls: 0 },
    t: { numeric: false, levels: null, n_levels: 1000000, nulls: 0 },
  };
  window.requests = [];
  window.fail = false;
  window.fetch = async (url) => {
    const u = new URL(url, location.href);
    window.requests.push(u.pathname);
    const column = u.searchParams.get("column");
    if (u.pathname === "/api/summary") return new Response(JSON.stringify(summaries[column] ?? numeric));
    if (column === "t") return new Response(JSON.stringify({ levels: null, n_levels: 1000000 }));
    if (window.fail) return new Response("broken", { status: 500 });
    const q = u.searchParams.get("q");
    const found = universe.filter(([v]) => v.includes(q));
    return new Response(JSON.stringify({ levels: found.slice(0, 100), truncated: found.length > 100, n_levels: 300 }));
  };
  if (!document.getElementById("css")) {
    const link = document.createElement("link");
    link.id = "css";
    link.rel = "stylesheet";
    link.href = "/static/app.css";
    const loaded = new Promise((r) => (link.onload = r));
    document.head.append(link);
    await loaded;
  }
  document.body.innerHTML = `
    <div id="left" style="display: flex; flex-direction: column; width: 260px; height: ${height}px">
      <div id="columns" style="flex: 1"></div>
      <div id="filters"><div class="filter-head"><span class="filter-summary"></span>
        <button class="filter-up"></button><button class="filter-down"></button></div>
        <div class="filter-resize"></div>
        <div class="filter-body"><div class="filter-list"></div><div class="filter-drop">Drop</div></div>
      </div>
    </div>
    <div id="drop-tip"></div>`;
  const { FilterPane } = await import("/static/js/filters.js");
  window.changes = 0;
  window.errors = [];
  window.addEventListener("error", (e) => window.errors.push(String(e.message)));
  const pane = new FilterPane(document.getElementById("filters"), () => window.changes++, () => {});
  for (const name of ["n", "g", "s", "id", "t", ...extra]) pane.add({ name, numeric: !summaries[name] || name === "n" });
  const ready = () => pane.cards.every((c) => c.summary && (c.name !== "id" || c.candidates) && (c.name !== "t" || c.candidates === false));
  while (!ready()) await new Promise((r) => setTimeout(r, 10));
  window.pane = pane;
  window.card = (name) => pane.cards.find((c) => c.name === name);
  window.names = () => pane.cards.map((c) => c.name);
  window.dom = () => [...document.querySelectorAll(".filter-list > .filter-card .filter-card-name")].map((e) => e.textContent);
  window.at = (name, sel) => {
    const e = sel ? window.card(name).element.querySelector(sel) : window.card(name).element;
    e.scrollIntoView({ block: "nearest" });
    const r = e.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, left: r.left, top: r.top, bottom: r.bottom };
  };
  window.height = (name) => {
    const list = window.card(name).levelList;
    return list && !list.hidden ? list.getBoundingClientRect().height : null;
  };
  window.lastPointer = null;
  window.addEventListener("pointerdown", (e) => (window.lastPointer = e.pointerId), true);
  window.search = (q) => {
    const input = window.card("id").element.querySelector(".filter-search input");
    input.value = q;
    input.dispatchEvent(new Event("input"));
    window.card("id").element.querySelector(".filter-search-go").click();
    return new Promise((r) => setTimeout(r, 30));
  };
  window.moving = () => ({
    preview: document.querySelectorAll(".filter-card-preview").length,
    line: document.querySelectorAll(".filter-card-line").length,
    body: document.body.classList.contains("filter-reordering"),
    marked: document.querySelectorAll(".filter-card.moving").length,
  });
}"""

IDLE = {"preview": 0, "line": 0, "body": False, "marked": 0}
MOVING = {"preview": 1, "line": 1, "body": True, "marked": 1}
HANDLE = ".filter-list-resize"
HEAD = ".filter-card-head"


@pytest.fixture
def page(clock_page: Page) -> Iterator[Page]:
    """Return a page of its own with the pane of `CARDS` in a left pane 600px high."""
    clock_page.evaluate(CARDS, [600, []])
    yield clock_page


def at(page: Page, name: str, sel: str | None = None) -> dict:
    """Return the middle of an element of a card (`window.at`)."""
    return page.evaluate("([n, s]) => window.at(n, s)", [name, sel])


def height(page: Page, name: str) -> float | None:
    """Return the height of a card's list on the page, or None without one shown."""
    return page.evaluate("(n) => window.height(n)", name)


def drag_edge(page: Page, name: str, dy: float, *, button: str = "left") -> None:
    """Drag the bottom edge of a card by `dy` px, in steps."""
    p = at(page, name, HANDLE)
    page.mouse.move(p["x"], p["y"])
    page.mouse.down(button=button)
    page.mouse.move(p["x"], p["y"] + dy, steps=5)
    page.mouse.up(button=button)


def test_only_lists_of_levels_to_tick_get_a_handle(page: Page) -> None:
    """The listed card and the candidates in 水準を選択 have the edge; numbers, the text box and 部分一致 do not; an undragged list is as high as its rows, 180px at most."""
    handles = "() => window.pane.cards.filter((c) => c.element.querySelector('.filter-list-resize')).map((c) => c.name)"
    assert page.evaluate(handles) == ["g", "s", "id"]
    title = page.evaluate(
        "() => window.card('g').element.querySelector('.filter-list-resize').title"
    )
    assert title == "ドラッグで一覧の高さを変える"
    assert abs(height(page, "g") - 180) <= 1
    assert abs(height(page, "id") - 180) <= 1
    assert height(page, "s") < 100
    assert page.evaluate("() => window.card('s').levelList.style.height") == ""
    page.locator('.filter-mode [data-mode="contains"]').click()
    assert page.evaluate(handles) == ["g", "s"]
    assert height(page, "id") is None


def test_the_bottom_edge_drags_the_list_alone(page: Page) -> None:
    """Down makes the list taller as it moves, up lower down to 40px; a click or the right button change nothing; after pointerup or pointercancel moves change nothing and the next drag works; the other lists and the card's other rows stay."""
    start = height(page, "g")
    others = page.evaluate(
        "() => [window.height('s'), window.height('id'), window.card('g').element.querySelector('.filter-note').offsetHeight]"
    )
    p = at(page, "g", HANDLE)
    page.mouse.click(p["x"], p["y"])
    drag_edge(page, "g", 80, button="right")
    assert page.evaluate("() => window.card('g').listHeight") is None
    assert height(page, "g") == start

    p = at(page, "g", HANDLE)
    page.mouse.move(p["x"], p["y"])
    page.mouse.down()
    page.mouse.move(p["x"], p["y"] + 40)
    assert abs(height(page, "g") - (start + 40)) <= 1
    page.mouse.move(p["x"], p["y"] + 100)
    assert abs(height(page, "g") - (start + 100)) <= 1
    page.mouse.up()
    page.mouse.move(p["x"], p["y"] + 200)
    assert abs(height(page, "g") - (start + 100)) <= 1
    rows = page.evaluate("() => window.card('g').levelList.scrollHeight")
    assert rows > start + 100

    drag_edge(page, "g", -1000)
    assert height(page, "g") == 40

    # pointercancel keeps the height shown last.
    p = at(page, "g", HANDLE)
    page.mouse.move(p["x"], p["y"])
    page.mouse.down()
    page.mouse.move(p["x"], p["y"] + 30)
    page.evaluate(
        """() => window.card('g').element.querySelector('.filter-list-resize').dispatchEvent(
          new PointerEvent("pointercancel", { pointerId: window.lastPointer }))"""
    )
    page.mouse.move(p["x"], p["y"] + 90)
    page.mouse.up()
    assert abs(height(page, "g") - 70) <= 1
    drag_edge(page, "g", 20)
    assert abs(height(page, "g") - 90) <= 1
    after = page.evaluate(
        "() => [window.height('s'), window.height('id'), window.card('g').element.querySelector('.filter-note').offsetHeight]"
    )
    assert after == others
    assert page.evaluate("() => [window.changes, window.requests.length]") == [0, 7]
    assert page.evaluate("() => window.errors") == []


def test_the_height_stays_over_searches_redraws_and_modes(page: Page) -> None:
    """A dragged height stays over a search, no candidate, a failure and its retry, the ticked ones apart, 部分一致 and back, another order, a redraw and other cards added and removed; a card removed and added again starts undragged; a restore keeps it, and gives it back to a card it brings back."""
    drag_edge(page, "id", 60)
    h = height(page, "id")
    assert abs(h - 240) <= 1
    page.evaluate("() => window.search('zzz')")
    assert (
        page.evaluate(
            "() => window.card('id').element.querySelector('.filter-candidates-status').textContent"
        )
        == "一致する候補がありません"
    )
    assert height(page, "id") == h
    drag_edge(page, "id", -20)
    h = height(page, "id")
    page.evaluate("() => { window.fail = true; return window.search('v1'); }")
    assert page.evaluate(
        "() => window.card('id').element.querySelector('.filter-error') !== null"
    )
    assert height(page, "id") == h
    page.evaluate(
        "() => { window.fail = false; window.card('id').element.querySelector('.filter-error button').click(); return new Promise((r) => setTimeout(r, 30)); }"
    )
    assert height(page, "id") == h
    page.evaluate("""() => {
      window.card('id').element.querySelector('.filter-card-body > .filter-levels input').click();
      return window.search('v2');
    }""")
    picked = page.evaluate(
        "() => window.card('id').element.querySelector('.filter-picked')"
    )
    assert picked is not None
    assert (
        page.evaluate(
            "() => window.card('id').element.querySelector('.filter-picked').hidden"
        )
        is False
    )
    assert height(page, "id") == h
    page.locator('.filter-mode [data-mode="contains"]').click()
    assert height(page, "id") is None
    page.locator('.filter-mode [data-mode="pick"]').click()
    assert height(page, "id") == h

    drag_edge(page, "g", 50)
    g = height(page, "g")
    page.evaluate("""async () => {
      window.card('g').element.querySelector('.filter-card-sort').click();
      document.querySelector('.filter-sort-menu [data-order="count"]').click();
      window.pane.render();
      window.pane.remove(window.card('s'));
      window.pane.add({ name: 's', numeric: false });
      while (!window.card('s').summary) await new Promise((r) => setTimeout(r, 10));
    }""")
    assert [height(page, "g"), height(page, "id")] == [g, h]

    # A restore: the card kept keeps its new height, the one brought back its own.
    page.evaluate("""async () => {
      const snapshot = window.pane.snapshot();
      window.pane.remove(window.card('g'));
      window.card('id').listHeight = 100;
      window.pane.restore(snapshot);
      await new Promise((r) => setTimeout(r, 30));
    }""")
    assert [height(page, "g"), height(page, "id")] == [g, 100]

    page.evaluate("""async () => {
      window.pane.remove(window.card('g'));
      window.pane.add({ name: 'g', numeric: false });
      while (!window.card('g').summary) await new Promise((r) => setTimeout(r, 10));
    }""")
    assert page.evaluate("() => window.card('g').listHeight") is None
    assert abs(height(page, "g") - 180) <= 1
    assert page.evaluate("() => window.errors") == []


def test_a_redraw_or_a_removal_during_a_drag_leaves_nothing_behind(page: Page) -> None:
    """The card drawn again or removed while its edge is dragged stops following the pointer without an error; the next drag works."""
    p = at(page, "g", HANDLE)
    page.mouse.move(p["x"], p["y"])
    page.mouse.down()
    page.mouse.move(p["x"], p["y"] + 30)
    page.evaluate("() => window.pane.render()")
    page.mouse.move(p["x"], p["y"] + 80)
    page.mouse.up()
    assert abs(height(page, "g") - 210) <= 1
    drag_edge(page, "g", -10)
    assert abs(height(page, "g") - 200) <= 1

    p = at(page, "s", HANDLE)
    page.mouse.move(p["x"], p["y"])
    page.mouse.down()
    page.mouse.move(p["x"], p["y"] + 30)
    page.evaluate("() => window.pane.remove(window.card('s'))")
    page.mouse.move(p["x"], p["y"] + 80)
    page.mouse.up()
    assert page.evaluate("() => window.names()") == ["n", "g", "id", "t"]
    assert page.evaluate("() => window.errors") == []


def test_where_a_moved_card_goes(clock_page: Page) -> None:
    """Above a card's middle is before it, from its middle after it: over cards of other heights, one taller than the pane, one card or none."""
    result = clock_page.evaluate(
        """async () => {
          const { insertionIndex } = await import("/static/js/filters.js");
          const rects = [{ top: 0, height: 100 }, { top: 106, height: 20 }, { top: 132, height: 1000 }];
          return {
            three: [-50, 49, 50, 115, 116, 631, 632, 5000].map((y) => insertionIndex(rects, y)),
            one: [4, 5].map((y) => insertionIndex([{ top: 0, height: 10 }], y)),
            none: insertionIndex([], 10),
          };
        }"""
    )
    assert result == {"three": [0, 0, 1, 1, 2, 2, 3, 3], "one": [0, 1], "none": 0}


def test_the_edges_that_scroll(clock_page: Page) -> None:
    """32px from either edge scroll at 480px a second, up or down; a pane under 64px high has half its height; outside the pane nothing."""
    result = clock_page.evaluate(
        """async () => {
          const { edgeSpeed } = await import("/static/js/filters.js");
          return {
            tall: [99, 100, 131, 132, 368, 369, 400, 401].map((y) => edgeSpeed(100, 400, y)),
            low: [119, 120, 121].map((y) => edgeSpeed(100, 140, y)),
          };
        }"""
    )
    assert result == {
        "tall": [0, -480, -480, 0, 0, 480, 480, 0],
        "low": [-480, 0, 480],
    }


def press_head(page: Page, name: str, where: str = "type") -> dict:
    """Press the head of a card on its type icon, its name or its left padding; return the point pressed."""
    if where == "pad":
        p = at(page, name, HEAD)
        p = {"x": p["left"] + 2, "y": p["y"]}
    else:
        p = at(page, name, ".column-type" if where == "type" else ".filter-card-name")
    page.mouse.move(p["x"], p["y"])
    page.mouse.down()
    return p


def move_to(page: Page, x: float, y: float) -> None:
    """Move the pressed pointer to (x, y) in steps."""
    page.mouse.move(x, y, steps=4)


@pytest.fixture
def tall(clock_page: Page) -> Iterator[Page]:
    """Return the pane of `CARDS` in a left pane 900px high, its lists 40px and the pane as high as its cards: every card in view."""
    clock_page.set_viewport_size({"width": 1280, "height": 1000})
    clock_page.evaluate(CARDS, [900, []])
    clock_page.evaluate(
        """() => {
          document.getElementById("filters").style.maxHeight = "none";
          for (const n of ["g", "s", "id"]) window.card(n).listHeight = 40;
          window.pane.render();
        }"""
    )
    yield clock_page


def test_a_card_moves_by_its_head(tall: Page) -> None:
    """A card pressed on its icon, name or padding moves before, among or after the others, up or down; until let go the order stays and a copy and a line show; then the cards and their elements are in one order and the summary follows it; a short move or the same place changes nothing."""
    page = tall
    order = page.evaluate("() => window.names()")
    assert order == ["n", "g", "s", "id", "t"]
    assert (
        page.evaluate(
            "() => window.card('n').element.querySelector('.filter-card-head').title"
        )
        == "ドラッグでカードの順番を変える"
    )
    assert (
        page.evaluate(
            "() => getComputedStyle(window.card('n').element.querySelector('.filter-card-head')).cursor"
        )
        == "grab"
    )

    # Under 5px: nothing.
    p = press_head(page, "n")
    move_to(page, p["x"], p["y"] + 4)
    assert page.evaluate("() => window.moving()") == IDLE
    page.mouse.up()

    # n down, after s.
    press_head(page, "n", "name")
    s = at(page, "s")
    move_to(page, s["x"], s["y"] + 1)
    assert page.evaluate("() => window.moving()") == MOVING
    assert page.evaluate("() => [window.names(), window.dom()]") == [order, order]
    line = page.evaluate(
        "() => document.querySelector('.filter-card-line').getBoundingClientRect().top"
    )
    assert s["bottom"] <= line + 1 <= at(page, "id")["top"]
    page.mouse.up()
    order = ["g", "s", "n", "id", "t"]
    assert page.evaluate("() => [window.names(), window.dom(), window.moving()]") == [
        order,
        order,
        IDLE,
    ]

    # t up, to the top.
    press_head(page, "t", "pad")
    first = at(page, "g")
    move_to(page, first["x"], first["top"] - 3)
    page.mouse.up()
    order = ["t", "g", "s", "n", "id"]
    assert page.evaluate("() => [window.names(), window.dom()]") == [order, order]

    # g down, past the last card onto the drop zone: the end.
    press_head(page, "g")
    drop = page.evaluate(
        "() => { const r = document.querySelector('.filter-drop').getBoundingClientRect(); return r.top + r.height / 2; }"
    )
    move_to(page, first["x"], drop)
    page.mouse.up()
    order = ["t", "s", "n", "id", "g"]
    assert page.evaluate("() => [window.names(), window.dom()]") == [order, order]

    # s up among them, before n... then back to its own place: nothing.
    press_head(page, "s")
    here = at(page, "s")
    move_to(page, here["x"], here["y"] + 10)
    move_to(page, here["x"], here["y"])
    page.mouse.up()
    assert page.evaluate("() => [window.names(), window.dom()]") == [order, order]
    page.evaluate(
        "() => { window.card('n').range = [2, 8]; window.card('s').levels.add('a'); window.pane.commit(); }"
    )
    summary = page.evaluate(
        "() => document.querySelector('.filter-summary').textContent"
    )
    assert summary.index("s:") < summary.index("n:")
    press_head(page, "n")
    s = at(page, "s")
    move_to(page, s["x"], s["top"] + 1)
    page.mouse.up()
    summary = page.evaluate(
        "() => document.querySelector('.filter-summary').textContent"
    )
    assert summary.index("n:") < summary.index("s:")
    assert page.evaluate("() => [window.changes, window.errors]") == [1, []]


def test_buttons_the_body_and_the_edge_start_no_move(tall: Page) -> None:
    """× and … keep their clicks, the menu closes on a move from another head and Escape cancels both; a press on the body, a level, the search box, the edge or with the right button moves no card."""
    page = tall
    order = page.evaluate("() => window.names()")
    for sel in [
        ".filter-card-sort",
        ".filter-card-remove",
        ".filter-level",
        ".filter-search input",
        HANDLE,
    ]:
        name = "id" if "search" in sel else "g"
        p = at(page, name, sel)
        page.mouse.move(p["x"], p["y"])
        page.mouse.down()
        move_to(page, p["x"], p["y"] + 60)
        assert page.evaluate("() => window.moving()") == IDLE, sel
        page.mouse.up()
    p = at(page, "s", HEAD)
    page.mouse.move(p["x"], p["y"])
    page.mouse.down(button="right")
    move_to(page, p["x"], p["y"] + 60)
    assert page.evaluate("() => window.moving()") == IDLE
    page.mouse.up(button="right")
    assert page.evaluate("() => window.names()") == order

    page.evaluate(
        "() => window.card('g').element.querySelector('.filter-card-sort').click()"
    )
    assert page.locator(".filter-sort-menu").count() == 1
    p = press_head(page, "s")
    move_to(page, p["x"], p["y"] + 20)
    assert page.locator(".filter-sort-menu").count() == 0
    page.keyboard.press("Escape")
    page.mouse.up()
    assert page.evaluate("() => [window.names(), window.moving(), window.errors]") == [
        order,
        IDLE,
        [],
    ]
    page.evaluate(
        "() => window.card('s').element.querySelector('.filter-card-remove').click()"
    )
    assert page.evaluate("() => window.names()") == ["n", "g", "id", "t"]


CANCELS = {
    "escape": "() => {}",
    "outside": "() => {}",
    "pointercancel": """() => window.card('n').element.querySelector('.filter-card-head').dispatchEvent(
      new PointerEvent("pointercancel", { pointerId: window.lastPointer, bubbles: true }))""",
    "add": "() => window.pane.add({ name: 'u', numeric: true })",
    "remove": "() => window.pane.remove(window.card('s'))",
    "redraw": "() => window.pane.renderCard(window.card('g'))",
    "fold": "() => window.pane.setState('collapsed')",
}


@pytest.mark.parametrize("how", list(CANCELS))
def test_a_move_is_cancelled(tall: Page, how: str) -> None:
    """Escape, letting go outside the pane, pointercancel, and a card added, removed or drawn again or the pane folded meanwhile leave the order (with that change), the copy, the line and the scrolling gone; the next move works."""
    page = tall
    p = press_head(page, "n")
    s = at(page, "id")
    move_to(page, s["x"], s["y"] + 1)
    assert page.evaluate("() => window.moving()") == MOVING
    page.evaluate(CANCELS[how])
    if how == "escape":
        page.keyboard.press("Escape")
    if how == "outside":
        move_to(page, 900, s["y"])
    page.mouse.up()
    expected = {
        "add": ["n", "g", "s", "id", "t", "u"],
        "remove": ["n", "g", "id", "t"],
    }.get(how, ["n", "g", "s", "id", "t"])
    assert page.evaluate(
        "() => [window.names(), window.dom(), window.moving(), window.errors]"
    ) == [expected, expected, IDLE, []]
    if how == "fold":
        page.evaluate("() => window.pane.setState('open')")
    # The new card's summary draws the pane again, which would cancel the next move.
    page.wait_for_function("() => window.pane.cards.every((c) => c.summary)")
    p = press_head(page, "n")
    drop = page.evaluate(
        "() => { const r = document.querySelector('.filter-drop').getBoundingClientRect(); return r.top + r.height / 2; }"
    )
    move_to(page, p["x"], drop)
    page.mouse.up()
    assert page.evaluate("() => window.names()") == [*expected[1:], "n"]


def test_the_pane_scrolls_at_its_edges_while_a_card_moves(clock_page: Page) -> None:
    """Held still near the bottom edge the pane scrolls down at 480px a second up to its end, near the top up, elsewhere or outside not at all; a list's own scroll and the page stay; the card goes to the end it could not see; after the move nothing scrolls."""
    page = clock_page
    page.evaluate(CARDS, [420, ["m1", "m2", "m3", "m4"]])
    page.evaluate("() => { window.card('g').levelList.scrollTop = 50; }")
    body = page.evaluate(
        "() => { const r = document.querySelector('.filter-body').getBoundingClientRect(); return { top: r.top, bottom: r.bottom, x: r.left + r.width / 2, right: r.right }; }"
    )
    scroll = "() => document.querySelector('.filter-body').scrollTop"
    most = page.evaluate(
        "() => { const b = document.querySelector('.filter-body'); return b.scrollHeight - b.clientHeight; }"
    )
    assert most > 500
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    press_head(page, "n")
    move_to(page, body["x"], body["bottom"] - 10)
    start = page.evaluate(scroll)
    page.clock.run_for(500)
    first = page.evaluate(scroll)
    assert 200 <= first - start <= 260, (start, first)
    page.clock.run_for(500)
    assert 450 <= page.evaluate(scroll) - start <= 500
    page.clock.run_for(10_000)
    assert abs(page.evaluate(scroll) - most) <= 1

    # In the middle, and outside, nothing scrolls.
    move_to(page, body["x"], (body["top"] + body["bottom"]) / 2)
    page.clock.run_for(500)
    assert abs(page.evaluate(scroll) - most) <= 1
    move_to(page, body["right"] + 40, body["bottom"] - 10)
    page.clock.run_for(500)
    assert abs(page.evaluate(scroll) - most) <= 1

    # Up near the top edge.
    move_to(page, body["x"], body["top"] + 10)
    page.clock.run_for(250)
    up = page.evaluate(scroll)
    assert 90 <= most - up <= 130
    page.clock.run_for(10_000)
    assert page.evaluate(scroll) == 0
    page.clock.run_for(10_000)
    move_to(page, body["x"], body["bottom"] - 10)
    page.clock.run_for(10_000)
    page.mouse.up()
    assert page.evaluate("() => window.names().at(-1)") == "n"
    assert page.evaluate(
        "() => [window.card('g').levelList.scrollTop, window.scrollY, window.moving()]"
    ) == [50, 0, IDLE]
    page.evaluate("() => { document.querySelector('.filter-body').scrollTop = 100; }")
    page.clock.run_for(1000)
    assert page.evaluate(scroll) == 100
    assert page.evaluate("() => [window.changes, window.errors]") == [0, []]


def test_a_move_keeps_what_every_card_holds(clock_page: Page) -> None:
    """Moved, every card keeps its range, ticks, text, query typed but not sent, order of levels, mode and height; the summary takes the new order, the conditions stay in the order of their columns and nothing is sent again, a tick waiting is still sent; redraws keep the order, a new card goes last, a known one changes nothing, and a restore goes back to the order of its snapshot with the heights kept."""
    page = clock_page
    page.evaluate(CARDS, [600, []])
    result = page.evaluate(
        """async () => {
          const pane = window.pane;
          const card = window.card;
          card('n').range = [2, 8];
          card('g').levels.add('g1');
          card('g').order = 'count';
          card('t').contains = 'x';
          card('g').listHeight = 60;
          card('id').listHeight = 70;
          pane.render();
          card('id').element.querySelector('.filter-card-body > .filter-levels input').click();
          pane.commit();
          const typed = card('id').element.querySelector('.filter-search input');
          typed.value = 'v4';
          typed.dispatchEvent(new Event('input'));
          const snapshot = pane.snapshot();
          const sent = window.changes;
          const state = () => pane.cards.map((c) => ({
            name: c.name,
            range: c.range,
            levels: [...c.levels],
            contains: c.contains,
            draft: c.draft,
            order: c.order,
            mode: c.mode,
            height: c.listHeight,
            shown: window.height(c.name),
            boxes: [...c.element.querySelectorAll('input')].map((i) => (i.type === 'checkbox' ? i.checked : i.value)),
          })).sort((a, b) => (a.name < b.name ? -1 : 1));
          const before = state();
          const elements = pane.cards.map((c) => c.element);
          const conditions = JSON.stringify(pane.conditions());
          // s ticked, waiting to be sent.
          card('s').element.querySelector('.filter-level input').click();
          pane.moveCard(card('t'), 0);
          pane.moveCard(card('n'), 4);
          const names = window.names();
          const summary = document.querySelector('.filter-summary').textContent;
          const after = state();
          const kept = elements.every((e) => pane.cards.some((c) => c.element === e));
          const afterConditions = conditions === JSON.stringify(pane.conditions().filter((c) => c.column !== 's'));
          await new Promise((r) => setTimeout(r, 500));
          const tickSent = window.changes - sent;
          pane.commit();
          const again = window.changes - sent;
          pane.render();
          pane.setState('collapsed');
          pane.setState('maximized');
          const redrawn = window.names();
          pane.add({ name: 'g', numeric: false });
          pane.add({ name: 'u', numeric: true });
          const added = window.names();
          pane.restore(snapshot);
          return {
            names, summary, kept, afterConditions, tickSent, again, redrawn, added,
            same: JSON.stringify(before) === JSON.stringify(after.map((c) => (c.name === 's' ? before.find((b) => b.name === 's') : c))),
            restored: window.names(),
            heights: [window.height('g'), window.height('id')],
            sortedConditions: pane.conditions().map((c) => c.column),
            errors: window.errors,
          };
        }"""
    )
    assert result["names"] == ["t", "g", "s", "id", "n"]
    assert [result["summary"].index(f"{n}:") for n in ("t", "g", "id", "n")] == sorted(
        result["summary"].index(f"{n}:") for n in ("t", "g", "id", "n")
    )
    assert result["kept"] and result["same"] and result["afterConditions"]
    assert [result["tickSent"], result["again"]] == [1, 1]
    assert result["redrawn"] == result["names"]
    assert result["added"] == [*result["names"], "u"]
    assert result["restored"] == ["n", "g", "s", "id", "t"]
    assert result["heights"] == [60, 70]
    assert result["sortedConditions"] == sorted(result["sortedConditions"])
    assert result["errors"] == []
