// The legend, in HTML beside the figure so that a scrolled grid does not hide
// it. Clicks fade series instead of hiding them, as flat-pca's plot_legend.js:
// a click toggles a level; a right click makes only that level active, or
// every level again when only it already is. The image layers (layers.js)
// and the hover follow its state. A level without rows in the drawn result
// (left out by the filter, or outside the view) stays, marked as empty, so
// that the colors of the others do not move.
//
// With an overlay beside the color (`meta.overlay`), the color levels and
// the overlay levels (marker shapes) are two legends, each toggled on its
// own: a series (a pair of a color and an overlay level) is inactive when
// either of its levels is. A right click on an item's marker opens the menu
// of the markers (`onMarkerMenu`): the size of the shapes.
//
// A numeric color column shows its scale instead (colorscale.js): a color
// bar for a gradient, or its intervals in colors spread over the scale. A
// right click on the bar or on the title opens the scale's menu.
import { cssColor, levelColors } from "./colorscale.js";
import { formatTemporal } from "./temporal.js";

export const INACTIVE_OPACITY = 0.1;

const BY_TEXT = { rows: "行数", values: "値の幅" };
// Color of the shapes in the overlay's legend.
const SHAPE_COLOR = "#444";

export class Legend {
  // `element` holds the items; `onChange` runs after each click, `onMenu`
  // with the right click's event on a numeric column's scale, and
  // `onMarkerMenu` with the right click's event on a marker.
  constructor(element, onChange, onMenu, onMarkerMenu) {
    this.element = element;
    this.onChange = onChange;
    this.onMenu = onMenu;
    this.onMarkerMenu = onMarkerMenu;
    this.series = [];
    this.shapes = [];
    // Inactive color levels and overlay levels; `inactive` holds the series
    // they make inactive.
    this.off = { color: new Set(), shape: new Set() };
    this.inactive = new Set();
    this.empty = { color: new Set(), shape: new Set() };
  }

  // Shows the levels of a result (its meta): the color column is the title
  // (none for a single color). A result of the same levels keeps their
  // state. Its images (one per series) mark the levels without rows.
  set(meta) {
    const shapes = meta.overlay?.levels ?? [];
    const same = (a, b) => a.length === b.length && a.every((s, i) => s === b[i]);
    if (!same(meta.series, this.series) || !same(shapes, this.shapes)) {
      this.off.color.clear();
      this.off.shape.clear();
    }
    this.title = meta.color.column;
    this.color = meta.color;
    this.meta = meta;
    this.series = meta.series;
    this.shapes = shapes;
    this.update();
    this.setEmpty(meta);
  }

  // Marks the levels of a result (its meta) that draw nothing: no series of
  // theirs has an image, a box plot or a smoothing line. They have no rows.
  setEmpty(meta) {
    const drawn = new Set(meta.images.flatMap((image, i) => (image === null ? [] : [i])));
    for (const panel of meta.panels) {
      for (const box of panel.boxes) drawn.add(box[1]);
      for (const line of panel.smooths) drawn.add(line[0]);
    }
    const shapes = meta.color.shapes;
    const hasColor = new Set([...drawn].map((s) => Math.floor(s / shapes)));
    const hasShape = new Set([...drawn].map((s) => s % shapes));
    this.empty = {
      color: new Set(meta.series.flatMap((_, i) => (hasColor.has(i) ? [] : [i]))),
      shape: new Set(this.shapes.flatMap((_, i) => (hasShape.has(i) ? [] : [i]))),
    };
    this.render();
  }

  clear() {
    this.series = [];
    this.shapes = [];
    this.color = null;
    this.meta = null;
    this.off.color.clear();
    this.off.shape.clear();
    this.inactive.clear();
    this.element.replaceChildren();
  }

  render() {
    if (!this.meta) {
      this.element.replaceChildren();
      return;
    }
    const nodes = this.color.kind === "gradient" ? this.barNodes() : this.colorNodes();
    if (this.meta.overlay) nodes.push(...this.shapeNodes());
    this.element.replaceChildren(...nodes);
  }

  colorNodes() {
    const colors = levelColors(this.meta);
    const items = this.series.map((name, i) =>
      this.item("color", i, this.title === null ? "全体" : name, (swatch) => {
        swatch.style.background = colors[i];
      }),
    );
    if (this.title === null) return items;
    const title = this.titleElement();
    const { bins } = this.color;
    if (bins) title.append(`（${BY_TEXT[bins.by]}で ${bins.n} 等分）`);
    return [title, ...items];
  }

  shapeNodes() {
    const { column, kernels } = this.meta.overlay;
    const title = document.createElement("div");
    title.className = "legend-title shapes";
    title.textContent = column;
    const items = this.shapes.map((name, i) =>
      this.item("shape", i, name, (swatch) => {
        swatch.classList.add("shape");
        swatch.append(shapeCanvas(kernels[i]));
      }),
    );
    return [title, ...items];
  }

