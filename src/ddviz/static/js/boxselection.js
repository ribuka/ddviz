// The selection of rows with a box on a panel of the drawn result: the box,
// its layer over every panel and the table of its rows, asked of the server
// (`/api/selection`).
import { axisKey } from "./axiskey.js";
import { isLogAxis, toValues } from "./axisscale.js";
import { filtersKey } from "./filters.js";
import { closeImages, loadImages } from "./layers.js";
import { errorText } from "./notice.js";
import { boxOf, panelKey, samePanels } from "./selectionbox.js";

// The selection of rows with a box on a panel of the drawn result, its
// layer over every panel and the table of its rows.
//
// Its state: the box drawn on a panel of the drawn result (its data ranges,
// its panel's facet levels and axis columns (`at`), and the index of that
// panel in the drawn result, -1 when a filter dropped it), the result its
// layer was asked for (`base`), the layer once it came (`layer`, decoded as
// `bitmaps`), whether the server holds the selection (`held`), whether the
// table is still to show (`fresh`) and the filters of the rows it shows
// (`filters`). Every panel shows the selected rows
// (`ddviz.compute.selection.selection_filter`); until the layer comes, the
// box shows them in its own panel. A filter may drop or bring back facet
// panels, so the panels' indices change: the box follows its facet levels.
export class BoxSelection {
  #state = null;
  // Bumped by every request and drop: a reply to an older one is stale.
  #generation = 0;

  // `gd` is plotly's plot of the drawn result; `current()` is the meta of
  // the result drawn (or null); `busy()` tells `{plotting, waiting}` (a plot
  // in flight, a view or size pending); `showRows(meta)` shows the status of
  // a result.
  constructor({ gd, layers, table, statusLine, current, busy, showRows }) {
    this.gd = gd;
    this.layers = layers;
    this.table = table;
    this.statusLine = statusLine;
    this.current = current;
    this.busy = busy;
    this.showRows = showRows;
  }

  // The state, or null without a selection; only the methods change it.
  get state() {
    return this.#state;
  }

  // Whether the selected rows' layer over the drawn result is being asked
  // for: asked (`base`) and not come yet (`layerBase`, the result of the
  // layer that came). A request that failed is not awaited.
  get asking() {
    const state = this.#state;
    return state !== null && state.base !== null && state.base !== state.layerBase;
  }

