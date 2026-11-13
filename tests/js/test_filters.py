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
