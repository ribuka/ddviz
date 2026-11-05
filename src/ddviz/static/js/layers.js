// Series image layers drawn on one canvas from plotly's axes, instead of an
// image trace per panel and series: plotly then only draws the axes, and a
// legend click redraws the canvas instead of the figure.
import { POINTS_UNDER_BOXES, drawBoxes } from "./boxes.js";
import { colorsNow, decode, seriesColors } from "./colorscale.js";
import { drawPiles } from "./piles.js";
import { drawSmooths } from "./smooth.js";

// Opacity of every row while rows are selected; the selected rows are drawn
// again at full opacity. Above the legend's default inactive opacity (0.1),
// so that a faded series still differs from an inactive one; an inactive
// opacity set at 0.25 or above blurs the two, as the user chose.
const SELECTION_DIM = 0.25;

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

// Fetches the PNGs of a result or layer (`source`: one file of task
// `source.task`, sliced by `source.images`) and decodes them in the colors of
// result `meta` (colorscale.js), again when the colors change meanwhile;
// returns per series an ImageBitmap whose tiles are the panels, or null.
export async function loadImages(source, meta = source) {
  const response = await fetch(`/api/images/${source.task}`);
  if (!response.ok) throw new Error(`images of task ${source.task}: ${response.status}`);
  const buffer = await response.arrayBuffer();
  const blobs = source.images.map((span) =>
    span ? new Blob([new Uint8Array(buffer, span[0], span[1])], { type: "image/png" }) : null,
  );
  for (;;) {
    const version = colorsNow();
    const bitmaps = await decode(blobs, meta);
    if (version === colorsNow()) return bitmaps;
    closeImages(bitmaps);
  }
}

// Frees the decoded images of a result.
export function closeImages(bitmaps) {
  bitmaps?.forEach((bitmap) => bitmap?.close());
}

