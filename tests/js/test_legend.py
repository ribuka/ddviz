"""JS: legend.js starts every level active again for other series, and keeps their state for the same ones."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def test_other_series_start_active_and_the_same_keep_their_state(js_page: Page) -> None:
    """`Legend.set` with other color levels empties the inactive levels and series; the same levels keep them."""
    result = js_page.evaluate(
        """async () => {
          const { Legend } = await import("/static/js/legend.js");
          const element = document.createElement("div");
          document.body.append(element);
          const meta = (series) => ({
            series,
            symbol: null,
            colors: series.map(() => "#123456"),
            color: { column: "g", kind: "levels", shapes: 1 },
            images: series.map(() => ({})),
            line_images: [],
            panels: [],
            grid: { n_series: series.length },
          });
          const legend = new Legend(element, () => {}, () => {}, () => {});
          legend.set(meta(["a", "b", "c"]));
          legend.toggle("color", 1);
          const off = () => ({ levels: [...legend.off.color], series: [...legend.inactive] });
          const before = off();
          legend.set(meta(["a", "b", "c"]));
          const same = off();
          legend.set(meta(["b", "c"]));
          const other = off();
          element.remove();
          return { before, same, other };
        }"""
    )
    assert result["before"] == {"levels": [1], "series": [1]}
    assert result["same"] == result["before"]
    assert result["other"] == {"levels": [], "series": []}


def test_point_order_puts_the_missing_level_behind_the_series_of_the_same_activity(js_page: Page) -> None:
    """`Legend.pointOrder` lists, from the top down, the active non-missing, active missing, inactive non-missing and inactive missing series."""
    result = js_page.evaluate(
        """async () => {
          const { Legend } = await import("/static/js/legend.js");
          const { MISSING } = await import("/static/js/names.js");
          const element = document.createElement("div");
          document.body.append(element);
          const meta = (series, kind, shapes = 1) => ({
            series,
            symbol: shapes > 1 ? { column: "s", levels: [...Array(shapes).keys()].map(String), kernels: Array(shapes).fill([[1]]) } : null,
            colors: series.map(() => "#123456"),
            color: { column: "g", kind, shapes, range: [0, 1] },
            images: Array(series.length * shapes).fill({}),
            line_images: [],
            panels: [],
            grid: { n_series: series.length * shapes },
          });
          const legend = new Legend(element, () => {}, () => {}, () => {});
          const run = (m, off = []) => {
            legend.clear();
            legend.set(m);
            for (const i of off) legend.toggle("color", i);
            return { points: legend.pointOrder(m.grid.n_series), order: legend.order(m.grid.n_series) };
          };
          const out = {
            levels: run(meta(["a", MISSING, "b"], "levels")),
            gradient: run(meta(["", MISSING], "gradient")),
            bothOff: run(meta(["", MISSING], "gradient"), [0, 1]),
            valueOff: run(meta(["", MISSING], "gradient"), [0]),
            bins: run(meta(["[0, 1)", "[1, 2]", MISSING], "bins"), [1]),
            symbol: run(meta(["a", MISSING], "levels", 2)),
            text: run(meta(["a", "(null)"], "levels")),
            none: run(meta(["a", "b", "c"], "levels"), [2]),
          };
          element.remove();
          return out;
        }"""
    )
    assert result["levels"]["points"] == [2, 0, 1]
    assert result["gradient"]["points"] == [0, 1]
    assert result["bothOff"]["points"] == [0, 1]
    # Only the non-missing series is inactive: the active missing one is on top.
    assert result["valueOff"]["points"] == [1, 0]
    assert result["bins"]["points"] == [0, 2, 1]
    # Series s is of color level s // 2: the missing level's series 2 and 3 sit behind.
    assert result["symbol"]["points"] == [1, 0, 3, 2]
    # A real "(null)" string is an ordinary level.
    assert result["text"]["points"] == result["text"]["order"] == [1, 0]
    assert result["none"]["points"] == result["none"]["order"] == [1, 0, 2]
