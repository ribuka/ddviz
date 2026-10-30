// Smoothing lines drawn on the image layers' canvas from a result's meta
// (`ddviz.compute.smooth`): each panel's `smooths` are `[series, xs, ys]`,
// a line through the points (xs, ys) in data coordinates.

// Width of a line, in CSS pixels.
const LINE_WIDTH = 2;
// Color of the lines of a gradient, whose single series has no color.
const GRADIENT_LINE = "#444";

// Draws the smoothing lines of every panel of `meta`; `colors` holds the
// series' colors and `alpha(s)` the opacity of series `s`. Earlier series
// in `order` are drawn first.
export function drawSmooths(ctx, full, meta, colors, alpha, order) {
  const rank = new Map(order.map((s, i) => [s, i]));
  for (const panel of meta.panels) {
    if (!panel.smooths?.length) continue;
    const xa = full[panel.xaxis.replace(/^x/, "xaxis")];
    const ya = full[panel.yaxis.replace(/^y/, "yaxis")];
    if (!xa || !ya) continue;
    ctx.save();
    ctx.beginPath();
    ctx.rect(xa._offset, ya._offset, xa._length, ya._length);
    ctx.clip();
    ctx.lineWidth = LINE_WIDTH;
    ctx.lineJoin = "round";
    const lines = [...panel.smooths].sort((a, b) => rank.get(a[0]) - rank.get(b[0]));
    for (const [series, xs, ys] of lines) {
      ctx.globalAlpha = alpha(series);
      ctx.strokeStyle = meta.color.kind === "gradient" ? GRADIENT_LINE : colors[series];
      ctx.beginPath();
      xs.forEach((x, i) => {
        const px = xa._offset + xa.l2p(x);
        const py = ya._offset + ya.l2p(ys[i]);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.stroke();
    }
    ctx.restore();
  }
}
