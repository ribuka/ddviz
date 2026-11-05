// Piles drawn on the image layers' canvas from a result's meta
// (`ddviz.compute.stacks`): rows of a categorical axis that share their exact
// coordinates and do not fit their band, drawn as one neutral marker with
// their number of rows ("×1,234") instead of points of their series.
// `meta.piles` holds lists of the same length: each pile's `panel`, its bins
// `bx` and `by`, its rows `n` and the `series` of its rows.

// Room between a pile's marker and its label, and the label's font.
const LABEL_GAP = 3;
const FONT = "11px sans-serif";

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

// Returns the colors of the piles from the page's stylesheet (`--pile-*`),
// so that a theme changes them.
function pileColors() {
  const style = getComputedStyle(document.documentElement);
  return {
    fill: style.getPropertyValue("--pile-fill").trim(),
    line: style.getPropertyValue("--pile-line").trim(),
    text: style.getPropertyValue("--pile-text").trim(),
    halo: style.getPropertyValue("--pile-halo").trim(),
  };
}

// Returns the label of a pile: all its rows, with thousands separators.
export function pileLabel(n) {
  return `×${n.toLocaleString("en-US")}`;
}

// Returns the diameter in pixels of a pile's marker: wider than the largest
// marker of the plot's points, so that it stands out from them.
function pileSize(meta) {
  const sizes = meta.overlay?.sizes?.length ? meta.overlay.sizes : [meta.marker_size];
  return Math.max(9, Math.max(...sizes) + 4);
}

let measure = null;

// Returns the width in pixels of a label in the labels' font.
function labelWidth(text) {
  measure ??= document.createElement("canvas").getContext("2d");
  measure.font = FONT;
  return measure.measureText(text).width;
}

// Returns where pile `i` of `meta` lies on the plot: its center, the radius
// of its marker, and the box of its label; null off its panel's axes.
function place(full, meta, i) {
  const piles = meta.piles;
  const panel = meta.panels[piles.panel[i]];
  const xa = full[axisKey(panel.xaxis)];
  const ya = full[axisKey(panel.yaxis)];
  if (!xa || !ya) return null;
  const [x0, x1] = meta.x_ranges[panel.x];
  const [y0, y1] = meta.y_ranges[panel.y];
  const x = x0 + ((piles.bx[i] + 0.5) * (x1 - x0)) / meta.grid.width;
  const y = y0 + ((piles.by[i] + 0.5) * (y1 - y0)) / meta.grid.height;
  const cx = xa._offset + xa.l2p(x);
  const cy = ya._offset + ya.l2p(y);
  const radius = pileSize(meta) / 2;
  const text = pileLabel(piles.n[i]);
  const width = labelWidth(text);
  return {
    xa,
    ya,
    cx,
    cy,
    radius,
    text,
    label: { left: cx + radius + LABEL_GAP, top: cy - 7, width, height: 14 },
  };
}

// Returns the opacity of pile `i`: that of its most visible series, so that a
// pile fades only when all its series are inactive.
export function pileOpacity(meta, i, alpha) {
  return Math.max(0, ...meta.piles.series[i].map(alpha));
}

// Draws the piles of `meta`; `alpha(s)` is the opacity of series `s`, and
// `faded(i)` whether pile `i` fades (none of its rows selected while rows
// are), by `dim`.
export function drawPiles(ctx, full, meta, alpha, faded = () => false, dim = 1) {
  const piles = meta.piles;
  if (!piles?.n.length) return;
  const colors = pileColors();

  // The piles come by panel (their pixels in order): one clip per panel.
  let clipped = -1;
  ctx.save();
  for (let i = 0; i < piles.n.length; i++) {
    const at = place(full, meta, i);
    if (!at) continue;
    const opacity = pileOpacity(meta, i, alpha) * (faded(i) ? dim : 1);
    if (opacity <= 0) continue;
    const { xa, ya, cx, cy, radius, text, label } = at;
    if (piles.panel[i] !== clipped) {
      clipped = piles.panel[i];
      ctx.restore();
      ctx.save();
      ctx.font = FONT;
      ctx.textBaseline = "middle";
      ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.rect(xa._offset, ya._offset, xa._length, ya._length);
      ctx.clip();
    }
    ctx.globalAlpha = opacity;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
    ctx.fillStyle = colors.fill;
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = colors.line;
    ctx.stroke();
    ctx.lineWidth = 3;
    ctx.strokeStyle = colors.halo;
    ctx.strokeText(text, label.left, cy);
    ctx.fillStyle = colors.text;
    ctx.fillText(text, label.left, cy);
  }
  ctx.restore();
}

// Returns the pile of `meta` under the cursor (`px`, `py` in the plot's
// pixels): over its marker or its label, the last drawn first; -1 for none.
// A pile drawn invisible (all its series at opacity 0) is not found.
export function pileAt(full, meta, px, py, alpha) {
  const piles = meta.piles;
  if (!piles?.n.length) return -1;
  for (let i = piles.n.length - 1; i >= 0; i--) {
    const at = place(full, meta, i);
    if (!at || pileOpacity(meta, i, alpha) <= 0) continue;
    const { xa, ya, cx, cy, radius, label } = at;
    if (px < xa._offset || px > xa._offset + xa._length) continue;
    if (py < ya._offset || py > ya._offset + ya._length) continue;
    const onMarker = (px - cx) ** 2 + (py - cy) ** 2 <= radius ** 2;
    const onLabel =
      px >= label.left &&
      px <= label.left + label.width &&
      py >= label.top &&
      py <= label.top + label.height;
    if (onMarker || onLabel) return i;
  }
  return -1;
}

// Returns the center of pile `i` on the plot, where the hover's ring goes.
export function pileCenter(full, meta, i) {
  const at = place(full, meta, i);
  return at ? { cx: at.cx, cy: at.cy } : null;
}
