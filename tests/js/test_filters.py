"""JS: filters.js writes the numbers of a filter card short and sorts its levels."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.js.test_keys import press_conversion_enters, press_plain_enter

pytestmark = pytest.mark.js


def test_huge_numbers_stay_short(js_page: Page) -> None:
    """Integers of 16 digits or more and 1e300 take 4 significant digits, as fractions do; smaller integers are whole with separators."""
    cases = {
        1e300: "1.000e+300",
        -1e300: "-1.000e+300",
        2e299: "2.000e+299",
        1e15: "1.000e+15",
        999999999999999: "999,999,999,999,999",
        1234: "1,234",
        0.123456: "0.1235",
        -2.5: "-2.5",
    }
    result = js_page.evaluate(
        """async (values) => {
          const { formatNumber } = await import("/static/js/filters.js");
          return values.map(formatNumber);
        }""",
        list(cases),
    )
    assert result == list(cases.values())


def _sort(page: Page, levels: list, *orders: str) -> list:
    """Return the levels after sorting them by each of `orders` in turn."""
    return page.evaluate(
        """async ([levels, orders]) => {
          const { sortLevels } = await import("/static/js/filters.js");
          let out = levels;
          for (const order of orders) out = sortLevels(out, order);
          return out;
        }""",
        [levels, list(orders)],
    )


def test_name_keeps_the_order_of_the_summary(js_page: Page) -> None:
    """Name leaves the levels in the natural order the summary gives."""
    levels = [["ID2", 1], ["ID10", 7], ["a", 3], [None, 9]]
    assert _sort(js_page, levels, "name") == levels


def test_count_puts_the_most_rows_first_and_ties_by_name(js_page: Page) -> None:
    """Count sorts by count, descending; equal counts keep the order of Name."""
    levels = [["ID2", 5], ["ID10", 5], ["a", 9]]
    assert [level for level, _ in _sort(js_page, levels, "count")] == [
        "a",
        "ID2",
        "ID10",
    ]


def test_picking_the_same_order_again_changes_nothing(js_page: Page) -> None:
    """Sorting twice by the same order gives the same list as once."""
    levels = [["ID2", 5], ["ID10", 5], ["a", 9], ["b", 1]]
    for order in ("name", "count"):
        assert _sort(js_page, levels, order, order) == _sort(js_page, levels, order)


# A filter pane of three cards: a numeric one (n), one of levels (g) and one
# of text (id), whose summaries come from a stub of `fetch`. `onChange`
# counts its calls in `window.changes`.
PANE = """async () => {
  const summaries = {
    n: { numeric: true, min: 0, max: 10, nulls: 0, integer: true, temporal: null },
    g: { numeric: false, levels: [["a", 5], ["b", 3], ["c", 1]], n_levels: 3, nulls: 0 },
    id: { numeric: false, levels: null, n_levels: 5000, nulls: 0 },
  };
  window.fetch = async (url) => {
    const column = new URL(url, location.href).searchParams.get("column");
    return new Response(JSON.stringify(summaries[column]));
  };
  document.body.innerHTML = `
    <div id="filters"><div class="filter-head"><span class="filter-summary"></span>
    <button class="filter-up"></button><button class="filter-down"></button></div>
    <div class="filter-resize"></div><div class="filter-list"></div></div>
    <div id="drop-tip"></div>`;
  const { FilterPane, RestorePoint } = await import("/static/js/filters.js");
  window.changes = 0;
  window.summary = "";
  const pane = new FilterPane(
    document.getElementById("filters"),
    () => window.changes++,
    (count, text) => (window.summary = text),
  );
  for (const [name, numeric] of [["n", true], ["g", false], ["id", false]]) pane.add({ name, numeric });
  while (pane.cards.some((c) => !c.summary)) await new Promise((r) => setTimeout(r, 10));
  window.pane = pane;
  window.RestorePoint = RestorePoint;
}"""


def test_restore_puts_back_the_conditions_without_sending(clock_page: Page) -> None:
    """After ticks, a range, a text and a removed card, `restore` gives back the conditions and the cards of the snapshot, sends nothing and stops the ticks waiting."""
    page = clock_page
    page.evaluate(PANE)
    result = page.evaluate(
        """async () => {
          const pane = window.pane;
          const [n, g, id] = pane.cards;
          g.levels.add("a");
          n.range = [2, 8];
          id.contains = "x1";
          pane.commit();
          const before = { conditions: pane.conditions(), names: pane.cards.map((c) => c.name) };
          const snapshot = pane.snapshot();
          const sent = window.changes;
          g.order = "count";
          g.levels.add("b");
          n.range = [3, 4];
          id.contains = "zz";
          pane.remove(n);
          // A tick waiting to be sent.
          g.levels.add("c");
          pane.commitSoon();
          pane.restore(snapshot);
          await new Promise((r) => setTimeout(r, 600));
          return {
            before,
            conditions: pane.conditions(),
            names: pane.cards.map((c) => c.name),
            changes: window.changes - sent,
            order: g.order,
            summary: window.summary,
            checked: [...pane.root.querySelectorAll(".filter-level input")].map((b) => b.checked),
          };
        }"""
    )
    assert result["conditions"] == result["before"]["conditions"]
    assert result["names"] == result["before"]["names"] == ["n", "g", "id"]
    # The removal and the later commit were sent; the restore and the waiting tick were not.
    assert result["changes"] == 1
    # What only shows stays as it is.
    assert result["order"] == "count"
    assert result["summary"] == "n: 2〜8、g: 1/3、id: 「x1」を含む"
    assert result["checked"] == [True, False, False]


def test_restore_drops_a_card_added_since_and_keeps_sending_after(
    clock_page: Page,
) -> None:
    """A card added after the snapshot goes; a change after the restore is sent, and the restored conditions are not sent again."""
    page = clock_page
    page.evaluate(PANE)
    result = page.evaluate(
        """async () => {
          const pane = window.pane;
          const id = pane.cards[2];
          pane.remove(id);
          const snapshot = pane.snapshot();
          pane.add({ name: "id", numeric: false });
          while (!pane.cards[2].summary) await new Promise((r) => setTimeout(r, 10));
          pane.restore(snapshot);
          const names = pane.cards.map((c) => c.name);
          const sent = window.changes;
          pane.commit();
          const same = window.changes - sent;
          pane.cards[1].levels.add("b");
          pane.commit();
          return { names, same, after: window.changes - sent };
        }"""
    )
    assert result == {"names": ["n", "g"], "same": 0, "after": 1}


def test_the_restore_point_is_the_latest_confirmed(js_page: Page) -> None:
    """A failure before a candidate is confirmed gets the previous point; an older candidate confirmed late does not replace a newer one."""
    result = js_page.evaluate(
        """async () => {
          const { RestorePoint } = await import("/static/js/filters.js");
          const point = new RestorePoint("start");
          const first = point.propose("one");
          const second = point.propose("two");
          const out = [point.point()];
          point.confirm(second);
          out.push(point.point());
          point.confirm(first);
          out.push(point.point());
          const third = point.propose("three");
          out.push(point.point());
          point.confirm(third);
          out.push(point.point());
          return out;
        }"""
    )
    assert result == ["start", "two", "two", "two", "three"]


def test_a_card_without_a_condition_goes_to_the_state_sent(clock_page: Page) -> None:
    """Adding or removing a card that sets no condition sends nothing, but the state sent has it or not, so that a restore to it keeps the cards of the request."""
    page = clock_page
    page.evaluate(PANE)
    result = page.evaluate(
        """async () => {
          const pane = window.pane;
          const sent = window.changes;
          const id = pane.cards[2];
          pane.remove(id);
          const removed = pane.sent.map((s) => s.card.name);
          pane.add({ name: "id", numeric: false });
          const added = pane.sent.map((s) => s.card.name);
          while (!pane.cards[2].summary) await new Promise((r) => setTimeout(r, 10));
          const point = pane.sent;
          pane.cards[1].levels.add("a");
          pane.commit();
          pane.restore(point);
          return {
            removed,
            added,
            names: pane.cards.map((c) => c.name),
            conditions: pane.conditions(),
            changes: window.changes - sent,
          };
        }"""
    )
    assert result == {
        "removed": ["n", "g"],
        "added": ["n", "g", "id"],
        "names": ["n", "g", "id"],
        "conditions": [],
        "changes": 1,
    }


# A filter pane of one card of candidates (id: 300 levels v1 to v300, v<i>
# with i rows), whose summary comes from a stub of `fetch` at once, and whose
# searches wait in `window.requests` until a test answers them
# (`window.answer(i)` with the levels the server would find, or a body and a
# status). `onChange` keeps the conditions sent in `window.sent`.
CANDIDATES = """async () => {
  const universe = Array.from({ length: 300 }, (_, i) => [`v${i + 1}`, i + 1]);
  window.find = (q, order) => {
    const words = q.toLowerCase().split(/\\s+/).filter(Boolean);
    let found = universe.filter(([v]) => words.every((w) => v.toLowerCase().includes(w)));
    if (order === "count") found = [...found].sort((a, b) => b[1] - a[1]);
    return { levels: found.slice(0, 100), truncated: found.length > 100, n_levels: 300 };
  };
  window.requests = [];
  window.fetch = (url) => {
    const u = new URL(url, location.href);
    if (u.pathname === "/api/summary") {
      return Promise.resolve(new Response(JSON.stringify(
        { numeric: false, levels: null, n_levels: 310, nulls: 4, rows: 45154 })));
    }
    return new Promise((resolve) =>
      window.requests.push({ params: Object.fromEntries(u.searchParams), resolve }));
  };
  window.answer = (i, body, status = 200) => {
    const { params, resolve } = window.requests[i];
    resolve(new Response(JSON.stringify(body ?? window.find(params.q, params.order)), { status }));
    return new Promise((r) => setTimeout(r, 20));
  };
  document.body.innerHTML = `
    <div id="filters"><div class="filter-head"><span class="filter-summary"></span>
    <button class="filter-up"></button><button class="filter-down"></button></div>
    <div class="filter-resize"></div><div class="filter-list"></div></div>
    <div id="drop-tip"></div>`;
  const { FilterPane } = await import("/static/js/filters.js");
  window.sent = [];
  const pane = new FilterPane(
    document.getElementById("filters"),
    (conditions) => window.sent.push(conditions),
    () => {},
  );
  pane.add({ name: "id", numeric: false });
  while (!window.requests.length) await new Promise((r) => setTimeout(r, 10));
  window.pane = pane;
  window.card = pane.cards[0];
  // What the card shows.
  window.view = () => {
    const root = window.card.element;
    const rows = (sel) => [...root.querySelectorAll(sel)].map((l) => ({
      name: l.querySelector(".filter-level-name").textContent,
      checked: l.querySelector("input").checked,
    }));
    const shown = (sel) => {
      const e = root.querySelector(sel);
      return e && !e.hidden ? e.textContent : null;
    };
    return {
      listed: rows(".filter-card-body > .filter-levels .filter-level:not(.filter-null)"),
      nulls: rows(".filter-card-body > .filter-levels .filter-null"),
      picked: rows(".filter-picked .filter-level"),
      status: shown(".filter-candidates-status"),
      more: shown(".filter-truncated"),
      search: !!root.querySelector(".filter-search"),
      contains: !!root.querySelector(".filter-contains"),
      modes: [...root.querySelectorAll(".filter-mode button")].map((b) => b.textContent),
      sort: !!root.querySelector(".filter-card-sort"),
      body: root.querySelector(".filter-card-body").textContent,
    };
  };
  // Ticks or unticks a level the card shows.
  window.tick = (name) => {
    const row = [...window.card.element.querySelectorAll(".filter-level")].find(
      (l) => l.querySelector(".filter-level-name").textContent === name);
    row.querySelector("input").click();
  };
  window.search = (q) => {
    const input = window.card.element.querySelector(".filter-search input");
    input.value = q;
    input.dispatchEvent(new Event("input"));
    window.card.element.querySelector(".filter-search-go").click();
  };
  window.sortBy = (order) => {
    window.card.element.querySelector(".filter-card-sort").click();
    document.querySelector(`.filter-sort-menu [data-order="${order}"]`).click();
  };
}"""


def _candidates(page: Page) -> None:
    """Open the pane of one card of candidates, its first search waiting."""
    page.evaluate(CANDIDATES)


def test_the_first_search_shows_the_candidates(js_page: Page) -> None:
    """Until the first answer the card tells it counts; then the first 100 by name, the note of the limit, the modes and Sort by."""
    page = js_page
    _candidates(page)
    assert page.evaluate("() => window.view().body") == "候補を集計中…"
    page.evaluate("() => window.answer(0)")
    view = page.evaluate("() => window.view()")
    assert len(view["listed"]) == 100
    assert view["listed"][0] == {"name": "v1", "checked": False}
    assert view["more"] == "先頭100件を表示しています。検索語を絞ってください"
    assert view["status"] is None
    assert view["modes"] == ["水準を選択", "部分一致"]
    assert view["sort"]
    params = page.evaluate("() => window.requests.map((r) => r.params)")
    assert params == [{"column": "id", "q": "", "order": "name"}]


def test_the_ticks_stay_over_searches_and_orders(js_page: Page) -> None:
    """Ticks stay over another query and another order; one the candidates do not list shows apart, ticked; neither sends a condition."""
    page = js_page
    _candidates(page)
    result = page.evaluate(
        """async () => {
          await window.answer(0);
          window.tick("v5");
          window.tick("v7");
          window.pane.commit();
          const before = window.sent.length;
          window.search("v7");
          await window.answer(1);
          const searched = window.view();
          window.sortBy("count");
          await window.answer(2);
          const sorted = window.view();
          await new Promise((r) => setTimeout(r, 500));
          return {
            searched, sorted,
            params: window.requests.map((r) => r.params),
            sent: window.sent.length - before,
            conditions: window.pane.conditions(),
          };
        }"""
    )
    searched = result["searched"]
    assert searched["listed"][0] == {"name": "v7", "checked": True}
    assert [r["name"] for r in searched["listed"]] == [
        "v7",
        *[f"v7{i}" for i in range(10)],
    ]
    assert searched["picked"] == [{"name": "v5", "checked": True}]
    assert searched["more"] is None
    sorted_ = result["sorted"]
    assert [r["name"] for r in sorted_["listed"]][:2] == ["v79", "v78"]
    assert {"name": "v7", "checked": True} in sorted_["listed"]
    assert result["params"][1:] == [
        {"column": "id", "q": "v7", "order": "name"},
        {"column": "id", "q": "v7", "order": "count"},
    ]
    assert result["sent"] == 0
    assert result["conditions"] == [{"column": "id", "levels": ["v5", "v7"]}]


def test_a_ticked_level_apart_is_unticked_and_all_are_cleared(js_page: Page) -> None:
    """A level apart from the candidates unticks there; "すべて外す" clears those apart too."""
    page = js_page
    _candidates(page)
    result = page.evaluate(
        """async () => {
          await window.answer(0);
          window.tick("v1");
          window.tick("v2");
          window.tick("v3");
          window.search("v3");
          await window.answer(1);
          const apart = window.view().picked.map((r) => r.name);
          window.card.element.querySelector(".filter-picked input").click();
          const after = window.view().picked.map((r) => r.name);
          await new Promise((r) => setTimeout(r, 500));
          const committed = window.sent.at(-1);
          window.card.element.querySelector(".filter-note .filter-reset").click();
          return {
            apart, after, committed,
            cleared: window.sent.at(-1),
            view: window.view(),
            levels: [...window.card.levels],
          };
        }"""
    )
    assert result["apart"] == ["v1", "v2"]
    assert result["after"] == ["v2"]
    assert result["committed"] == [{"column": "id", "levels": ["v2", "v3"]}]
    assert result["cleared"] == []
    assert result["levels"] == []
    assert result["view"]["picked"] == []
    assert not any(r["checked"] for r in result["view"]["listed"])


def test_older_answers_and_those_of_a_removed_card_are_dropped(js_page: Page) -> None:
    """An answer to an older request of the card, and one to a card removed since, change nothing."""
    page = js_page
    _candidates(page)
    result = page.evaluate(
        """async () => {
          await window.answer(0);
          window.search("v1");
          window.search("v2");
          await window.answer(2);
          await window.answer(1);
          const latest = window.view().listed[0].name;
          window.search("v3");
          const card = window.card;
          window.pane.remove(card);
          await window.answer(3);
          return { latest, shown: card.shown, loading: card.loading };
        }"""
    )
    assert result["latest"] == "v2"
    assert result["shown"] == {"query": "v2", "order": "name"}
    assert result["loading"] is True


def test_a_column_with_too_many_levels_gets_the_text_box_alone(js_page: Page) -> None:
    """An answer without levels leaves the text box, with the server's count, and no modes or Sort by."""
    page = js_page
    _candidates(page)
    page.evaluate(
        "() => window.answer(0, { levels: null, truncated: false, n_levels: 3000000 })"
    )
    view = page.evaluate("() => window.view()")
    assert view["contains"]
    assert not view["search"]
    assert view["modes"] == []
    assert not view["sort"]
    assert view["body"].startswith(
        "水準が多すぎる（約 3,000,000 個）ため、部分一致で絞る"
    )


