"""JS: the list of the favorites of the drawing settings (`static/js/favorites.js`, Issue #278)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def run(page: Page, body: str) -> object:
    """Run `body` with `m` the module and `F` a new list; return what it returns."""
    return page.evaluate(
        f"""async () => {{
          const m = await import("/static/js/favorites.js");
          const F = new m.Favorites();
          const names = () => F.items.map((f) => f.settings.name);
          {body}
        }}"""
    )


def test_adds_up_to_three(js_page: Page) -> None:
    """Three are added in order; a fourth is refused and the list stays."""
    result = run(
        js_page,
        """
        const added = ["a", "b", "c", "d"].map((name) => F.add({ name }));
        return { added, names: names(), full: F.full, max: m.MAX_FAVORITES };
        """,
    )
    assert result == {"added": [True, True, True, False], "names": ["a", "b", "c"], "full": True, "max": 3}


def test_replace_keeps_the_place(js_page: Page) -> None:
    """`replace` puts the new settings, thumbnail and time where the old ones were."""
    result = run(
        js_page,
        """
        for (const name of ["a", "b", "c"]) F.add({ name }, null, new Date(2026, 0, 1, 9, 5));
        const replaced = F.replace(1, { name: "x" }, "thumb", new Date(2026, 0, 1, 14, 30));
        const outside = F.replace(3, { name: "y" });
        const middle = F.items[1];
        return { replaced, outside, names: names(), thumb: middle.thumbnail, time: m.timeText(middle.time) };
        """,
    )
    assert result == {"replaced": True, "outside": False, "names": ["a", "x", "c"], "thumb": "thumb", "time": "14:30"}


def test_remove_moves_the_rest_up(js_page: Page) -> None:
    """`remove` drops a favorite and those after it move up; another can then be added."""
    result = run(
        js_page,
        """
        for (const name of ["a", "b", "c"]) F.add({ name });
        const removed = F.remove(0);
        const outside = F.remove(5);
        const after = names();
        F.add({ name: "d" });
        return { removed, outside, after, then: names() };
        """,
    )
    assert result == {"removed": True, "outside": False, "after": ["b", "c"], "then": ["b", "c", "d"]}


def test_the_same_settings_whatever_the_order_of_their_keys(js_page: Page) -> None:
    """`indexOf` finds settings whose keys come in another order; other values are not found."""
    result = run(
        js_page,
        """
        F.add({ zones: { x: ["a"], y: ["b"] }, options: { size: 3 } }, "one", new Date(2026, 0, 1, 9, 0));
        F.add({ zones: { x: ["c"], y: ["b"] }, options: { size: 3 } }, "two", new Date(2026, 0, 1, 10, 0));
        return [
          F.indexOf({ options: { size: 3 }, zones: { y: ["b"], x: ["a"] } }),
          F.indexOf(JSON.parse('{"options":{"size":3},"zones":{"y":["b"],"x":["c"]}}')),
          F.indexOf({ zones: { x: ["a"], y: ["b"] }, options: { size: 4 } }),
        ];
        """,
    )
    assert result == [0, 1, -1]


def test_a_favorite_keeps_a_copy(js_page: Page) -> None:
    """The settings saved do not follow later changes of the object given."""
    result = run(
        js_page,
        """
        const settings = { zones: { x: ["a"] } };
        F.add(settings);
        settings.zones.x.push("b");
        return [F.items[0].settings.zones.x, F.indexOf({ zones: { x: ["a"] } })];
        """,
    )
    assert result == [["a"], 0]


def test_the_time_has_two_digits(js_page: Page) -> None:
    """The time is HH:MM with leading zeros."""
    texts = js_page.evaluate(
        """async () => {
          const m = await import("/static/js/favorites.js");
          return [m.timeText(new Date(2026, 0, 1, 7, 3)), m.timeText(new Date(2026, 0, 1, 23, 59))];
        }"""
    )
    assert texts == ["07:03", "23:59"]
