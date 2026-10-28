// The legend, in HTML beside the figure so that a scrolled grid does not hide
// it. Clicks fade series instead of hiding them, as flat-pca's plot_legend.js:
// a click toggles a series; a right click makes only that series active, or
// every series again when only it already is. The image layers (layers.js)
// and the hover follow its state.
export const INACTIVE_OPACITY = 0.1;

export class Legend {
  // `element` holds the items; `onChange` runs after each click.
  constructor(element, onChange) {
    this.element = element;
    this.onChange = onChange;
    this.series = [];
    this.inactive = new Set();
  }

  // Shows the series of a result: `title` is the color column (null for a
  // single series). A result of the same series keeps their state.
  set(title, series, colors) {
    const same = series.length === this.series.length && series.every((s, i) => s === this.series[i]);
    if (!same) this.inactive.clear();
    this.title = title;
    this.series = series;
    this.colors = colors;
    this.render();
  }

  clear() {
    this.series = [];
    this.inactive.clear();
    this.element.replaceChildren();
  }

  render() {
    const items = this.series.map((name, i) => {
      const item = document.createElement("div");
      item.className = "legend-item";
      item.classList.toggle("inactive", this.inactive.has(i));
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = this.colors[i];
      item.append(swatch, this.title === null ? "全体" : name);
      item.addEventListener("click", () => this.toggle(i));
      item.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        this.isolate(i);
      });
      return item;
    });
    const nodes = [];
    if (this.title !== null) {
      const title = document.createElement("div");
      title.className = "legend-title";
      title.textContent = this.title;
      nodes.push(title);
    }
    this.element.replaceChildren(...nodes, ...items);
  }

  toggle(i) {
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