def test_a_failure_shows_the_error_and_retries_with_the_same_search(
    js_page: Page,
) -> None:
    """A failed search shows its error and a retry, keeps the ticks, and the retry asks the same query and order."""
    page = js_page
    _candidates(page)
    result = page.evaluate(
        """async () => {
          await window.answer(0);
          window.tick("v4");
          window.sortBy("count");
          await window.answer(1);
          window.search("v4");
          await window.answer(2, { detail: "worker failed" }, 500);
          const failed = window.view();
          window.card.element.querySelector(".filter-error button").click();
          const retried = window.requests[3].params;
          await window.answer(3);
          return { failed, retried, after: window.view(), levels: [...window.card.levels] };
        }"""
    )
    assert result["failed"]["status"] == "エラー: worker failed再試行"
    assert result["failed"]["picked"] == [{"name": "v4", "checked": True}]
    assert result["retried"] == {"column": "id", "q": "v4", "order": "count"}
    assert result["after"]["status"] is None
    assert result["levels"] == ["v4"]


def test_a_failed_first_search_retries(js_page: Page) -> None:
    """A failed first search shows its error and a retry instead of the candidates."""
    page = js_page
    _candidates(page)
    page.evaluate("() => window.answer(0, { detail: 'boom' }, 500)")
    assert page.evaluate("() => window.view().body") == "エラー: boom再試行"
    page.evaluate(
        "() => window.card.element.querySelector('.filter-error button').click()"
    )
    page.evaluate("() => window.answer(1)")
    assert len(page.evaluate("() => window.view().listed")) == 100


