"""JS: graph.js judges whether a graph can be drawn and with which elements, as `ddviz.server.plan` does."""

from __future__ import annotations

import itertools

import pytest
from playwright.sync_api import Page

from ddviz.server import plan
from ddviz.server.encoding import Encoding

pytestmark = pytest.mark.js

# `n` is numeric, `c` categorical, and `u` a column the map does not hold
# (numeric, as on the server).
XS = [[], ["n"], ["c"], ["u"]]
YS = [[], ["n"], ["c"], ["n", "c"]]
NUMERIC = {"n": True, "c": False}


def test_the_judgements_match_the_server(js_page: Page) -> None:
    """For 16 placements of x and y, oneBand, drawable, hasBoxPair and hasSmoothPair give what the server's functions give."""
    pairs = list(itertools.product(XS, YS))
    result = js_page.evaluate(
        """async ({ pairs, numeric }) => {
          const m = await import("/static/js/graph.js");
          const map = new Map(Object.entries(numeric));
          return pairs.map(([x, y]) => {
            const encoding = { x, y };
            return [
              m.oneBand(encoding, map),
              m.drawable(encoding, map),
              m.hasBoxPair(encoding, map),
              m.hasSmoothPair(encoding, map),
            ];
          });
        }""",
        {"pairs": pairs, "numeric": NUMERIC},
    )
    expected = []
    for x, y in pairs:
        encoding = Encoding(x=tuple(x), y=tuple(y))
        expected.append(
            [
                plan.one_band(encoding, NUMERIC),
                plan.drawable(encoding, NUMERIC),
                plan.has_box_pair(encoding, NUMERIC),
                plan.has_smooth_pair(encoding, NUMERIC),
            ]
        )
    assert dict(zip(map(str, pairs), result, strict=True)) == dict(
        zip(map(str, pairs), expected, strict=True)
    )


def test_drawn_roles_change_with_any_role(js_page: Page) -> None:
    """The same roles give the same text; another value of any role gives another."""
    result = js_page.evaluate(
        """async () => {
          const { drawnRoles } = await import("/static/js/graph.js");
          const base = {
            x: ["a"], y: ["b"], color: null, row: null, col: null, wrap: null,
            elements: ["points"], symbol: null,
          };
          const changes = [
            { x: ["c"] }, { y: ["c"] }, { color: "c" }, { row: "c" }, { col: "c" },
            { wrap: "c" }, { elements: ["points", "line"] }, { symbol: "c" },
          ];
          return {
            same: drawnRoles(base) === drawnRoles({ ...base }),
            changed: changes.map((change) => drawnRoles(base) !== drawnRoles({ ...base, ...change })),
          };
        }"""
    )
    assert result == {"same": True, "changed": [True] * 8}
