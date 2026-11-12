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
