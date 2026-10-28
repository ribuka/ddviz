// Series image layers drawn on one canvas from plotly's axes, instead of an
// image trace per panel and series: plotly then only draws the axes, and a
// legend click redraws the canvas instead of the figure.
import { INACTIVE_OPACITY, inactiveSeries, seriesOrder } from "./legend.js";

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

// Fetches the PNGs of a result (one file, sliced by `meta.images`) and decodes
// them; returns per series an ImageBitmap whose tiles are the panels, or null.
export async function loadImages(meta) {
  const response = await fetch(`/api/images/${meta.task}`);
  if (!response.ok) throw new Error(`images of task ${meta.task}: ${response.status}`);
  const buffer = await response.arrayBuffer();
  return Promise.all(
    meta.images.map((span) =>
      span ? createImageBitmap(new Blob([new Uint8Array(buffer, span[0], span[1])], { type: "image/png" })) : null,
    ),
  );
}

// Frees the decoded images of a result.
export function closeImages(bitmaps) {
  bitmaps?.forEach((bitmap) => bitmap?.close());
}

// The canvas sits between plotly's two SVG layers: above the panels' grid and
// below the legend, the zoom box and the selection. It takes no pointer events.
export class ImageLayers {
  constructor(gd) {
    this.gd = gd;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "image-layers";
    this.meta = null;
    this.bitmaps = null;
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

  // Redraws on every change of the axes (also during a pan drag) or the
  // legend. Call after each `Plotly.newPlot`, which drops plotly's handlers.
  attach() {
    const draw = () => this.draw();
    for (const event of ["plotly_afterplot", "plotly_relayout", "plotly_relayouting", "plotly_restyle"]) {
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
    const { meta, bitmaps } = this;
    if (!meta || !bitmaps) return;
    ctx.imageSmoothingEnabled = false;
    const nSeries = meta.series.length;
    const inactive = inactiveSeries(this.gd);
    // Bottom layer first: inactive series behind, later series above earlier ones.
    const order = seriesOrder(this.gd, nSeries).reverse();
    const [x0, x1] = meta.x_range;
    const [y0, y1] = meta.y_range;
    const { width: w, height: h } = meta.grid;
    meta.panels.forEach((panel, p) => {
      const xa = full[axisKey(panel.xaxis)];
      const ya = full[axisKey(panel.yaxis)];
      if (!xa || !ya) return;
      const left = xa._offset + xa.l2p(x0);
      const right = xa._offset + xa.l2p(x1);
      const bottom = ya._offset + ya.l2p(y0);
      const top = ya._offset + ya.l2p(y1);
      ctx.save();
      ctx.beginPath();
      ctx.rect(xa._offset, ya._offset, xa._length, ya._length);
      ctx.clip();
      const sx = (p % meta.ncol) * w;
      const sy = Math.floor(p / meta.ncol) * h;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.translate(left, bottom);
      // Row 0 of a tile is the bottom bin.
      ctx.scale((right - left) / w, (top - bottom) / h);
      for (const s of order) {
        const bitmap = bitmaps[s];
        if (!bitmap) continue;
        ctx.globalAlpha = inactive.has(s) ? INACTIVE_OPACITY : 1;
        ctx.drawImage(bitmap, sx, sy, w, h, 0, 0, w, h);
      }
      ctx.restore();
    });
  }
}
