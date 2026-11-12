// Ticks of the categorical axes: a level at the middle of its band, thinned
// to labels that can be read (`docs/spec.md`, "カテゴリの軸の目盛り").
//
// Of the levels in the shown range, every `step`-th one (from the first
// level) has a tick and a label, `step` the fewest bands that hold the
// widest of those labels side by side on an x axis, or a line of text on a
// y axis. So the ticks are about as many as the axis has room for, whatever
// the levels: plotly drew every level's tick in time about the square of
// their number (1.2s for 420 levels, over 120s for 10,000). Every band and
// point is drawn all the same; the hover names a level without a label.
// The ticks are made again for each range shown (`bandTickUpdate`): zoomed
// in to bands that each hold their label, every level shown is named.

import { MARGIN_LEFT } from "./leftmargin.js";
import { levelText } from "./names.js";

// plotly's font of the tick labels.
const FONT = '12px "Open Sans", verdana, arial, sans-serif';
// Measured widths are taken this much wider, for a font that draws a little
// wider (as `ddviz.server.labeltext.MARGIN`).
const WIDTH_MARGIN = 1.1;
// Gap in pixels between the labels of an x axis, and from a y axis's labels
// to the edge of the figure (as `ddviz.server.figure.TICK_PAD`).
const TICK_PAD = 6;
// Room in pixels of a y axis's labels: the left margin of a figure's
// labels at its smallest (`leftmargin.js`), which the labels of a
// categorical axis do not widen (`ddviz.server.figure`).
const Y_ROOM = MARGIN_LEFT - TICK_PAD;
// Room in pixels a label of a y axis takes along the axis: a line of 12px text.
const LINE_PX = 16;
// Widest an x label is drawn when bands are narrower: a longer one ends in "…".
const MAX_LABEL_PX = 120;
const ELLIPSIS = "…";

let context = null;

function textWidth(text) {
  context ??= document.createElement("canvas").getContext("2d");
  context.font = FONT;
  return context.measureText(text).width * WIDTH_MARGIN;
}

// Returns `text` cut to fit `pixels`, ending in "…" when cut.
export function fitText(text, pixels) {
  if (textWidth(text) <= pixels) return text;
  const chars = Array.from(text);
  // The longest head that fits with the "…" after it.
  let lo = 0;
  let hi = chars.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (textWidth(chars.slice(0, mid).join("") + ELLIPSIS) <= pixels) lo = mid;
    else hi = mid - 1;
  }
  return chars.slice(0, lo).join("") + ELLIPSIS;
}

// plotly reads tick text as its own markup; the levels are the data's.
export function plotlyText(text) {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

// Returns the ticks of a categorical axis, `{tickvals, ticktext}`: of
// `levels`, those in `range` (band positions, either way round) at the
// `step` that reads on an axis `length` pixels long. An x axis (`across`
// false) fits its labels to the bands of a step; a y axis's labels lie
// across it, in `room` pixels.
export function bandTicks(levels, range, length, across, room) {
  const lo = Math.min(range[0], range[1]);
  const hi = Math.max(range[0], range[1]);
  const first = Math.max(0, Math.ceil(lo));
  const last = Math.min(levels.length - 1, Math.floor(hi));
  if (!(last >= first) || !(length > 0) || !(hi > lo)) return { tickvals: [], ticktext: [] };
  const perBand = length / (hi - lo);
  const shown = (step) => {
    const out = [];
    for (let i = Math.ceil(first / step) * step; i <= last; i += step) out.push(i);
    return out;
  };
  let step;
  if (across) {
    step = Math.max(1, Math.ceil(LINE_PX / perBand));
  } else {
    // A label as wide as its band when the bands are wide.
    const widest = Math.max(MAX_LABEL_PX, perBand - TICK_PAD);
    step = Math.max(1, Math.ceil((textWidth(ELLIPSIS) + TICK_PAD) / perBand));
    // A wider step shows other levels; it only grows, up to the widest label.
    for (;;) {
      let need = 0;
      for (const i of shown(step)) need = Math.max(need, Math.min(widest, textWidth(levelText(levels[i]))));
      const fits = Math.max(1, Math.ceil((need + TICK_PAD) / perBand));
      if (fits <= step) break;
      step = fits;
    }
    room = step * perBand - TICK_PAD;
  }
  const tickvals = shown(step);
  const ticktext = tickvals.map((i) => plotlyText(fitText(levelText(levels[i]), room)));
  return { tickvals, ticktext };
}

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

// Yields `[key, levels, across]` for each categorical axis of `meta`'s
// panels: its layout key, the levels of its column, and whether it is a y
// axis. The one band has its series' ticks (`ddviz.server.figure`).
function* bandAxes(meta) {
  for (const panel of meta.panels) {
    for (const [role, id, index] of [
      ["x", panel.xaxis, panel.x],
      ["y", panel.yaxis, panel.y],
    ]) {
      if (role === "x" && meta.one_band) continue;
      const levels = meta.axis_levels[meta[`${role}_columns`][index]];
      if (levels) yield [axisKey(id), levels, role === "y"];
    }
  }
}

// Returns `layout` with the ticks of its categorical axes at their ranges.
export function withBandTicks(layout, meta) {
  const out = { ...layout };
  const margin = layout.margin ?? {};
  const width = layout.width - (margin.l ?? 0) - (margin.r ?? 0);
  const height = layout.height - (margin.t ?? 0) - (margin.b ?? 0);
  for (const [key, levels, across] of bandAxes(meta)) {
    const axis = out[key];
    if (!axis?.range) continue;
    const [d0, d1] = axis.domain ?? [0, 1];
    const length = (across ? height : width) * (d1 - d0);
    out[key] = { ...axis, ...bandTicks(levels, axis.range, length, across, Y_ROOM) };
  }
  return out;
}

// Returns the relayout that gives the categorical axes of the figure drawn
// in `gd` (of `meta`) the ticks of their shown ranges, or null when they
// have them.
export function bandTickUpdate(gd, meta) {
  const full = gd._fullLayout;
  if (!full) return null;
  const update = {};
  for (const [key, levels, across] of bandAxes(meta)) {
    const axis = full[key];
    if (!axis?.range) continue;
    const ticks = bandTicks(levels, axis.range, axis._length, across, Y_ROOM);
    const drawn = gd.layout[key] ?? {};
    if (!sameList(drawn.tickvals, ticks.tickvals) || !sameList(drawn.ticktext, ticks.ticktext)) {
      update[`${key}.tickvals`] = ticks.tickvals;
      update[`${key}.ticktext`] = ticks.ticktext;
    }
  }
  return Object.keys(update).length ? update : null;
}

function sameList(a, b) {
  return Array.isArray(a) && a.length === b.length && a.every((v, i) => v === b[i]);
}
