"""JS: the Builder commits and rolls back a whole drop."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


BUILDER = """async () => {
  const { Builder } = await import("/static/js/builder.js");
  const root = document.createElement("div");
  for (const role of ["x", "y", "color", "symbol", "row", "col", "wrap"]) {
    const zone = document.createElement("div");
    zone.className = "zone";
    zone.dataset.role = role;
    root.append(zone);
  }
  let related = { key: "empty" };
  const changes = [];
  const builder = new Builder(root, document.createElement("div"), (e) => changes.push(e), {
    save: () => ({ ...related }),
    load: (state) => { related = { ...state }; },
  });
  const graph = () => JSON.stringify([builder.encoding.x, builder.encoding.y, builder.encoding.col, builder.encoding.wrap]);
  const chips = () => [...root.querySelectorAll(".chip-name")].map((c) => c.textContent);
  const out = {};
  builder.place("x", { name: "a", numeric: true, temporal: null }, { index: 0, insert: false });
  builder.place("y", { name: "b", numeric: true, temporal: "duration" }, { index: 0, insert: false });
  builder.place("col", { name: "f", numeric: false }, { index: 0, insert: false });
  related.key = "drawn";
  builder.commit();
  out.clean = builder.uncommitted();
  const drawn = graph();
  // One drop: a swap of x and y, then Wrap, which removes Group X.
  builder.place("y", { name: "a", numeric: true, from: "x", index: 0 }, { index: 0, insert: false });
  builder.place("wrap", { name: "w", numeric: false }, { index: 0, insert: false });
  related.key = "candidate";
  out.candidate = [builder.uncommitted(), graph()];
  const calls = changes.length;
  builder.rollback();
  out.rolledBack = [builder.uncommitted(), graph() === drawn, related.key, changes.length - calls, chips()];
  out.kinds = [builder.numeric.get("w") ?? null, builder.temporal.get("b")];
  // A snapshot taken before the rollback is not the committed state.
  const older = builder.snapshot();
  builder.place("color", { name: "c", numeric: false }, { index: 0, insert: false });
  builder.commit(older);
  out.olderCommit = builder.uncommitted();
  return out;
}"""


def test_the_builder_commits_and_rolls_back_a_whole_drop(js_page: Page) -> None:
    """A rollback restores the graph, the kinds of its chips and the related state as committed, without calling onChange."""
    result = js_page.evaluate(BUILDER)
    assert result["clean"] is False
    assert result["candidate"] == [True, '[["b"],["a"],null,"w"]']
    assert result["rolledBack"] == [False, True, "drawn", 0, ["a", "b (s)", "f"]]
    assert result["kinds"] == [None, "duration"]
    assert result["olderCommit"] is True


STASH = """async () => {
  const { Builder } = await import("/static/js/builder.js");
  const root = document.createElement("div");
  for (const role of ["x", "y", "color", "symbol", "row", "col", "wrap"]) {
    const zone = document.createElement("div");
    zone.className = "zone";
    zone.dataset.role = role;
    root.append(zone);
  }
  const changes = [];
  const builder = new Builder(root, document.createElement("div"), (e) => changes.push(e));
  const chip = (role) => root.querySelector(`.zone[data-role="${role}"] .chip`);
  const put = (role, name, from = undefined, index = 0) =>
    builder.place(role, { name, numeric: false, from, index }, { index: 0, insert: false });
  const out = {};
  put("x", "a");
  put("y", "b");
  // An empty zone and X are not stashed, nor told to onChange.
  let calls = changes.length;
  builder.toggleStash("color");
  builder.toggleStash("x");
  out.ignored = [changes.length - calls, builder.isStashed("color"), builder.isStashed("x")];
  // A stashed role is null in the graph drawn; its chip stays, faded.
  put("color", "c");
  builder.commit();
  builder.toggleStash("color");
  out.stashed = [
    changes.at(-1).color,
    builder.encoding.color,
    builder.isStashed("color"),
    chip("color").classList.contains("stashed"),
    chip("color").title,
  ];
  // A rollback brings the committed state back, unstashed.
  builder.rollback();
  out.rolledBack = [builder.isStashed("color"), chip("color").classList.contains("stashed")];
  builder.toggleStash("color");
  builder.commit();
  builder.toggleStash("color");
  builder.rollback();
  out.rolledBackStashed = [builder.isStashed("color"), chip("color").classList.contains("stashed")];
  // Toggled again, the role is drawn.
  builder.toggleStash("color");
  out.unstashed = [changes.at(-1).color, builder.isStashed("color")];
  // Another column placed takes the stash off.
  builder.toggleStash("color");
  put("color", "d");
  out.replaced = [changes.at(-1).color, builder.isStashed("color")];
  // A swap with another zone takes it off on both; a stashed chip moved is drawn where it goes.
  put("symbol", "s");
  builder.toggleStash("color");
  builder.toggleStash("symbol");
  put("symbol", "d", "color");
  out.swapped = [changes.at(-1).color, changes.at(-1).symbol, builder.isStashed("color"), builder.isStashed("symbol")];
  builder.toggleStash("symbol");
  put("row", "s", "symbol");
  out.moved = [changes.at(-1).row, changes.at(-1).symbol, builder.isStashed("row"), builder.isStashed("symbol")];
  // Wrap removes the stashed Group Y and takes its stash off.
  builder.toggleStash("row");
  put("wrap", "w");
  out.wrapped = [changes.at(-1).row, changes.at(-1).wrap, builder.isStashed("row")];
  // A stashed Wrap is removed by a facet; a removed chip leaves no stash.
  builder.toggleStash("wrap");
  out.wrapStashed = changes.at(-1).wrap;
  put("col", "g");
  out.faceted = [changes.at(-1).wrap, changes.at(-1).col, builder.isStashed("wrap")];
  builder.toggleStash("col");
  builder.remove("col", 0);
  out.removed = [changes.at(-1).col, builder.isStashed("col")];
  return out;
}"""


def test_a_stash_draws_the_zone_empty_until_its_column_changes(js_page: Page) -> None:
    """A stash draws the role as null and fades its chip; a rollback restores it; another column, a swap, a move, Wrap or a removal takes it off."""
    result = js_page.evaluate(STASH)
    assert result["ignored"] == [0, False, False]
    assert result["stashed"] == [
        None,
        "c",
        True,
        True,
        "c（Stash 中：描画では無いものとして扱う。右クリックの Stash で戻す）",
    ]
    assert result["rolledBack"] == [False, False]
    assert result["rolledBackStashed"] == [True, True]
    assert result["unstashed"] == ["c", False]
    assert result["replaced"] == ["d", False]
    assert result["swapped"] == ["s", "d", False, False]
    assert result["moved"] == ["s", None, False, False]
    assert result["wrapped"] == [None, "w", False]
    assert result["wrapStashed"] is None
    assert result["faceted"] == [None, "g", False]
    assert result["removed"] == [None, False]
