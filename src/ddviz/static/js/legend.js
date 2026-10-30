// The legend, in HTML beside the figure so that a scrolled grid does not hide
// it. Clicks fade series instead of hiding them, as flat-pca's plot_legend.js:
// a click toggles a series; a right click makes only that series active, or
// every series again when only it already is. The image layers (layers.js)
// and the hover follow its state. A series without rows in the drawn result
// (left out by the filter, or outside the view) stays, marked as empty, so
// that the colors of the others do not move.
//
// A numeric color column shows its scale instead (colorscale.js): a color
// bar for a gradient, or its intervals in colors spread over the scale. A
// right click on the bar or on the title opens the scale's menu.
import { cssColor, seriesColors } from "./colorscale.js";

export const INACTIVE_OPACITY = 0.1;

const BY_TEXT = { rows: "行数", values: "値の幅" };

export class Legend {
  // `element` holds the items; `onChange` runs after each click, `onMenu`
  // with the right click's event on a numeric column's scale.
  constructor(element, onChange, onMenu) {
    this.element = element;
    this.onChange = onChange;
    this.onMenu = onMenu;
    this.series = [];
    this.inactive = new Set();
    this.empty = new Set();
  }

  // Shows the series of a result (its meta): the color column is the title
  // (none for a single series). A result of the same series keeps their
  // state. Its images (one per series) mark the series without rows.
  set(meta) {
    const { series } = meta;
    const same = series.length === this.series.length && series.every((s, i) => s === this.series[i]);
    if (!same) this.inactive.clear();
    this.title = meta.color.column;
    this.color = meta.color;
    this.meta = meta;
    this.series = series;
    this.setEmpty(meta);
  }

  // Marks the series of a result (its meta) that draw nothing: no image,
  // box plot or smoothing line. They have no rows.
  setEmpty(meta) {
    const drawn = new Set(meta.images.flatMap((image, i) => (image === null ? [] : [i])));
    for (const panel of meta.panels) {
      for (const box of panel.boxes) drawn.add(box[1]);
      for (const line of panel.smooths) drawn.add(line[0]);
    }
    this.empty = new Set(meta.images.flatMap((_, i) => (drawn.has(i) ? [] : [i])));
    this.render();
  }

  clear() {
    this.series = [];
    this.color = null;
    this.meta = null;
    this.inactive.clear();
    this.element.replaceChildren();
  }

  render() {
    if (!this.meta) {
      this.element.replaceChildren();
      return;
    }
    if (this.color.kind === "gradient") {
      this.renderBar();
      return;
    }
    this.colors = this.meta ? seriesColors(this.meta) : [];
    const items = this.series.map((name, i) => {
      const item = document.createElement("div");
      item.className = "legend-item";
      item.classList.toggle("inactive", this.inactive.has(i));
      item.classList.toggle("empty", this.empty.has(i));
      if (this.empty.has(i)) item.title = "表示範囲とフィルタの条件に合う行が無い";
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = this.colors[i];
      item.append(swatch, this.title === null ? "全体" : name);
      if (this.empty.has(i)) item.append(" （行なし）");
      item.addEventListener("click", () => this.toggle(i));
      item.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        this.isolate(i);
      });
      return item;
    });
    const nodes = [];
    if (this.title !== null) {
      const title = this.titleElement();
      const { bins } = this.color;
      if (bins) title.append(`（${BY_TEXT[bins.by]}で ${bins.n} 等分）`);
      nodes.push(title);
    }
    this.element.replaceChildren(...nodes, ...items);
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
  renderBar() {
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
      tick.textContent = formatTick(value);
      ticks.append(tick);
    }
    bar.append(strip, ticks);
    bar.title = "右クリックで色の付け方を変える";
    bar.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      this.onMenu(event);
    });
    const nodes = [this.titleElement(), bar];
    if (this.empty.has(0)) {
      const note = document.createElement("div");
      note.className = "legend-item empty";
      note.textContent = "（行なし）";
      nodes.push(note);
    }
    this.element.replaceChildren(...nodes);
  }

  toggle(i) {
    if (this.color?.kind === "gradient") return;
    if (!this.inactive.delete(i)) this.inactive.add(i);
    this.changed();
  }

  isolate(i) {
    const isolated = this.series.every((_, j) => this.inactive.has(j) !== (j === i));
    this.inactive.clear();
    if (!isolated) this.series.forEach((_, j) => j !== i && this.inactive.add(j));
    this.changed();
  }

  changed() {
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

function formatTick(value) {
  return Number.isInteger(value) ? String(value) : Number(value.toPrecision(4)).toString();
}