  // One item of a legend (`kind` "color" or "shape"); `paint` draws its marker.
  item(kind, i, text, paint) {
    const item = document.createElement("div");
    item.className = "legend-item";
    item.classList.toggle("inactive", this.off[kind].has(i));
    item.classList.toggle("empty", this.empty[kind].has(i));
    if (this.empty[kind].has(i)) item.title = "表示範囲とフィルタの条件に合う行が無い";
    const marker = document.createElement("span");
    marker.className = "legend-marker";
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    paint(swatch);
    marker.append(swatch);
    item.append(marker, text);
    if (this.empty[kind].has(i)) item.append(" （行なし）");
    item.addEventListener("click", () => this.toggle(kind, i));
    item.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      this.isolate(kind, i);
    });
    // The markers have options only while shapes are drawn: their size.
    if (this.meta.overlay) {
      marker.classList.add("menu");
      marker.title = "右クリックで形の大きさを変える";
      marker.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        event.stopPropagation();
        this.onMarkerMenu(event);
      });
    }
    return item;
  }

  // The title; for a numeric column, a right click opens the scale's menu.
  titleElement() {
    const title = document.createElement("div");
    title.className = "legend-title";
    title.textContent = this.title;
    if (this.color.kind !== "levels") {
      title.classList.add("scale");
      title.title = "右クリックで色の付け方を変える";
      title.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        this.onMenu(event);
      });
    }
    return title;
  }

  // A gradient's color bar: high values at the top.
  barNodes() {
    const [lo, hi] = this.color.range;
    const bar = document.createElement("div");
    bar.className = "colorbar";
    const strip = document.createElement("div");
    strip.className = "colorbar-strip";
    const stops = [...Array(11).keys()].map((i) => cssColor(i / 10));
    strip.style.background = `linear-gradient(to top, ${stops.join(", ")})`;
    const ticks = document.createElement("div");
    ticks.className = "colorbar-ticks";
    for (const value of [hi, (lo + hi) / 2, lo]) {
      const tick = document.createElement("span");
      tick.textContent = formatTick(value, this.color.temporal);
      ticks.append(tick);
    }
    bar.append(strip, ticks);
    bar.title = "右クリックで色の付け方を変える";
    bar.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      this.onMenu(event);
    });
    const nodes = [this.titleElement(), bar];
    if (this.empty.color.has(0)) {
      const note = document.createElement("div");
      note.className = "legend-item empty";
      note.textContent = "（行なし）";
      nodes.push(note);
    }
    return nodes;
  }

  toggle(kind, i) {
    if (kind === "color" && this.color?.kind === "gradient") return;
    const off = this.off[kind];
    if (!off.delete(i)) off.add(i);
    this.changed();
  }

  isolate(kind, i) {
    if (kind === "color" && this.color?.kind === "gradient") return;
    const levels = kind === "color" ? this.series : this.shapes;
    const off = this.off[kind];
    const isolated = levels.every((_, j) => off.has(j) !== (j === i));
    off.clear();
    if (!isolated) levels.forEach((_, j) => j !== i && off.add(j));
    this.changed();
  }

  // Makes the series of the inactive levels inactive.
  update() {
    this.inactive.clear();
    if (!this.meta) return;
    const shapes = this.meta.color.shapes;
    for (let s = 0; s < this.meta.grid.n_series; s++) {
      if (this.off.color.has(Math.floor(s / shapes)) || this.off.shape.has(s % shapes)) {
        this.inactive.add(s);
      }
    }
  }

  changed() {
    this.update();
    this.render();
    this.onChange();
  }

  // Returns the series from the top drawn layer down: active series before
  // inactive ones (which sit behind), later series above earlier ones.
  order(nSeries) {
    const down = [...Array(nSeries).keys()].reverse();
    return [...down.filter((s) => !this.inactive.has(s)), ...down.filter((s) => this.inactive.has(s))];
  }
}

// Draws a marker shape (`meta.overlay.kernels`, rows from the top) a pixel
// per cell.
function shapeCanvas(kernel) {
  const canvas = document.createElement("canvas");
  canvas.width = kernel.length;
  canvas.height = kernel.length;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = SHAPE_COLOR;
  kernel.forEach((row, y) => {
    row.forEach((on, x) => {
      if (on) ctx.fillRect(x, y, 1, 1);
    });
  });
  return canvas;
}

// Returns a tick of a gradient: a datetime, date or time column's (`kind`) as such.
function formatTick(value, kind) {
  const temporal = formatTemporal(kind, value);
  if (temporal !== null) return temporal;
  return Number.isInteger(value) ? String(value) : Number(value.toPrecision(4)).toString();
}