  // Takes plotly's box of `event`; plotly sends no range for a click beside
  // the box, which drops it.
  pick(event) {
    if (!event?.range) {
      this.clear();
      return;
    }
    const meta = this.current();
    if (!meta) return;
    this.statusLine.release();
    const box = boxOf(this.gd, meta, event.range);
    if (!box) return;
    closeImages(this.#state?.bitmaps);
    this.#state = { box, base: null, bitmaps: null, fresh: true };
    this.layers.setSelection({ box });
    // An aggregation in flight would be killed; the selection waits for its result.
    const { plotting, waiting } = this.busy();
    if (!waiting && !plotting) this.follow();
  }

  // Asks for the selected rows' layer over the drawn result, unless asked already.
  async follow() { // noqa: C901, PLR0912, PLR0915
    const meta = this.current();
    const selection = this.#state;
    if (!selection || !meta || this.busy().plotting || selection.base === meta.task) return;
    const mine = ++this.#generation;
    const { layers, statusLine } = this;
    const { box } = selection;
    box.panel = meta.panels.findIndex((p) => panelKey(p) === box.at);
    if (!selection.held && box.panel < 0) {
      // A filter dropped the box's panel before the server took the box.
      this.clear();
      return;
    }
    // The layer of other panels would land on the wrong ones: the box stands in.
    if (selection.bitmaps && !samePanels(layers.selection.meta, meta)) {
      closeImages(selection.bitmaps);
      selection.bitmaps = null;
      layers.setSelection({ box });
    }
    selection.base = meta.task;
    statusLine.show("選んだ行を集約中…");
    // Once the server holds the selection, it is asked again by its facet
    // levels, which the server keeps, not by the panel's index.
    const { panel, x_range, y_range } = box;
    // The server takes the box in values, ascending: those of a log axis are
    // the powers of 10 of its exponents (`axisscale.js`).
    const { x: xi, y: yj } = meta.panels[panel] ?? {};
    const body = selection.held
      ? { task: meta.task }
      : {
          task: meta.task,
          panel,
          x_range: toValues(meta.x_log[xi], x_range),
          y_range: toValues(meta.y_log[yj], y_range),
        };
    let layer;
    try {
      const response = await fetch("/api/selection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (mine !== this.#generation || !this.#state) return;
      if (!response.ok) {
        // Killed by a newer aggregation: asked again once its result is drawn.
        this.#state.base = null;
        const text = await response.text();
        const { plotting, waiting } = this.busy();
        if (response.status !== 409) statusLine.error(errorText(text));
        // Killed by a plot that failed: asked again, unless another aggregation goes on.
        else if (errorText(text) === "cancelled" && !plotting && !waiting && mine === this.#generation) this.follow();
        return;
      }
      layer = await response.json();
    } catch (error) {
      // The request itself failed (no connection, a body that is not JSON):
      // as an error response, the box and the layer before stay, and the
      // next drawn result asks again.
      if (mine !== this.#generation || !this.#state) return;
      this.#state.base = null;
      statusLine.error(`選んだ行の集約の要求に失敗した（${error.message}）`);
      console.error(error);
      return;
    }
    let bitmaps = null;
    try {
      bitmaps = await loadImages({ task: layer.task, images: layer.images }, meta);
    } catch (error) {
      console.error(error);
    }
    if (mine !== this.#generation || !this.#state || !bitmaps) {
      closeImages(bitmaps);
      // A layer that could not be read is not awaited: the status shows the drawn result's rows again.
      if (this.#state && mine === this.#generation) {
        this.#state.base = null;
        this.showRows(meta);
      }
      return;
    }
    const state = this.#state;
    closeImages(state.bitmaps);
    state.bitmaps = bitmaps;
    state.layer = layer;
    state.layerBase = meta.task;
    state.held = true;
    layers.setSelection({ meta, bitmaps, piles: new Set(layer.piles) });
    statusLine.show(`選んだ行：${layer.rows.toLocaleString()} 行（${layer.task_seconds.toFixed(1)} 秒）`);
    // A new filter changes the selected rows: the table starts again.
    const key = filtersKey(meta.filters);
    if (state.fresh || state.filters !== key) {
      state.fresh = false;
      state.filters = key;
      this.table.show(layer.rows);
    }
  }

  // Drops the selection; `server` also tells the server (a new plot drops it there).
  clear(server = true) {
    this.#generation++;
    if (!this.#state) return;
    closeImages(this.#state.bitmaps);
    this.#state = null;
    this.layers.setSelection(null);
    this.table.show(null);
    if (server) {
      fetch("/api/selection", { method: "DELETE" });
      const meta = this.current();
      if (meta) this.showRows(meta);
    }
  }

  // Takes `box`, the box of a plot drawn before, for a plot drawn again; its
  // layer is asked for by `follow`.
  restore(box) {
    this.#state = { box, base: null, bitmaps: null, fresh: true };
  }

  // Returns `layout` with plotly's box of the selection on the panel of `meta`
  // that has the box's facet levels and axis columns; a filter may have moved
  // the panel or dropped it.
  withBox(layout, meta) {
    if (!this.#state) return layout;
    const { at, x_range: x, y_range: y } = this.#state.box;
    const panel = meta.panels.find((p) => panelKey(p) === at);
    if (!panel) return layout;
    // plotly's box on a log axis is of values, as its `event.range` (`boxRange`).
    const [x0, x1] = toValues(isLogAxis(layout[axisKey(panel.xaxis)]), x);
    const [y0, y1] = toValues(isLogAxis(layout[axisKey(panel.yaxis)]), y);
    const box = { type: "rect", xref: panel.xaxis, yref: panel.yaxis, x0, x1, y0, y1 };
    return { ...layout, selections: [{ ...box, line: { width: 1, dash: "dot" } }] };
  }

  // The state whose layer to decode again in new colors, or null without a layer.
  layerToRecolor() {
    return this.#state?.bitmaps ? this.#state : null;
  }

  // Takes `bitmaps`, the layer of `state` decoded again; they are closed if
  // the selection changed meanwhile.
  replaceBitmaps(state, bitmaps) {
    if (state !== this.#state) {
      closeImages(bitmaps);
      return;
    }
    closeImages(state.bitmaps);
    state.bitmaps = bitmaps;
    this.layers.setSelection({ ...this.layers.selection, bitmaps });
  }
}
