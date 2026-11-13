// The legend, in HTML beside the figure so that a scrolled grid does not hide
// it. Clicks fade series instead of hiding them, as flat-pca's plot_legend.js:
// a click toggles a level; a right click makes only that level active, or
// every level again when only it already is. The image layers (layers.js)
// and the hover follow its state. A level without rows in the drawn result
// (left out by the filter, or outside the view) stays, marked as empty, so
// that the colors of the others do not move.
//
// With a symbol beside the color (`meta.symbol`), the color levels and
// the symbol levels (marker shapes) are two legends, each toggled on its
// own: a series (a pair of a color and a symbol level) is inactive when
// either of its levels is. A right click on an item's marker opens the menu
// of the markers (`onMarkerMenu`): on a color item, the level's color and the
// size of every series' markers, or the scale's menu for the intervals of a
// numeric column; on a symbol item, the level's shape and the size of its
// shapes.
//
// A numeric color column shows its scale instead (colorscale.js): a color
// bar for a gradient, or its intervals in colors spread over the scale. A
// right click on the bar, on the title or on an interval's marker opens the
// scale's menu, which also has the size of the markers.
//
// The missing level (`MISSING`, names.js: the rows of a null or NaN value,
// drawn with "Show null rows") is the last item of either legend, shown as
// "(null)". Under a gradient's bar it is an item of its own, toggled and
// colored as the levels; a gradient without a finite value shows it alone,
// without a bar. Its marker's menu changes its color (or shape and size),
// whatever the kind of the color column.
//
// An inactive series is drawn at `inactiveOpacity` (`plot.legend.
// inactive_opacity` of the settings, `GET /api/settings`); at 0 it is hidden,
// and the hover does not find it (`hidden`). The legend's own inactive items
// stay at app.css's opacity, so that they can be clicked back at 0.
import { cssColor, isMissingLevel, levelColors } from "./colorscale.js";
import { hasMissing, levelText } from "./names.js";
import { shapeCanvas } from "./shapepanel.js";
import { formatTemporal } from "./temporal.js";

// Until the settings come.
const INACTIVE_OPACITY = 0.1;

export class Legend {
  // `element` holds the items; `onChange` runs after each click, `onMenu`
  // with the right click's event on a numeric column's scale, and
  // `onMarkerMenu` with the right click's event on a marker, its legend
  // ("color" or "shape") and the item's index.
  constructor(element, onChange, onMenu, onMarkerMenu) {
    this.element = element;
    this.onChange = onChange;
    this.onMenu = onMenu;
    this.onMarkerMenu = onMarkerMenu;
    this.series = [];
    this.shapes = [];
    // Inactive color levels and symbol levels; `inactive` holds the series
    // they make inactive.
    this.off = { color: new Set(), shape: new Set() };
    this.inactive = new Set();
    this.empty = { color: new Set(), shape: new Set() };
    this.inactiveOpacity = INACTIVE_OPACITY;
  }

  // Returns the opacity series `s` is drawn at.
  opacity(s) {
    return this.inactive.has(s) ? this.inactiveOpacity : 1;
  }

  // Returns the opacity the lines of color level `c` are drawn at: the
  // symbol levels do not split the lines, so only the color legend fades them.
  colorOpacity(c) {
    return this.off.color.has(c) ? this.inactiveOpacity : 1;
  }

  // Returns the series drawn invisible (inactive at opacity 0), which the
  // hover does not find.
  hidden() {
    return this.inactiveOpacity === 0 ? this.inactive : new Set();
  }

