"""JS: filters.js writes the numbers of a filter card short and sorts its levels."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

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
      listed: rows(".filter-card-body > .filter-levels .filter-level"),
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
    assert [r["name"] for r in searched["listed"]] == ["v7", *[f"v7{i}" for i in range(10)]]
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
    assert view["body"].startswith("水準が多すぎる（約 3,000,000 個）ため、部分一致で絞る")


def test_a_failure_shows_the_error_and_retries_with_the_same_search(js_page: Page) -> None:
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
