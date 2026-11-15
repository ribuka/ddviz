// The axis ranges of a result: how two ranges compare, the ranges on screen,
// and how they go into a layout and into plotly (`Plotly.relayout`).
import { ascending } from "./axisdirection.js";
import { axisKey } from "./axiskey.js";
import { linearRange, plotlyRange } from "./temporal.js";

// Whether two ranges run the same way.
export function sameOrder(a, b) {
  return a[1] < a[0] === b[1] < b[0];
}

// Whether two sizes of the graph (its width, height and margins) are equal; null is no size.
export function sameSize(a, b) {
  return (
    a !== null &&
    b !== null &&
    a.width === b.width &&
    a.height === b.height &&
    a.margin_left === b.margin_left &&
    a.margin_bottom === b.margin_bottom
  );
}

// Returns what the coordinates of the axis column `index` of `role` of
// `meta` mean: its scale, temporal kind, and the levels of a categorical
// axis (the order of its bands), or the one band of a figure without x.
export function axisCoordinates(meta, role, index) {
  const column = meta[`${role}_columns`][index];
  return JSON.stringify([
    role === "x" && meta.one_band,
    meta[`${role}_log`][index],
    meta.temporal?.[column] ?? null,
    meta.axis_levels?.[column] ?? null,
  ]);
}

// Whether a kept view (`keptView`) has a range for each axis column of a result.
export function sameAxes(keep, meta) {
  return keep.ranges.x.length === meta.x_axes.length && keep.ranges.y.length === meta.y_axes.length;
}

// Returns `layout` with the axis ranges of each x and y column given (`shownRanges`).
export function withRanges(layout, meta, ranges) {
  const out = { ...layout };
  for (const panel of meta.panels) {
    const xKey = axisKey(panel.xaxis);
    const yKey = axisKey(panel.yaxis);
    out[xKey] = { ...layout[xKey], range: ranges.x[panel.x] };
    out[yKey] = { ...layout[yKey], range: ranges.y[panel.y] };
  }
  return out;
}

// Returns whether two ranges are equal up to a small part of their span. A
// date axis's range comes back from plotly as the same milliseconds
// (`dateText`), however short it is.
export function sameRange(a, b) {
  const tol = Math.abs(b[1] - b[0]) * 1e-9;
  return Math.abs(a[0] - b[0]) <= tol && Math.abs(a[1] - b[1]) <= tol;
}

// Returns whether two lists of ranges (one per axis column) are equal.
export function sameRanges(a, b) {
  return a.length === b.length && a.every((range, i) => sameRange(range, b[i]));
}

// Returns the ranges on screen (plotly's graph div `gd`) of each x and y
// column of a result, as numbers (a date axis holds dates), ascending on a
// reversed axis too: the panels of one column share them (`matches`).
export function shownRanges(gd, meta) {
  const full = gd._fullLayout;
  return {
    x: meta.x_axes.map((id) => ascending(linearRange(full[axisKey(id)]))),
    y: meta.y_axes.map((id) => ascending(linearRange(full[axisKey(id)]))),
  };
}

// Returns a key of the drawn figure without its axis ranges and the ticks of
// its categorical axes, which follow the ranges (`bandticks.js`).
export function figureKey(data, layout) {
  const axes = {};
  for (const [key, value] of Object.entries(layout)) {
    axes[key] = /^[xy]axis\d*$/.test(key) ? { ...value, range: null, tickvals: null, ticktext: null } : value;
  }
  return JSON.stringify([data, axes]);
}

// Returns the relayout that gives every axis of plotly's graph div `gd` its
// range in `layout`, and a categorical axis its ticks, or null when the axes
// already have them.
export function rangeUpdate(gd, layout) {
  const update = {};
  for (const [key, value] of Object.entries(layout)) {
    if (!/^[xy]axis\d*$/.test(key)) continue;
    if (!sameRange(linearRange(gd._fullLayout[key]), value.range)) {
      update[`${key}.range`] = plotlyRange(value, value.range);
    }
    const drawn = gd.layout[key] ?? {};
    for (const name of ["tickvals", "ticktext"]) {
      if (value[name] && JSON.stringify(value[name]) !== JSON.stringify(drawn[name])) {
        update[`${key}.${name}`] = value[name];
      }
    }
  }
  return Object.keys(update).length ? update : null;
}