  // Shows the levels of a result (its meta): the color column is the title
  // (none for a single color, which shows no color legend).A result of the same levels keeps their
  // state. Its images (one per series) mark the levels without rows.
  set(meta) {
    const shapes = meta.symbol?.levels ?? [];
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
  // theirs has an image, a box plot or a smoothing line, and they have no
  // lines. They have no rows.
  setEmpty(meta) {
    const drawn = new Set(meta.images.flatMap((image, i) => (image === null ? [] : [i])));
    // The lines of color level `c` (`meta.line_images`) are of its first series.
    (meta.line_images ?? []).forEach((image, c) => {
      if (image !== null) drawn.add(c * meta.color.shapes);
    });
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
    if (this.meta.symbol) nodes.push(...this.shapeNodes());
    this.element.replaceChildren(...nodes);
  }

  // The color legend: none for a single color (Color empty), whose one item
  // would tell nothing. The title is the column's name alone: the intervals'
  // items and the scale's menu tell how a numeric column is cut.
  colorNodes() {
    if (this.title === null) return [];
    const colors = levelColors(this.meta);
    const items = this.series.map((name, i) =>
      this.item("color", i, levelText(name, this.series), (swatch) => {
        swatch.style.background = colors[i];
      }),
    );
    return [this.titleElement(), ...items];
  }

  shapeNodes() {
    const { column, kernels } = this.meta.symbol;
    const title = document.createElement("div");
    title.className = "legend-title shapes";
    title.textContent = column;
    title.title = column;
    const items = this.shapes.map((name, i) =>
      this.item("shape", i, levelText(name, this.shapes), (swatch) => {
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
    const marker = document.createElement("span");
    marker.className = "legend-marker";
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    paint(swatch);
    marker.append(swatch);
    // A long name ends in "…" within the side pane; its tooltip has it whole.
    const name = document.createElement("span");
    name.className = "legend-name";
    name.textContent = text;
    item.title = this.empty[kind].has(i) ? `${text}\n表示範囲とフィルタの条件に合う行が無い` : text;
    item.append(marker, name);
    if (this.empty[kind].has(i)) item.append(" （行なし）");
    item.addEventListener("click", () => this.toggle(kind, i));
    item.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      this.isolate(kind, i);
    });
    marker.classList.add("menu");
    marker.title = this.markerTip(kind, i);
    marker.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.onMarkerMenu(event, kind, i);
    });
    return item;
  }

  // The tooltip of a marker of a legend (`kind` "color" or "shape").
  markerTip(kind, i) {
    if (kind === "shape") return "右クリックでこの水準の形と大きさを変える";
    if (this.color.kind === "bins" && !isMissingLevel(this.meta, i)) return "右クリックで色の付け方を変える";
    return "右クリックで色と点の大きさを変える";
  }

  // The title; for a numeric column, a right click opens the scale's menu.
  titleElement() {
    const title = document.createElement("div");
    title.className = "legend-title";
    title.textContent = this.title;
    title.title = this.title;
    if (this.color.kind !== "levels") {
      title.classList.add("scale");
      title.title = `${this.title}\n右クリックで色の付け方を変える`;
      title.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        this.onMenu(event);
      });
    }
    return title;
  }

  // A gradient's color bar, high values at the top, and under it the missing
  // level's item; only the item without a finite value.
  barNodes() {
    const missing = hasMissing(this.series);
    const last = this.series.length - 1;
    const missingNodes = () => {
      if (!missing) return [];
      const colors = levelColors(this.meta);
      return [
        this.item("color", last, levelText(this.series[last]), (swatch) => {
          swatch.style.background = colors[last];
        }),
      ];
    };
    if (missing && last === 0) return [this.titleElement(), ...missingNodes()];
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
    bar.classList.toggle("inactive", this.off.color.has(0));
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
    return [...nodes, ...missingNodes()];
  }

  // Whether the color legend has no items to toggle: a gradient without its
  // missing level.
  barOnly(kind) {
    return kind === "color" && this.color?.kind === "gradient" && !hasMissing(this.series);
  }

  toggle(kind, i) {
    if (this.barOnly(kind)) return;
    const off = this.off[kind];
    if (!off.delete(i)) off.add(i);
    this.changed();
  }

  isolate(kind, i) {
    if (this.barOnly(kind)) return;
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

// Returns a tick of a gradient: a datetime, date or time column's (`kind`) as such.
function formatTick(value, kind) {
  const temporal = formatTemporal(kind, value);
  if (temporal !== null) return temporal;
  // An integer of 16 digits or more is shown as 4 significant digits, as the
  // others, so that the tick fits the side pane.
  if (Math.abs(value) >= 1e15) return value.toPrecision(4);
  return Number.isInteger(value) ? String(value) : Number(value.toPrecision(4)).toString();
}
