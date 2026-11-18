"""JS: axislevels.js keeps the categorical axis columns whose bands are the levels of every row, and the axis menu toggles it (Issue #281)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

ITEM = "フィルタで除外された水準も軸に残す"


def test_the_setting_is_one_per_column_and_stays_off_the_graph(js_page: Page) -> None:
    """A column kept on X is kept on Y too; taken off the graph and put back, it is still kept; the request names the categorical columns placed, once each."""
    result = js_page.evaluate(
        """async () => {
          const { AxisLevels } = await import("/static/js/axislevels.js");
          const levels = new AxisLevels();
          const numeric = new Map([["g", false], ["h", false], ["v", true]]);
          levels.set("g", true);
          const onY = levels.request({ x: ["v"], y: ["g"] }, numeric);
          const both = levels.request({ x: ["g"], y: ["g"] }, numeric);
          const off = levels.request({ x: ["v"], y: ["v"] }, numeric);
          const back = levels.request({ x: ["g", "h"], y: ["v"] }, numeric);
          // A column the graph has as numeric is not sent.
          const numericG = levels.request({ x: ["g"], y: ["v"] }, new Map([["g", true]]));
          levels.set("h", true);
          const columns = levels.columns();
          levels.set("g", false);
          return { onY, both, off, back, numericG, columns, after: levels.columns() };
        }"""
    )
    assert result == {
        "onY": ["g"],
        "both": ["g"],
        "off": [],
        "back": ["g"],
        "numericG": [],
        "columns": ["g", "h"],
        "after": ["h"],
    }


# Makes `a`, an `AxisControls` whose `current()` is `drawn`, and `menu(axis,
# index)`, which opens the menu of that axis column and returns its items as
# `{text, disabled, checked}`.
SETUP = """
  const m = await import("/static/js/axiscontrols.js");
  let replotted = "drawn";
  const calls = { replot: 0 };
  const drawn = {
    panels: [{ x: 0, y: 0, xaxis: "x", yaxis: "y" }],
    x_columns: ["g"],
    y_columns: ["v"],
    x_log: [false],
    y_log: [false],
    x_loggable: [false],
    y_loggable: [true],
    axis_levels: { g: ["g0", "g1"] },
    keep_unfiltered_axis_levels: [],
    one_band: false,
  };
  let meta = drawn;
  const a = new m.AxisControls({
    gd: { _fullLayout: {} },
    builderRoot: null,
    yZone: null,
    sticky: null,
    marginTargets: [],
    current: () => meta,
    hideHover: () => {},
    relayoutOwn: async () => {},
    plotted: () => true,
    replot: async () => {
      calls.replot++;
      return replotted;
    },
    followMargin: () => {},
    openPlotMenu: () => {},
  });
  const menu = (axis, index) => {
    a.openMenuOf(new MouseEvent("contextmenu", { clientX: 10, clientY: 10 }), { axis, index });
    const rows = [...document.querySelectorAll(".axis-menu .scale-menu-item")];
    return rows.map((row) => ({
      text: row.textContent,
      disabled: row.disabled,
      checked: row.classList.contains("checked"),
    }));
  };
"""


def _call(page: Page, body: str) -> object:
    """Return what `body` returns, run after `SETUP`."""
    return page.evaluate(f"async () => {{ {SETUP} {body} }}")


def test_the_item_is_enabled_on_a_categorical_column_only(js_page: Page) -> None:
    """The item is enabled on a categorical x, checked as the meta has it; grayed out on a numeric y and on the one band of an empty X."""
    result = _call(
        js_page,
        """const item = (rows) => rows.find((r) => r.text === "フィルタで除外された水準も軸に残す");
        const categorical = item(menu("x", 0));
        const numericY = item(menu("y", 0));
        meta = { ...drawn, keep_unfiltered_axis_levels: ["g"] };
        const kept = item(menu("x", 0));
        meta = { ...drawn, one_band: true, x_columns: ["__band__"], axis_levels: { __band__: [""] } };
        const band = item(menu("x", 0));
        return { categorical, numericY, kept, band };""",
    )
    assert result == {
        "categorical": {"text": ITEM, "disabled": False, "checked": False},
        "numericY": {"text": ITEM, "disabled": True, "checked": False},
        "kept": {"text": ITEM, "disabled": False, "checked": True},
        "band": {"text": ITEM, "disabled": True, "checked": False},
    }


def test_picking_the_item_plots_again_and_a_refusal_turns_it_back(js_page: Page) -> None:
    """Picking the item keeps the column and plots again, in the request and the undo settings; a refused plot turns it back."""
    result = _call(
        js_page,
        """const pick = () =>
          [...document.querySelectorAll(".axis-menu .scale-menu-item")]
            .find((row) => row.textContent === "フィルタで除外された水準も軸に残す")
            .click();
        menu("x", 0);
        pick();
        await new Promise((resolve) => setTimeout(resolve, 0));
        const on = { kept: a.levels.has("g"), settings: a.settings().keepLevels, replots: calls.replot };
        a.levels.set("g", false);
        replotted = "refused";
        menu("x", 0);
        pick();
        await new Promise((resolve) => setTimeout(resolve, 0));
        const refused = { kept: a.levels.has("g"), replots: calls.replot };
        a.applySettings({ ...a.settings(), keepLevels: ["g"] });
        return { on, refused, applied: a.levels.has("g") };""",
    )
    assert result == {
        "on": {"kept": True, "settings": ["g"], "replots": 1},
        "refused": {"kept": False, "replots": 2},
        "applied": True,
    }
