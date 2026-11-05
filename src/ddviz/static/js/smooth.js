// Smoothing lines drawn on the image layers' canvas from a result's meta
// (`ddviz.compute.smooth`): each panel's `smooths` are `[series, xs, ys]`,
// a line through the points (xs, ys) in data coordinates: on a log axis,
// at their exponents (`axisscale.js`), broken where a point has none.
import { isLogAxis, toPosition } from "./axisscale.js";

// Width of a line's colored stroke, in CSS pixels.
export const LINE_WIDTH = 2;
// Width of the white stroke under it, in CSS pixels: a 1px white edge on
// each side, so that the line stands out over points of its own color.
export const HALO_WIDTH = 4;
export const HALO_COLOR = "#fff";
// Color of the lines of a gradient, whose single series has no color.
const GRADIENT_LINE = "#444";

// Draws the smoothing lines of every panel of `meta`; `colors` holds the
// series' colors and `alpha(s)` the opacity of series `s`. Earlier series
// in `order` are drawn first, each as its white halo and then its color,
// so that a later line covers an earlier one with both. The context's
// transform must map CSS pixels.
export function drawSmooths(ctx, full, meta, colors, alpha, order) {
  const rank = new Map(order.map((s, i) => [s, i]));
  for (const panel of meta.panels) {
    if (!panel.smooths?.length) continue;
    const xa = full[panel.xaxis.replace(/^x/, "xaxis")];
    const ya = full[panel.yaxis.replace(/^y/, "yaxis")];
    if (!xa || !ya) continue;
    const xLog = isLogAxis(xa);
    const yLog = isLogAxis(ya);
    ctx.save();
    ctx.beginPath();
    ctx.rect(xa._offset, ya._offset, xa._length, ya._length);
    ctx.clip();
    ctx.lineJoin = "round";
    ctx.lineCap = "butt";
    const lines = [...panel.smooths].sort((a, b) => rank.get(a[0]) - rank.get(b[0]));
    for (const [series, xs, ys] of lines) {
      const opacity = alpha(series);
      if (!(opacity > 0)) continue;
      ctx.globalAlpha = opacity;
      ctx.beginPath();
      // A point without a position (an estimate not positive on a log
      // axis, or not finite) breaks the line: its ends stay apart.
      let joined = false;
      xs.forEach((x, i) => {
        const lx = toPosition(xLog, x);
        const ly = toPosition(yLog, ys[i]);
        if (!Number.isFinite(lx) || !Number.isFinite(ly)) {
          joined = false;
          return;
        }
        const px = xa._offset + xa.l2p(lx);
        const py = ya._offset + ya.l2p(ly);
        if (joined) ctx.lineTo(px, py);
        else ctx.moveTo(px, py);
        joined = true;
      });
      ctx.lineWidth = HALO_WIDTH;
      ctx.strokeStyle = HALO_COLOR;
      ctx.stroke();
      // A gradient's missing level has a color; its own series have none.
      ctx.lineWidth = LINE_WIDTH;
      ctx.strokeStyle = colors[series] ?? GRADIENT_LINE;
      ctx.stroke();
    }
    ctx.restore();
  }
}
