// Box plots drawn on the image layers' canvas from a result's meta
// (`ddviz.compute.boxes`): each panel's `boxes` are
// `[level, series, n, low, q1, median, q3, high]` along a categorical x
// axis. In a level's band, the series' boxes lie side by side. They are of
// values: on a log y axis, at their exponents (`axisscale.js`).
import { isLogAxis, toPosition } from "./axisscale.js";

// Half the width of a band (`ddviz.compute.bands.BAND`), and the width of a
// box as a part of its series' slot (`ddviz.compute.boxes.BOX`).
const BAND = 0.4;
const BOX = 0.8;
// Opacity of the points under box plots.
export const POINTS_UNDER_BOXES = 0.3;
// Opacity of a box's fill.
const FILL_OPACITY = 0.25;
// Color of the boxes of a gradient, whose single series has no color.
const GRADIENT_BOX = "#444";

// Returns the middle and half the width of a box along the x axis.
function span(box, nSeries) {
  const slot = (2 * BAND) / nSeries;
  return { middle: box[0] - BAND + slot * (box[1] + 0.5), half: (slot * BOX) / 2 };
}

// Returns the box plot of panel `p` of `meta` at data position (x, y): over
// its box or its whiskers, else null. The boxes of the series in `hidden`
// (drawn invisible) are not found.
export function boxAt(meta, p, x, y, hidden = new Set()) {
  const nSeries = meta.grid.n_series;
  // On a log axis, the boxes (of values) lie at their exponents, as y does.
  const log = meta.y_log[meta.panels[p]?.y];
  for (const box of meta.panels[p]?.boxes ?? []) {
    if (hidden.has(box[1])) continue;
    const { middle, half } = span(box, nSeries);
    if (Math.abs(x - middle) <= half && y >= toPosition(log, box[3]) && y <= toPosition(log, box[7])) return box;
  }
  return null;
}

// Draws the box plots of every panel of `meta`; `colors` holds the series'
// colors and `alpha(s)` the opacity of series `s`. Earlier series in
// `order` are drawn first.
export function drawBoxes(ctx, full, meta, colors, alpha, order) {
  const nSeries = meta.grid.n_series;
  const rank = new Map(order.map((s, i) => [s, i]));
  for (const panel of meta.panels) {
    if (!panel.boxes?.length) continue;
    const xa = full[panel.xaxis.replace(/^x/, "xaxis")];
    const ya = full[panel.yaxis.replace(/^y/, "yaxis")];
    if (!xa || !ya) continue;
    const px = (v) => xa._offset + xa.l2p(v);
    // The boxes are of values: on a log axis, at their exponents.
    const py = (v) => ya._offset + ya.l2p(toPosition(isLogAxis(ya), v));
    ctx.save();
    ctx.beginPath();
    ctx.rect(xa._offset, ya._offset, xa._length, ya._length);
    ctx.clip();
    const boxes = [...panel.boxes].sort((a, b) => rank.get(a[1]) - rank.get(b[1]));
    for (const box of boxes) {
      const [, series, , low, q1, median, q3, high] = box;
      const { middle, half } = span(box, nSeries);
      // The box's edges on screen, left to right and top to bottom on a
      // reversed axis too (`axisdirection.js`).
      const left = Math.min(px(middle - half), px(middle + half));
      const right = Math.max(px(middle - half), px(middle + half));
      const center = px(middle);
      const cap = (right - left) / 4;
      // A gradient's missing level has a color; its own series have none.
      const color = colors[series] ?? GRADIENT_BOX;
      ctx.globalAlpha = alpha(series);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (const [from, to] of [
        [low, q1],
        [q3, high],
      ]) {
        ctx.moveTo(center, py(from));
        ctx.lineTo(center, py(to));
      }
      for (const end of [low, high]) {
        ctx.moveTo(center - cap, py(end));
        ctx.lineTo(center + cap, py(end));
      }
      ctx.stroke();
      const top = Math.min(py(q1), py(q3));
      const height = Math.abs(py(q1) - py(q3));
      ctx.globalAlpha = alpha(series) * FILL_OPACITY;
      ctx.fillStyle = color;
      ctx.fillRect(left, top, right - left, height);
      ctx.globalAlpha = alpha(series);
      ctx.strokeRect(left, top, right - left, height);
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(left, py(median));
      ctx.lineTo(right, py(median));
      ctx.stroke();
    }
    ctx.restore();
  }
}