// The canvas sits between plotly's two SVG layers: above the panels' grid and
// below the zoom box and the selection. It takes no pointer events. The
// series' state comes from the legend (legend.js).
export class ImageLayers {
  constructor(gd, legend) {
    this.gd = gd;
    this.legend = legend;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "image-layers";
    this.meta = null;
    this.bitmaps = null;
    // The selection: `{box}` (the box drawn on a panel of `meta`) until its
    // layer comes, then `{meta, bitmaps, piles}` (the layer, the result it was
    // aggregated for, and the pixels of the piles with selected rows), or null.
    this.selection = null;
    // A new device pixel ratio (a window moved to another screen, or another
    // zoom) changes no axis, so plotly sends no event.
    const watchRatio = () => {
      matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`).addEventListener(
        "change",
        () => {
          this.draw();
          watchRatio();
        },
        { once: true },
      );
    };
    watchRatio();
  }

  // Redraws on every change of the axes (also during a pan drag). Call after
  // each `Plotly.newPlot`, which drops plotly's handlers.
  attach() {
    const draw = () => this.draw();
    for (const event of ["plotly_afterplot", "plotly_relayout", "plotly_relayouting"]) {
      this.gd.on(event, draw);
    }
    this.draw();
  }

  // Draws the images of a result; `meta` places them (its ranges and panels).
  set(meta, bitmaps) {
    this.meta = meta;
    this.bitmaps = bitmaps;
    this.draw();
  }

  // Shows a selection (see the constructor), or none.
  setSelection(selection) {
    this.selection = selection;
    this.draw();
  }

  draw() {
    const full = this.gd._fullLayout;
    const svg = this.gd.querySelector(".main-svg");
    if (!full || !svg) return;
    if (this.canvas.previousElementSibling !== svg) svg.after(this.canvas);
    const dpr = window.devicePixelRatio || 1;
    const width = Math.round(full.width * dpr);
    const height = Math.round(full.height * dpr);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
      this.canvas.style.width = `${full.width}px`;
      this.canvas.style.height = `${full.height}px`;
    }
    const ctx = this.canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, full.width, full.height);
    const { meta, bitmaps, selection } = this;
    if (!meta || !bitmaps) return;
    ctx.imageSmoothingEnabled = false;
    const alpha = (s) => this.legend.opacity(s);
    // With a selection every row fades, and the selected rows are drawn
    // again on top, in every panel.
    const dim = selection ? SELECTION_DIM : 1;
    // The points under box plots fade, so that the boxes stand out.
    this.drawLayer(ctx, full, dpr, meta, bitmaps, (s) => alpha(s) * dim, null, true);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const order = this.legend.order(meta.grid.n_series).reverse();
    drawBoxes(ctx, full, meta, seriesColors(meta), alpha, order);
    // The smoothing lines, like the boxes, stay at full opacity over a selection.
    drawSmooths(ctx, full, meta, seriesColors(meta), alpha, order);
    if (selection?.bitmaps) {
      this.drawLayer(ctx, full, dpr, selection.meta, selection.bitmaps, alpha);
    } else if (selection?.box) {
      // Until the selected rows' layer comes, the box shows them in its panel.
      this.drawLayer(ctx, full, dpr, meta, bitmaps, alpha, selection.box);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // The piles lie over the points; with a selection, those without
    // selected rows fade as the points do.
    const { width: w, height: h } = meta.grid;
    const piles = meta.piles;
    const faded = (i) =>
      !selection?.piles?.has((piles.panel[i] * h + piles.by[i]) * w + piles.bx[i]);
    drawPiles(ctx, full, meta, alpha, selection ? faded : undefined, dim);
  }


  // Draws one layer: an image per series whose tiles are the panels that
  // `meta` places. With `box` ({panel, x_range, y_range}), only that panel,
  // clipped to the box. With `fade`, the points under box plots fade.
  drawLayer(ctx, full, dpr, meta, bitmaps, alpha, box = null, fade = false) {
    const nSeries = meta.grid.n_series;
    // Bottom layer first: inactive series behind, later series above earlier ones.
    const order = this.legend.order(nSeries).reverse();
    const { width: w, height: h } = meta.grid;
    meta.panels.forEach((panel, p) => {
      if (box && box.panel !== p) return;
      const xa = full[axisKey(panel.xaxis)];
      const ya = full[axisKey(panel.yaxis)];
      if (!xa || !ya) return;
      const [x0, x1] = meta.x_ranges[panel.x];
      const [y0, y1] = meta.y_ranges[panel.y];
      const left = xa._offset + xa.l2p(x0);
      const right = xa._offset + xa.l2p(x1);
      const bottom = ya._offset + ya.l2p(y0);
      const top = ya._offset + ya.l2p(y1);
      ctx.save();
      ctx.beginPath();
      ctx.rect(xa._offset, ya._offset, xa._length, ya._length);
      ctx.clip();
      if (box) {
        const bx = box.x_range.map((v) => xa._offset + xa.l2p(v));
        const by = box.y_range.map((v) => ya._offset + ya.l2p(v));
        ctx.beginPath();
        ctx.rect(Math.min(...bx), Math.min(...by), Math.abs(bx[1] - bx[0]), Math.abs(by[1] - by[0]));
        ctx.clip();
      }
      const sx = (p % meta.ncol) * w;
      const sy = Math.floor(p / meta.ncol) * h;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.translate(left, bottom);
      // Row 0 of a tile is the bottom bin.
      ctx.scale((right - left) / w, (top - bottom) / h);
      const under = fade && panel.points && panel.boxes?.length ? POINTS_UNDER_BOXES : 1;
      for (const s of order) {
        const bitmap = bitmaps[s];
        if (!bitmap) continue;
        ctx.globalAlpha = alpha(s) * under;
        ctx.drawImage(bitmap, sx, sy, w, h, 0, 0, w, h);
      }
      ctx.restore();
    });
  }
}
