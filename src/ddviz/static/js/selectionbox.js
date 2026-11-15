// The box of a selection: the panel plotly's box lies on, its bounds in the
// page's linear units, and the names of panels that keep a box across results.
import { ascending } from "./axisdirection.js";
import { axisKey } from "./axiskey.js";
import { isLogAxis, toPosition } from "./axisscale.js";
import { linearRange } from "./temporal.js";

// Returns the panel of a box from plotly's `range` (keyed by axis id), its
// bounds as numbers (a date axis gives dates), read on plotly's graph div `gd`.
export function boxOf(gd, meta, range) {
  const panel = meta.panels.findIndex((p) => p.xaxis in range && p.yaxis in range);
  if (panel < 0) return null;
  const { xaxis, yaxis } = meta.panels[panel];
  const full = gd._fullLayout;
  return {
    panel,
    at: panelKey(meta.panels[panel]),
    x_range: boxRange(full[axisKey(xaxis)], range[xaxis]),
    y_range: boxRange(full[axisKey(yaxis)], range[yaxis]),
  };
}

// Returns the bounds of plotly's box along an axis in linear units. On a
// log axis, plotly's `event.range` holds values (checked in Chrome), not the
// exponents of the axis's range: they become exponents here.
export function boxRange(axis, range) {
  return ascending(isLogAxis(axis) ? range.map((v) => toPosition(true, v)) : linearRange(axis, range));
}

// Names a panel by its facet levels and axis columns, the same in every result of a plot.
export function panelKey(panel) {
  return JSON.stringify([panel.facet, panel.x, panel.y]);
}

// Whether two results draw the same panels in the same order.
export function samePanels(a, b) {
  return a.panels.length === b.panels.length && a.panels.every((p, i) => panelKey(p) === panelKey(b.panels[i]));
}
