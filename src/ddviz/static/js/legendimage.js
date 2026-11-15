// The legend drawn on a canvas, for a copied graph image (`plotimage.js`):
// the entries the page's legend shows (`Legend.entries`, legend.js), every
// one of them, laid out as app.css lays them out in the side pane. A name
// longer than `MAX_WIDTH` ends in "…", as in the side pane.
import { EMPTY_NOTE } from "./legend.js";
import { shapeCanvas } from "./shapepanel.js";

// The side pane's font (app.css, body) and colors (`--text`,
// `--text-placeholder`, `--text-sub`, `--border-strong`).
const FONT = '"Segoe UI", sans-serif';
const TEXT = "#222";
const EMPTY = "#999";
const TICK = "#444";
const FRAME = "#aaa";
// Opacity of an inactive item and of an inactive gradient's bar (app.css).
const INACTIVE = 0.35;
// Sizes in CSS px, as app.css's `.legend-*` and `.colorbar*`.
const LINE = 18;
const TITLE_GAP = 4;
const SHAPES_GAP = 10;
const ITEM = LINE + 4;
const NAME_LEFT = 30;
const SWATCH_X = 14;
const SWATCH = 10;
const BAR = 160;
const BAR_MARGIN = 6;
const STRIP = 16;
const TICKS_LEFT = BAR_MARGIN + STRIP + 6;
// Widest a legend gets; longer names are cut.
export const MAX_WIDTH = 360;
const SIDE = 4;

// Returns the layout of `entries` measured on `ctx`: `{width, height,
// rows}`, each row `{entry, y, height, text}` (its top, from the legend's
// top, and its text as drawn). An empty legend is 0 × 0.
export function legendLayout(ctx, entries) {
  const rows = [];
  let y = 0;
  let width = 0;
  let previous = null;
  for (const entry of entries) {
    if (entry.type === "title") {
      if (entry.legend === "shape" && previous) y += SHAPES_GAP;
      ctx.font = `600 13px ${FONT}`;
      const text = fitText(ctx, entry.text, MAX_WIDTH - 2 * SIDE);
      width = Math.max(width, ctx.measureText(text).width + 2 * SIDE);
      rows.push({ entry, y: y + 2, height: LINE, text });
      y += 2 + LINE + TITLE_GAP;
    } else if (entry.type === "item") {
      ctx.font = `13px ${FONT}`;
      const note = entry.empty ? ` ${EMPTY_NOTE}` : "";
      const room = MAX_WIDTH - NAME_LEFT - SIDE - ctx.measureText(note).width;
      const text = fitText(ctx, entry.text, room) + note;
      width = Math.max(width, NAME_LEFT + ctx.measureText(text).width + SIDE);
      rows.push({ entry, y, height: ITEM, text });
      y += ITEM;
    } else if (entry.type === "bar") {
      ctx.font = `11px ${FONT}`;
      const ticks = Math.max(...entry.ticks.map((t) => ctx.measureText(t).width));
      width = Math.max(width, TICKS_LEFT + ticks + BAR_MARGIN);
      rows.push({ entry, y: y + 4, height: BAR, text: null });
      y += 4 + BAR + 4;
    } else {
      ctx.font = `13px ${FONT}`;
      width = Math.max(width, ctx.measureText(EMPTY_NOTE).width + 2 * SIDE);
      rows.push({ entry, y, height: ITEM, text: EMPTY_NOTE });
      y += ITEM;
    }
    previous = entry;
  }
  return { width: Math.ceil(width), height: Math.ceil(y), rows };
}

// Draws a legend laid out by `legendLayout` with its top left at (x, y) of
// `ctx`'s current transform.
export function drawLegend(ctx, layout, x, y) {
  ctx.save();
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  for (const { entry, y: top, height, text } of layout.rows) {
    const middle = y + top + height / 2;
    ctx.globalAlpha = entry.inactive ? INACTIVE : 1;
    if (entry.type === "title") {
      ctx.font = `600 13px ${FONT}`;
      ctx.fillStyle = TEXT;
      ctx.fillText(text, x + SIDE, middle);
    } else if (entry.type === "item") {
      if (entry.kernel) {
        const shape = shapeCanvas(entry.kernel);
        const size = entry.kernel.length;
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(shape, x + SWATCH_X - size / 2, middle - size / 2, size, size);
      } else {
        ctx.fillStyle = entry.color;
        ctx.beginPath();
        ctx.arc(x + SWATCH_X, middle, SWATCH / 2, 0, 2 * Math.PI);
        ctx.fill();
      }
      ctx.font = `13px ${FONT}`;
      ctx.fillStyle = entry.empty ? EMPTY : TEXT;
      ctx.fillText(text, x + NAME_LEFT, middle);
    } else if (entry.type === "bar") {
      const left = x + BAR_MARGIN;
      const barTop = y + top;
      const gradient = ctx.createLinearGradient(0, barTop + height, 0, barTop);
      entry.stops.forEach((color, i) => gradient.addColorStop(i / (entry.stops.length - 1), color));
      ctx.fillStyle = gradient;
      ctx.fillRect(left + 1, barTop + 1, STRIP - 2, height - 2);
      ctx.strokeStyle = FRAME;
      ctx.lineWidth = 1;
      ctx.strokeRect(left + 0.5, barTop + 0.5, STRIP - 1, height - 1);
      ctx.font = `11px ${FONT}`;
      ctx.fillStyle = TICK;
      const [hi, mid, lo] = entry.ticks;
      ctx.textBaseline = "top";
      ctx.fillText(hi, x + TICKS_LEFT, barTop);
      ctx.textBaseline = "middle";
      ctx.fillText(mid, x + TICKS_LEFT, barTop + height / 2);
      ctx.textBaseline = "bottom";
      ctx.fillText(lo, x + TICKS_LEFT, barTop + height);
      ctx.textBaseline = "middle";
    } else {
      ctx.font = `13px ${FONT}`;
      ctx.fillStyle = EMPTY;
      ctx.fillText(text, x + SIDE, middle);
    }
  }
  ctx.restore();
}

// Returns `text` cut to `room` px in `ctx`'s font, ending in "…" when cut.
export function fitText(ctx, text, room) {
  if (ctx.measureText(text).width <= room) return text;
  const chars = [...text];
  let lo = 0;
  let hi = chars.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (ctx.measureText(`${chars.slice(0, mid).join("")}…`).width <= room) lo = mid;
    else hi = mid - 1;
  }
  return `${chars.slice(0, lo).join("")}…`;
}