def test_the_modes_keep_their_own_state(js_page: Page) -> None:
    """Each mode keeps its state: back to the levels, the ticks, query and order come back, and only the mode shown sets the condition."""
    page = js_page
    _candidates(page)
    result = page.evaluate(
        """async () => {
          await window.answer(0);
          window.tick("v9");
          window.search("v9");
          await window.answer(1);
          window.sortBy("count");
          await window.answer(2);
          window.pane.commit();
          const mode = (m) => window.card.element.querySelector(`.filter-mode [data-mode="${m}"]`).click();
          mode("contains");
          const text = window.view();
          const box = window.card.element.querySelector(".filter-contains input");
          box.value = "v1 0";
          box.dispatchEvent(new Event("change"));
          const contains = window.sent.at(-1);
          mode("pick");
          const back = window.view();
          const picked = window.sent.at(-1);
          mode("contains");
          const again = window.card.element.querySelector(".filter-contains input").value;
          const summary = window.pane.summaryText();
          mode("pick");
          return {
            text, contains, back, picked, again, summary,
            input: window.card.element.querySelector(".filter-search input").value,
            requests: window.requests.length,
          };
        }"""
    )
    assert not result["text"]["search"]
    assert not result["text"]["sort"]
    assert result["contains"] == [{"column": "id", "contains": "v1 0"}]
    assert result["back"]["listed"][0] == {"name": "v99", "checked": False}
    assert {"name": "v9", "checked": True} in result["back"]["listed"]
    assert result["back"]["sort"]
    assert result["input"] == "v9"
    assert result["picked"] == [{"column": "id", "levels": ["v9"]}]
    assert result["again"] == "v1 0"
    assert result["summary"] == "id: 「v1 0」を含む"
    # Switching shows what was fetched: no search is sent.
    assert result["requests"] == 3


