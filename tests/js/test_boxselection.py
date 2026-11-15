"""JS: boxselection.js keeps the selection of rows with a box, its layer and its table."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# Makes `s`, a `BoxSelection` over plain objects that record their calls in
# `calls`, and `box`, a box on the panel `p` of `meta`; `busy` is `{plotting,
# waiting}` as `s.busy()` returns it.
SETUP = """
  const m = await import("/static/js/boxselection.js");
  const calls = { setSelection: [], show: [], status: [], showRows: [] };
  const layers = { selection: null, setSelection: (s) => calls.setSelection.push(s) };
  const table = { show: (rows) => calls.show.push(rows) };
  const statusLine = {
    release: () => {},
    show: (text) => calls.status.push(text),
    error: (text) => calls.status.push(text),
  };
  const p = { facet: ["a"], x: 0, y: 0, xaxis: "x2", yaxis: "y2" };
  const meta = { task: 7, panels: [{ facet: ["b"], x: 0, y: 0, xaxis: "x", yaxis: "y" }, p], x_log: [false], y_log: [false], filters: [] };
  const box = { at: JSON.stringify([p.facet, p.x, p.y]), panel: 1, x_range: [1, 2], y_range: [3, 4] };
  let busy = { plotting: false, waiting: false };
  const s = new m.BoxSelection({
    gd: null,
    layers,
    table,
    statusLine,
    current: () => meta,
    busy: () => busy,
    showRows: (shown) => calls.showRows.push(shown),
  });
"""


def _call(page: Page, body: str) -> object:
    """Return what `body` returns, run after `SETUP` with `window.fetch` recording into `fetched`."""
    return page.evaluate(
        f"""async () => {{
          {SETUP}
          const fetched = [];
          const fetchBefore = window.fetch;
          window.fetch = async (url, init) => {{
            fetched.push([url, init?.method ?? "GET"]);
            return new Response("{{}}", {{ status: 500 }});
          }};
          try {{
            {body}
          }} finally {{
            window.fetch = fetchBefore;
          }}
        }}"""
    )


def test_a_pick_without_a_range_clears_as_clear_does(js_page: Page) -> None:
    """`pick({})` drops the state, the layer and the table, and tells the server, as `clear()` does."""
    result = _call(
        js_page,
        """s.restore(box);
        s.pick({});
        const picked = { state: s.state, ...structuredClone(calls), fetched: [...fetched] };
        s.restore(box);
        calls.setSelection.length = 0;
        calls.show.length = 0;
        calls.showRows.length = 0;
        fetched.length = 0;
        s.clear();
        const cleared = { state: s.state, ...structuredClone(calls), fetched: [...fetched] };
        return { picked, cleared, rowsShown: calls.showRows[0] === meta };""",
    )
    assert result["picked"] == result["cleared"]
    assert result["picked"]["state"] is None
    assert result["picked"]["setSelection"] == [None]
    assert result["picked"]["show"] == [None]
    assert result["picked"]["fetched"] == [["/api/selection", "DELETE"]]
    assert result["rowsShown"] is True


def test_a_clear_without_the_server_does_not_fetch(js_page: Page) -> None:
    """`clear(false)` drops the selection but does not tell the server."""
    result = _call(
        js_page,
        """s.restore(box);
        s.clear(false);
        return { state: s.state, setSelection: calls.setSelection, fetched };""",
    )
    assert result == {"state": None, "setSelection": [None], "fetched": []}


def test_a_restored_box_draws_on_its_panel(js_page: Page) -> None:
    """After `restore(box)`, `withBox` adds one dotted box on the panel of `box.at`; without the panel, the layout stays."""
    result = _call(
        js_page,
        """const layout = { xaxis2: { type: "linear" }, yaxis2: { type: "log" } };
        const before = s.withBox(layout, meta) === layout;
        s.restore(box);
        const state = s.state;
        const drawn = s.withBox(layout, meta);
        const other = { ...meta, panels: [meta.panels[0]] };
        return { before, state, drawn, kept: s.withBox(layout, other) === layout };""",
    )
    assert result["before"] is True
    assert result["state"] == {
        "box": {"at": '[["a"],0,0]', "panel": 1, "x_range": [1, 2], "y_range": [3, 4]},
        "base": None,
        "bitmaps": None,
        "fresh": True,
    }
    assert result["drawn"]["selections"] == [
        {
            "type": "rect",
            "xref": "x2",
            "yref": "y2",
            "x0": 1,
            "x1": 2,
            "y0": 1000,
            "y1": 10000,
            "line": {"width": 1, "dash": "dot"},
        }
    ]
    assert result["drawn"]["xaxis2"] == {"type": "linear"}
    assert result["kept"] is True


def test_follow_while_plotting_does_not_fetch(js_page: Page) -> None:
    """While `busy()` tells a plot in flight, `follow()` asks the server nothing."""
    result = _call(
        js_page,
        """s.restore(box);
        busy = { plotting: true, waiting: false };
        await s.follow();
        const whilePlotting = [...fetched];
        busy = { plotting: false, waiting: false };
        await s.follow();
        return { whilePlotting, after: fetched.map(([url, method]) => `${method} ${url}`) };""",
    )
    assert result == {"whilePlotting": [], "after": ["POST /api/selection"]}


def test_bitmaps_of_another_state_are_closed(js_page: Page) -> None:
    """`replaceBitmaps` closes the bitmaps of a state not current and keeps the state's; for the current state it swaps them."""
    result = _call(
        js_page,
        """const closed = [];
        const bitmap = (name) => ({ close: () => closed.push(name) });
        s.restore(box);
        const state = s.state;
        s.replaceBitmaps({ ...state }, [bitmap("a"), bitmap("b")]);
        const other = { closed: [...closed], bitmaps: s.state.bitmaps, setSelection: calls.setSelection.length };
        const mine = [bitmap("c")];
        s.replaceBitmaps(state, mine);
        return { other, swapped: s.state.bitmaps === mine, layer: calls.setSelection.at(-1).bitmaps === mine };""",
    )
    assert result["other"] == {"closed": ["a", "b"], "bitmaps": None, "setSelection": 0}
    assert result["swapped"] is True
    assert result["layer"] is True


def test_the_layer_to_recolor_is_the_state_with_bitmaps(js_page: Page) -> None:
    """`layerToRecolor()` is null without a selection or without its layer, and the state once it has bitmaps."""
    result = _call(
        js_page,
        """const none = s.layerToRecolor();
        s.restore(box);
        const noLayer = s.layerToRecolor();
        s.replaceBitmaps(s.state, [{ close() {} }]);
        return [none, noLayer, s.layerToRecolor() === s.state];""",
    )
    assert result == [None, None, True]
