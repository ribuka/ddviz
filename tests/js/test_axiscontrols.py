"""JS: axiscontrols.js keeps the settings of the axis columns and draws them."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# Makes `a`, an `AxisControls` over plain functions that record their calls
# in `calls`; `current()` returns `drawn`, null until a test sets it, and
# `replot()` returns `replotted`. `meta` draws the column "a" on x of one panel.
SETUP = """
  const m = await import("/static/js/axiscontrols.js");
  const { emptySettings } = await import("/static/js/axisdialog.js");
  const calls = { relayoutOwn: [], replot: 0, followMargin: [], openPlotMenu: 0, hideHover: 0 };
  let drawn = null;
  let replotted = "drawn";
  const meta = {
    panels: [{ x: 0, y: 0, xaxis: "x", yaxis: "y" }],
    x_columns: ["a"],
    y_columns: ["b"],
  };
  const a = new m.AxisControls({
    gd: { _fullLayout: {} },
    builderRoot: null,
    yZone: null,
    sticky: null,
    marginTargets: [],
    current: () => drawn,
    hideHover: () => calls.hideHover++,
    relayoutOwn: async (update) => calls.relayoutOwn.push(update),
    plotted: () => true,
    replot: async () => {
      calls.replot++;
      return replotted;
    },
    followMargin: (grow) => calls.followMargin.push(grow),
    openPlotMenu: () => calls.openPlotMenu++,
  });
"""


def _call(page: Page, body: str) -> object:
    """Return what `body` returns, run after `SETUP`."""
    return page.evaluate(f"async () => {{ {SETUP} {body} }}")


def test_apply_keeps_the_settings_and_the_angle(js_page: Page) -> None:
    """`apply` keeps the column's settings and angle; with nothing drawn it relayouts nothing."""
    result = _call(
        js_page,
        """const settings = { ...emptySettings(), lines: [{ type: "value", value: 1, color: "#000000", dash: "dash" }] };
        await a.apply("x", "a", settings, null, 30);
        return {
          same: a.settingsOf("a") === settings,
          angle: a.angleOf("x", "a"),
          other: a.angleOf("y", "a"),
          relayouts: calls.relayoutOwn.length,
        };""",
    )
    assert result == {"same": True, "angle": 30, "other": None, "relayouts": 0}


def test_apply_drops_empty_settings_and_a_null_angle(js_page: Page) -> None:
    """Empty settings drop the column's; a null angle drops it, an undefined one keeps it."""
    result = _call(
        js_page,
        """await a.apply("x", "a", { ...emptySettings(), lines: [{ type: "value", value: 1, color: "#000000", dash: "dash" }] }, null, 30);
        await a.apply("x", "a", emptySettings(), null, undefined);
        const kept = { settings: a.settingsOf("a") ?? "undefined", angle: a.angleOf("x", "a") };
        await a.apply("x", "a", null, null, null);
        return { kept, angle: a.angleOf("x", "a") };""",
    )
    assert result == {"kept": {"settings": "undefined", "angle": 30}, "angle": None}


def test_set_log_plots_only_the_drawn_result_and_undoes_a_refusal(js_page: Page) -> None:
    """`setLog` of a result not drawn plots nothing; a refused plot puts the scale back."""
    result = _call(
        js_page,
        """await a.setLog(meta, "x", "a", true);
        const notDrawn = { replot: calls.replot, log: a.scales.isLog("x", "a") };
        drawn = meta;
        replotted = "refused";
        await a.setLog(meta, "x", "a", true);
        const refused = { replot: calls.replot, log: a.scales.isLog("x", "a") };
        replotted = "drawn";
        await a.setLog(meta, "x", "a", true);
        return { notDrawn, refused, log: a.scales.isLog("x", "a") };""",
    )
    assert result == {
        "notDrawn": {"replot": 0, "log": False},
        "refused": {"replot": 1, "log": False},
        "log": True,
    }


def test_oriented_layout_reverses_the_column_s_axis(js_page: Page) -> None:
    """After `directions.set("x", "a", true)`, `orientedLayout` reverses the range of a's x axis."""
    result = _call(
        js_page,
        """const layout = { xaxis: { range: [0, 1] }, yaxis: { range: [2, 3] } };
        const before = a.orientedLayout(layout, meta);
        a.directions.set("x", "a", true);
        const after = a.orientedLayout(layout, meta);
        return { before: [before.xaxis.range, before.yaxis.range], after: [after.xaxis.range, after.yaxis.range] };""",
    )
    assert result == {"before": [[0, 1], [2, 3]], "after": [[1, 0], [2, 3]]}