def test_enter_searches_unless_it_commits_a_conversion(js_page: Page) -> None:
    """Enter in the search box searches; the Enter of an IME conversion, typing and leaving do not."""
    page = js_page
    _candidates(page)
    result = page.evaluate(
        """async () => {
          await window.answer(0);
          const input = window.card.element.querySelector(".filter-search input");
          input.value = "v2";
          input.dispatchEvent(new Event("input"));
          input.dispatchEvent(new Event("change"));
          input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true }));
          input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229 }));
          const typed = window.requests.length;
          input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
          return { typed, after: window.requests.length, q: window.requests.at(-1).params.q };
        }"""
    )
    assert result == {"typed": 1, "after": 2, "q": "v2"}


def test_restore_gives_back_the_mode_ticks_query_and_order(js_page: Page) -> None:
    """`restore` puts back a card of candidates' mode, ticks, query and order, and fetches the candidates of that query and order again."""
    page = js_page
    _candidates(page)
    result = page.evaluate(
        """async () => {
          await window.answer(0);
          window.tick("v3");
          window.pane.commit();
          const snapshot = window.pane.snapshot();
          window.tick("v4");
          window.search("v4");
          await window.answer(1);
          window.sortBy("count");
          await window.answer(2);
          window.card.element.querySelector('.filter-mode [data-mode="contains"]').click();
          window.pane.restore(snapshot);
          const asked = window.requests.at(-1).params;
          await window.answer(3);
          return {
            asked,
            mode: window.card.mode,
            levels: [...window.card.levels],
            conditions: window.pane.conditions(),
            first: window.view().listed[0],
            input: window.card.element.querySelector(".filter-search input").value,
          };
        }"""
    )
    assert result["asked"] == {"column": "id", "q": "", "order": "name"}
    assert result["mode"] == "pick"
    assert result["levels"] == ["v3"]
    assert result["conditions"] == [{"column": "id", "levels": ["v3"]}]
    assert result["first"] == {"name": "v1", "checked": False}
    assert result["input"] == ""


