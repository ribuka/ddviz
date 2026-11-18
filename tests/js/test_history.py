"""JS: history.js keeps the steps of the drawing settings for undo and redo."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def _call(page: Page, body: str) -> object:
    """Return what `body` (the body of a function of `m`, the module, and `h`, a new `SettingsHistory`) returns."""
    return page.evaluate(
        f"""async () => {{
          const m = await import("/static/js/history.js");
          const h = new m.SettingsHistory();
          {body}
        }}"""
    )


def test_undo_and_redo_move_among_the_steps(js_page: Page) -> None:
    """Undo goes to the step before the one shown, redo to the one after, once moved to."""
    result = _call(
        js_page,
        """const out = [[h.canUndo, h.canRedo, h.undoTarget()]];
        h.push({ a: 1 });
        out.push([h.canUndo, h.canRedo, h.undoTarget()]);
        h.push({ a: 2 });
        h.push({ a: 3 });
        const back = h.undoTarget();
        out.push(back);
        h.moveTo(back.index);
        out.push([h.index, h.canUndo, h.canRedo, h.redoTarget()]);
        h.moveTo(h.undoTarget().index);
        out.push([h.index, h.canUndo, h.canRedo]);
        h.moveTo(h.redoTarget().index);
        out.push(h.index);
        return out;""",
    )
    assert result == [
        [False, False, None],
        [False, False, None],
        {"index": 1, "settings": {"a": 2}},
        [1, True, True, {"index": 2, "settings": {"a": 3}}],
        [0, False, True],
        1,
    ]


def test_a_target_is_a_copy(js_page: Page) -> None:
    """Changing the settings of a target or of what was pushed leaves the step as it was."""
    result = _call(
        js_page,
        """const s = { a: [1] };
        h.push(s);
        s.a.push(2);
        h.push({ a: [3] });
        h.undoTarget().settings.a.push(4);
        return h.undoTarget().settings;""",
    )
    assert result == {"a": [1]}


def test_past_the_most_steps_the_oldest_go(js_page: Page) -> None:
    """Pushing past 50 steps drops the oldest: 50 stay, the latest shown."""
    result = _call(
        js_page,
        """for (let i = 0; i < 53; i++) h.push({ i });
        let oldest = h.index;
        while (h.canUndo) h.moveTo(h.undoTarget().index);
        return [m.MAX_STEPS, h.steps.length, oldest, h.steps[0].settings];""",
    )
    assert result == [50, 50, 49, {"i": 3}]


def test_a_new_step_drops_those_of_redo(js_page: Page) -> None:
    """A step pushed after an undo replaces the steps after the one shown."""
    result = _call(
        js_page,
        """h.push({ a: 1 });
        h.push({ a: 2 });
        h.push({ a: 3 });
        h.moveTo(h.undoTarget().index);
        h.moveTo(h.undoTarget().index);
        const pushed = h.push({ a: 4 });
        return [pushed, h.canRedo, h.steps.map((s) => s.settings.a), h.undoTarget()];""",
    )
    assert result == [True, False, [1, 4], {"index": 0, "settings": {"a": 1}}]


def test_the_settings_shown_are_not_pushed_again(js_page: Page) -> None:
    """The settings of the step shown make no step, even with their keys or a Map's entries in another order."""
    result = _call(
        js_page,
        """const out = [h.push({ a: 1, b: { c: 2, d: 3 }, m: new Map([["x", 1], ["y", 2]]) })];
        out.push(h.push({ b: { d: 3, c: 2 }, m: new Map([["y", 2], ["x", 1]]), a: 1 }));
        out.push(h.push({ a: 1, b: { c: 2, d: 3 }, m: new Map([["x", 1], ["y", 3]]) }));
        h.moveTo(0);
        // The step shown is the first: its settings again are not pushed.
        out.push(h.push({ a: 1, b: { c: 2, d: 3 }, m: new Map([["y", 2], ["x", 1]]) }));
        out.push(h.steps.length);
        return out;""",
    )
    assert result == [True, False, True, False, 2]


def test_the_key_orders_keys_entries_and_sets(js_page: Page) -> None:
    """`settingsKey` sorts the keys of objects, a Map's entries by key and a Set's values; arrays keep their order."""
    result = _call(
        js_page,
        """return [
          m.settingsKey({ b: 1, a: [2, 1] }),
          m.settingsKey(new Map([["b", 1], ["a", 2]])),
          m.settingsKey(new Set(["b", "a"])),
          m.settingsKey(JSON.parse('{"__proto__": 1, "a": 2}')),
          m.settingsKey({ a: undefined, b: null }),
        ];""",
    )
    assert result == [
        '{"a":[2,1],"b":1}',
        '[["a",2],["b",1]]',
        '["a","b"]',
        '{"__proto__":1,"a":2}',
        '{"b":null}',
    ]