def test_filters_key_follows_the_conditions(js_page: Page) -> None:
    """Conditions of the same values have one key in any order of the cards; another range, levels or contains gives another."""
    result = js_page.evaluate(
        """async () => {
          const { filtersKey } = await import("/static/js/filters.js");
          const list = [
            { column: "a", range: [0, 1] },
            { column: "b", levels: ["p"] },
            { column: "c", contains: "x" },
          ];
          const copy = list.map((f) => ({ ...f }));
          const changed = [
            [{ ...list[0], range: [0, 2] }, list[1], list[2]],
            [list[0], { ...list[1], levels: ["p", "q"] }, list[2]],
            [list[0], list[1], { ...list[2], contains: "y" }],
          ];
          return {
            same: filtersKey(list) === filtersKey(copy),
            reordered: filtersKey(list) === filtersKey([list[2], list[0], list[1]]),
            changed: changed.map((other) => filtersKey(list) !== filtersKey(other)),
          };
        }"""
    )
    assert result == {"same": True, "reordered": True, "changed": [True, True, True]}


def test_card_kind_tells_how_a_card_sets_its_condition(js_page: Page) -> None:
    """A card is null before its summary, else range, pick, contains or listed, in that order."""
    kinds = js_page.evaluate(
        """async () => {
          const { cardKind } = await import("/static/js/filters.js");
          const text = { numeric: false, levels: null, n_levels: 5000, nulls: 0 };
          const found = { levels: [["a", 1]], n_levels: 5000, truncated: false };
          return [
            { numeric: false, summary: null, candidates: null, mode: "pick" },
            { numeric: true, summary: { numeric: true, min: 0, max: 1 }, candidates: null, mode: "pick" },
            { numeric: false, summary: text, candidates: found, mode: "pick" },
            { numeric: false, summary: text, candidates: found, mode: "contains" },
            { numeric: false, summary: text, candidates: false, mode: "contains" },
            { numeric: false, summary: { numeric: false, levels: [["a", 1]] }, candidates: null, mode: "pick" },
          ].map(cardKind);
        }"""
    )
    assert kinds == [None, "range", "pick", "contains", "contains", "listed"]


# A filter pane of the four kinds of cards: numeric (n), listed levels (g),
# picked candidates (id) and the text contained (t), each setting a condition.
FOUR_KINDS = """async () => {
  const summaries = {
    n: { numeric: true, min: 0, max: 10, nulls: 0, integer: true, temporal: null },
    g: { numeric: false, levels: [["a", 5], ["b", 3], ["c", 1]], n_levels: 3, nulls: 0 },
    id: { numeric: false, levels: null, n_levels: 5000, nulls: 0 },
    t: { numeric: false, levels: null, n_levels: 90000, nulls: 0 },
  };
  const candidates = {
    id: { levels: [["v1", 2], ["v2", 1]], n_levels: 5000, truncated: false },
    t: { levels: null, n_levels: 90000 },
  };
  window.fetch = async (url) => {
    const u = new URL(url, location.href);
    const column = u.searchParams.get("column");
    const body = u.pathname === "/api/summary" ? summaries[column] : candidates[column];
    return new Response(JSON.stringify(body));
  };
  document.body.innerHTML = `
    <div id="filters"><div class="filter-head"><span class="filter-summary"></span>
    <button class="filter-up"></button><button class="filter-down"></button></div>
    <div class="filter-resize"></div><div class="filter-list"></div></div>
    <div id="drop-tip"></div>`;
  const { FilterPane } = await import("/static/js/filters.js");
  const pane = new FilterPane(document.getElementById("filters"), () => {}, () => {});
  for (const [name, numeric] of [["n", true], ["g", false], ["id", false], ["t", false]]) pane.add({ name, numeric });
  const ready = () => pane.cards.every((c) => c.summary && (c.summary.levels !== null || c.candidates !== null));
  while (!ready()) await new Promise((r) => setTimeout(r, 10));
  const [n, g, id, t] = pane.cards;
  n.range = [2, 7];
  g.levels = new Set(["b", "a"]);
  id.levels = new Set(["v2", "v1"]);
  t.contains = "ab";
  return { conditions: pane.conditions(), summary: pane.summaryText() };
}"""


def test_the_four_kinds_of_cards_give_their_conditions_and_summary(
    js_page: Page,
) -> None:
    """Each kind of card sends its own condition, in the order of the columns, and says it in its own words, in the order of the cards."""
    got = js_page.evaluate(FOUR_KINDS)
    assert got["conditions"] == [
        {"column": "g", "levels": ["a", "b"]},
        {"column": "id", "levels": ["v1", "v2"]},
        {"column": "n", "range": [2, 7]},
        {"column": "t", "contains": "ab"},
    ]
    assert got["summary"] == "n: 2〜7、g: 2/3、id: 2/5000、t: 「ab」を含む"


def test_enter_in_an_end_of_a_numeric_card_leaves_it_unless_it_commits_a_conversion(
    js_page: Page,
) -> None:
    """Enter in the lower end of a numeric card leaves the field; the Enter of an IME conversion does not."""
    page = js_page
    page.evaluate(PANE)
    low = page.locator(".filter-range input").first
    low.focus()
    press_conversion_enters(low)
    assert low.evaluate("(field) => document.activeElement === field")
    press_plain_enter(low)
    assert not low.evaluate("(field) => document.activeElement === field")


# A filter pane of cards whose columns have missing values: a numeric one (n,
# 3 missing), one of levels (g, 2 missing, with a real "(null)" text), one of
# text (t, 4 missing) and a numeric one without finite values (e, 5
# missing), whose summaries come from a stub of `fetch`. `window.nullRow(name)`
# is a card's `(null)` row, `window.counter(name)` its count of ticked levels.
NULLS = """async () => {
  const summaries = {
    n: { numeric: true, min: 0, max: 10, nulls: 3, integer: true, temporal: null },
    g: { numeric: false, levels: [["(null)", 1], ["a", 2], ["b", 9]], n_levels: 3, nulls: 2 },
    t: { numeric: false, levels: null, n_levels: 90000, nulls: 4 },
    e: { numeric: true, min: null, max: null, nulls: 5, integer: false, temporal: null },
  };
  const candidates = { t: { levels: null, n_levels: 90000 } };
  window.fetch = async (url) => {
    const u = new URL(url, location.href);
    const column = u.searchParams.get("column");
    const body = u.pathname === "/api/summary" ? summaries[column] : candidates[column];
    return new Response(JSON.stringify(body));
  };
  document.body.innerHTML = `
    <div id="filters"><div class="filter-head"><span class="filter-summary"></span>
    <button class="filter-up"></button><button class="filter-down"></button></div>
    <div class="filter-resize"></div><div class="filter-list"></div></div>
    <div id="drop-tip"></div>`;
  const { FilterPane } = await import("/static/js/filters.js");
  const pane = new FilterPane(document.getElementById("filters"), () => {}, () => {});
  for (const [name, numeric] of [["n", true], ["g", false], ["t", false], ["e", true]]) pane.add({ name, numeric });
  const ready = () => pane.cards.every((c) => c.summary && (c.summary.levels !== null || c.candidates !== null));
  while (!ready()) await new Promise((r) => setTimeout(r, 10));
  window.pane = pane;
  const card = (name) => pane.cards.find((c) => c.name === name);
  window.nullRow = (name) => card(name).element.querySelector(".filter-null");
  window.counter = (name) => card(name).element.querySelector(".filter-note > span")?.textContent;
  window.names = (name) =>
    [...card(name).element.querySelectorAll(".filter-level-name")].map((e) => e.textContent);
  window.untick = (name) => window.nullRow(name).querySelector("input").click();
}"""


def test_the_null_row_of_a_card_of_levels(js_page: Page) -> None:
    """The (null) row comes last in either order, unticked, marks a real "(null)" text, and sets the condition and its words with the levels or alone; すべて外す unticks it."""
    page = js_page
    page.evaluate(NULLS)
    result = page.evaluate(
        """async () => {
          const pane = window.pane;
          const g = pane.cards[1];
          const out = { names: window.names("g"), idle: window.counter("g") };
          out.ticked = window.nullRow("g").querySelector("input").checked;
          out.count = window.nullRow("g").querySelector(".filter-level-count").textContent;
          g.order = "count";
          g.arrange();
          out.byCount = window.names("g");
          window.untick("g");
          out.alone = { conditions: pane.conditions(), summary: pane.summaryText(), counter: window.counter("g") };
          const boxes = [...g.element.querySelectorAll(".filter-level input")];
          boxes[0].click();
          boxes[2].click();
          out.both = { conditions: pane.conditions(), summary: pane.summaryText(), counter: window.counter("g") };
          g.element.querySelector(".filter-note .filter-reset").click();
          out.cleared = {
            conditions: pane.conditions(),
            counter: window.counter("g"),
            ticked: window.nullRow("g").querySelector("input").checked,
          };
          return out;
        }"""
    )
    assert result["names"] == ["(null)（文字列）", "a", "b", "(null)"]
    assert result["byCount"] == ["b", "a", "(null)（文字列）", "(null)"]
    assert result["idle"] == "3 水準（選ぶと絞る）"
    assert not result["ticked"]
    assert result["count"] == "2"
    assert result["alone"] == {
        "conditions": [{"column": "g", "nulls": True}],
        "summary": "g: null",
        "counter": "null を選択",
    }
    assert result["both"] == {
        "conditions": [{"column": "g", "levels": ["(null)", "b"], "nulls": True}],
        "summary": "g: 2/3+null",
        "counter": "2 / 3 水準と null を選択",
    }
    assert result["cleared"] == {
        "conditions": [],
        "counter": "3 水準（選ぶと絞る）",
        "ticked": False,
    }


def test_the_null_row_of_a_numeric_card(js_page: Page) -> None:
    """The (null) row of a numeric card is ticked: unticked it leaves the missing rows out, ticked with a range narrowed it keeps them too; 全範囲 keeps the tick; a column without finite values has it too."""
    page = js_page
    page.evaluate(NULLS)
    result = page.evaluate(
        """async () => {
          const pane = window.pane;
          const n = pane.cards[0];
          const state = () => ({
            conditions: pane.conditions().filter((c) => c.column === "n"),
            summary: pane.summaryText(),
          });
          const out = { ticked: window.nullRow("n").querySelector("input").checked, whole: state() };
          n.range = [2, 7];
          out.narrowed = state();
          window.untick("n");
          out.narrowedOff = state();
          n.element.querySelector(".filter-range .filter-reset").click();
          out.wholeOff = { ...state(), ticked: window.nullRow("n").querySelector("input").checked };
          out.empty = !!window.nullRow("e");
          out.note = n.element.querySelector(".filter-note").textContent;
          return out;
        }"""
    )
    assert result["ticked"]
    assert result["whole"] == {"conditions": [], "summary": ""}
    assert result["narrowed"] == {
        "conditions": [{"column": "n", "range": [2, 7], "nulls": True}],
        "summary": "n: 2〜7+null",
    }
    assert result["narrowedOff"] == {
        "conditions": [{"column": "n", "range": [2, 7]}],
        "summary": "n: 2〜7",
    }
    assert result["wholeOff"] == {
        "conditions": [{"column": "n", "nulls": False}],
        "summary": "n: null を除く",
        "ticked": False,
    }
    assert result["empty"]
    assert "null" not in result["note"]


def test_the_null_row_of_a_text_box(js_page: Page) -> None:
    """The (null) row under the text box keeps the missing rows alone with a blank box, or besides the text."""
    page = js_page
    page.evaluate(NULLS)
    result = page.evaluate(
        """async () => {
          const pane = window.pane;
          const t = pane.cards[2];
          const row = window.nullRow("t");
          const out = { below: row.previousElementSibling.className, ticked: row.querySelector("input").checked };
          window.untick("t");
          out.alone = { conditions: pane.conditions(), summary: pane.summaryText() };
          const box = t.element.querySelector(".filter-contains input");
          box.value = "a1";
          box.dispatchEvent(new Event("change"));
          out.both = { conditions: pane.conditions(), summary: pane.summaryText() };
          out.note = t.element.querySelector(".filter-note").textContent;
          return out;
        }"""
    )
    assert result["below"] == "filter-contains"
    assert not result["ticked"]
    assert result["alone"] == {
        "conditions": [{"column": "t", "nulls": True}],
        "summary": "t: null",
    }
    assert result["both"] == {
        "conditions": [{"column": "t", "contains": "a1", "nulls": True}],
        "summary": "t: 「a1」を含む+null",
    }
    assert "null" not in result["note"]


def test_a_card_without_missing_values_has_no_null_row(js_page: Page) -> None:
    """A column with no missing values gets no (null) row and no note of nulls."""
    page = js_page
    page.evaluate(PANE)
    rows = page.evaluate(
        """() => [...document.querySelectorAll('.filter-card')].map((c) =>
          [!!c.querySelector('.filter-null'), c.textContent.includes('null')])"""
    )
    assert rows == [[False, False], [False, False], [False, False]]


def test_the_null_row_of_candidates(js_page: Page) -> None:
    """The (null) row comes last past the 100 candidates and with none found, is not one of them nor of the picked ones, keeps its tick per mode and is unticked by すべて外す."""
    page = js_page
    _candidates(page)
    result = page.evaluate(
        """async () => {
          await window.answer(0);
          const pane = window.pane;
          const rows = () => [...window.card.element.querySelectorAll(".filter-card-body > .filter-levels .filter-level")];
          const counter = () => window.card.element.querySelector(".filter-note > span").textContent;
          const out = { first: window.view(), last: rows().at(-1).classList.contains("filter-null") };
          window.tick("(null)");
          window.tick("v2");
          out.ticked = { conditions: pane.conditions(), summary: pane.summaryText(), counter: counter() };
          window.search("zzz");
          await window.answer(1);
          out.none = window.view();
          const mode = (m) => window.card.element.querySelector(`.filter-mode [data-mode="${m}"]`).click();
          mode("contains");
          out.contains = {
            nulls: window.card.element.querySelector(".filter-null input").checked,
            conditions: pane.conditions(),
          };
          mode("pick");
          out.back = window.view().nulls;
          window.card.element.querySelector(".filter-note .filter-reset").click();
          out.cleared = { nulls: window.view().nulls, conditions: pane.conditions() };
          return out;
        }"""
    )
    assert len(result["first"]["listed"]) == 100
    assert result["first"]["nulls"] == [{"name": "(null)", "checked": False}]
    assert result["last"]
    assert result["ticked"] == {
        "conditions": [{"column": "id", "levels": ["v2"], "nulls": True}],
        "summary": "id: 1/300+null",
        "counter": "1 / 300 水準と null を選択",
    }
    assert result["none"]["status"] == "一致する候補がありません"
    assert result["none"]["listed"] == []
    assert result["none"]["nulls"] == [{"name": "(null)", "checked": True}]
    assert result["none"]["picked"] == [{"name": "v2", "checked": True}]
    assert result["contains"] == {"nulls": False, "conditions": []}
    assert result["back"] == [{"name": "(null)", "checked": True}]
    assert result["cleared"] == {
        "nulls": [{"name": "(null)", "checked": False}],
        "conditions": [],
    }


def test_snapshot_and_filters_key_hold_the_null_ticks(js_page: Page) -> None:
    """`restore` puts back the (null) ticks, and `filtersKey` tells conditions apart by `nulls`."""
    page = js_page
    page.evaluate(NULLS)
    result = page.evaluate(
        """async () => {
          const { filtersKey } = await import("/static/js/filters.js");
          const pane = window.pane;
          const before = pane.snapshot();
          window.untick("n");
          window.untick("g");
          const changed = pane.conditions();
          const after = pane.snapshot();
          pane.restore(before);
          const back = { conditions: pane.conditions(), tick: window.nullRow("n").querySelector("input").checked };
          pane.restore(after);
          const again = { conditions: pane.conditions(), tick: window.nullRow("g").querySelector("input").checked };
          const key = (nulls) => filtersKey([{ column: "g", levels: ["a"], ...(nulls === undefined ? {} : { nulls }) }]);
          return { changed, back, again, keys: [key() === key(false), key() === key(true)] };
        }"""
    )
    assert result["changed"] == [
        {"column": "g", "nulls": True},
        {"column": "n", "nulls": False},
    ]
    assert result["back"] == {"conditions": [], "tick": True}
    assert result["again"] == {"conditions": result["changed"], "tick": True}
    assert result["keys"] == [True, False]


# A filter pane without cards whose `fetch` is a stub: the summaries of n
# (numeric), g (3 levels) and id (too many levels to list, its candidates
# searched), each answered with `window.failing[column]` (200 by default).
# Every request is kept in `window.requests` as its path and parameters.
PREPARE = """async () => {
  const summaries = {
    n: { numeric: true, min: 0, max: 10, nulls: 0, integer: true, temporal: null },
    g: { numeric: false, levels: [["a", 5], ["b", 3], ["c", 1]], n_levels: 3, nulls: 0 },
    id: { numeric: false, levels: null, n_levels: 5000, nulls: 0 },
  };
  window.failing = {};
  window.requests = [];
  window.fetch = async (url) => {
    const u = new URL(url, location.href);
    const params = Object.fromEntries(u.searchParams);
    window.requests.push([u.pathname, params]);
    const status = window.failing[params.column] ?? 200;
    if (status !== 200) return new Response(JSON.stringify({ detail: "broken" }), { status });
    if (u.pathname === "/api/summary") return new Response(JSON.stringify(summaries[params.column]));
    return new Response(JSON.stringify({ levels: [["v1", 2], ["v2", 1]], truncated: false, n_levels: 5000 }));
  };
  document.body.innerHTML = `
    <div id="filters"><div class="filter-head"><span class="filter-summary"></span>
    <button class="filter-up"></button><button class="filter-down"></button></div>
    <div class="filter-resize"></div><div class="filter-list"></div></div>
    <div id="drop-tip"></div>`;
  const { FilterPane } = await import("/static/js/filters.js");
  window.sent = [];
  window.pane = new FilterPane(
    document.getElementById("filters"),
    (conditions) => window.sent.push(conditions),
    () => {},
  );
  const nulls = { range: true, pick: false, contains: false, listed: false };
  const entry = (name, numeric, more) =>
    ({ name, numeric, range: null, levels: [], contains: "", nulls, mode: "pick", query: "", order: "name", ...more });
  window.settings = [
    entry("n", true, { range: [2, 5] }),
    entry("g", false, { levels: ["a"] }),
    entry("id", false, { levels: ["v1"], query: "v", order: "count" }),
  ];
}"""


def test_prepared_settings_give_their_conditions_at_once(js_page: Page) -> None:
    """After `prepare`, the conditions taken right after `applySettings` are those of the settings (Issue #342): nothing is sent, the candidates are those of the card's query and order, and nothing is fetched again."""
    page = js_page
    page.evaluate(PREPARE)
    result = page.evaluate(
        """async () => {
          await window.pane.prepare(window.settings);
          const fetched = window.requests.length;
          window.pane.applySettings(window.settings);
          const conditions = window.pane.conditions();
          await new Promise((r) => setTimeout(r, 50));
          return {
            conditions,
            sent: window.sent,
            requests: window.requests,
            fetchedAfter: window.requests.length - fetched,
            summary: document.querySelector(".filter-summary").textContent,
          };
        }"""
    )
    assert result["conditions"] == [
        {"column": "g", "levels": ["a"]},
        {"column": "id", "levels": ["v1"]},
        {"column": "n", "range": [2, 5]},
    ]
    assert result["sent"] == []
    assert sorted(result["requests"], key=str) == sorted(
        [
            ["/api/summary", {"column": "n"}],
            ["/api/summary", {"column": "g"}],
            ["/api/summary", {"column": "id"}],
            ["/api/filter-levels", {"column": "id", "q": "v", "order": "count"}],
        ],
        key=str,
    )
    assert result["fetchedAfter"] == 0
    assert result["summary"] == "（3）n: 2〜5、g: 1/3、id: 1/5000"


def test_prepare_skips_the_cards_the_pane_knows(js_page: Page) -> None:
    """A column whose card was added before keeps that card: `prepare` fetches nothing for it."""
    page = js_page
    page.evaluate(PREPARE)
    result = page.evaluate(
        """async () => {
          window.pane.add({ name: "g", numeric: false });
          while (!window.pane.cards[0].summary) await new Promise((r) => setTimeout(r, 10));
          const card = window.pane.cards[0];
          window.requests.length = 0;
          await window.pane.prepare(window.settings.slice(1, 2));
          window.pane.applySettings(window.settings.slice(1, 2));
          return {
            requests: window.requests,
            same: window.pane.cards[0] === card,
            conditions: window.pane.conditions(),
          };
        }"""
    )
    assert result == {"requests": [], "same": True, "conditions": [{"column": "g", "levels": ["a"]}]}


@pytest.mark.parametrize(
    ("column", "message"),
    [
        ("g", "フィルタの列 g の要約を読めませんでした：broken"),
        ("id", "フィルタの列 id の候補を読めませんでした：broken"),
    ],
)
def test_prepare_fails_when_a_summary_or_candidates_fail(js_page: Page, column: str, message: str) -> None:
    """A summary or a first search that fails rejects `prepare` with its reason: the settings would be drawn without that card's condition."""
    page = js_page
    page.evaluate(PREPARE)
    result = page.evaluate(
        """async (column) => {
          if (column === "id") window.fetch = ((fetch) => (url) =>
            url.includes("filter-levels") ? Promise.resolve(new Response(JSON.stringify({ detail: "broken" }), { status: 500 })) : fetch(url))(window.fetch);
          else window.failing[column] = 500;
          try {
            await window.pane.prepare(window.settings);
            return null;
          } catch (error) {
            return error.message;
          }
        }""",
        column,
    )
    assert result == message
