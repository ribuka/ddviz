// The page: drop columns on the graph builder's zones, plot, zoom and pan,
// resize, hover, select rows with a box, and filter rows.
import { Builder } from "./builder.js";
import { showCasts } from "./casts.js";
import { attachColumnList } from "./columns.js";
import { openDataMenu } from "./datamenu.js";
import { ElementBar } from "./elements.js";
import { FilterPane } from "./filters.js";
import { attachHover } from "./hover.js";
import { ImageLayers, closeImages, loadImages } from "./layers.js";
import { LeftPane } from "./leftpane.js";
import { Legend } from "./legend.js";
import { StatusLine, Toasts, errorText } from "./notice.js";
import { openScaleMenu } from "./scalemenu.js";
import { levelHeading, openShapeMenu, SIZE_HEADING } from "./shapemenu.js";
import { DEFAULT_SMOOTHING, openSmoothMenu, smoothingText } from "./smoothmenu.js";
import { StickyLabels } from "./sticky.js";
import { SelectionTable } from "./table.js";
import { linearRange } from "./temporal.js";

const statusLine = new StatusLine(document.getElementById("status"), new Toasts(document.getElementById("toasts")));
const hoverWarning = document.getElementById("hover-warning");
const info = document.getElementById("info");
const gd = document.getElementById("plot");
const stage = document.getElementById("stage");
const timings = { hover: [] };

function setInfo(extra = {}) {
  const hover = timings.hover;
  const recent = hover.slice(-50);
  const median = recent.length ? [...recent].sort((a, b) => a - b)[Math.floor(recent.length / 2)] : null;
  info.textContent = JSON.stringify(
    {
      convert_s: timings.convert,
      task_s: timings.task,
      fetch_ms: timings.fetch,
      newPlot_ms: timings.plot,
      images_ms: timings.images,
      newPlot_and_images_ms: timings.plotAndImages,
      view_task_s: timings.viewTask,
      view_fetch_ms: timings.viewFetch,
      view_react_ms: timings.react,
      figure_kb: timings.size,
      hover_ms_median_last50: median && Number(median.toFixed(2)),
      ...extra,
    },
    null,
    1,
  );
}

const converting = document.getElementById("converting");
const convertingText = document.getElementById("converting-text");
const convertingBar = document.getElementById("converting-bar");

// While a worker converts columns into the cache, only its progress shows;
// the overlay takes every click, so the plot cannot be edited.
function showConverting(message) {
  converting.hidden = false;
  convertingText.textContent = `列を初めて使うため変換しています（${message.done + 1} / ${message.total}）：${message.column}`;
  convertingBar.max = message.total;
  convertingBar.value = message.done;
}

const events = new EventSource("/api/events");
events.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.type !== "progress") return;
  if (message.stage === "convert") {
    showConverting(message);
    return;
  }
  converting.hidden = true;
  statusLine.show(`task ${message.task}: ${message.stage}`);
};

// The overview (whole data range) as the server sent it with the size it was
// aggregated for and its decoded images, kept to go back to without a worker,
// and the meta of the result whose images are drawn.
let overview = null;
let current = null;
const legend = new Legend(
  document.getElementById("legend"),
  () => layers.draw(),
  (event) =>
    openScaleMenu(event, colorBins, setColorBins, recolor, current?.marker_size, setShapeSize),
  (event, kind, i) => {
    if (kind === "shape") {
      const level = current.overlay.levels[i];
      openShapeMenu(event, levelHeading(level), current.overlay.sizes[i], (size) =>
        setLevelSize(current.overlay.column, level, size),
      );
    } else {
      openShapeMenu(event, SIZE_HEADING, current?.marker_size, setShapeSize);
    }
  },
);
const layers = new ImageLayers(gd, legend);
const sticky = new StickyLabels(document.getElementById("scroller"), gd);
const empty = document.getElementById("empty");
// Decoded images on the canvas; freed when replaced, unless the overview's.
let shownImages = null;
// Size of the plot area that the latest request was made for, and that the
// drawn result was aggregated for.
let requestedSize = null;
let shownSize = null;
// Conditions of the local filter (`ddviz.server.plan.parse_filters`) that every
// request carries; a result's meta has those it was aggregated with.
let filters = [];
// Returns a key of conditions, from the page's or from a result's meta.
function filtersKey(list) {
  return JSON.stringify(list.map((f) => [f.column, f.range ?? null, f.levels ?? null]));
}
// How a numeric color column is cut into intervals ({n, by}), or null for a
// gradient (`ddviz.server.plan.parse_color_bins`); back to null for another color
// column. The graph last plotted, to plot again with another cutting.
let colorBins = null;
let plottedEncoding = null;
// How the smoothing lines are fitted (`ddviz.server.plan.parse_smoothing`),
// picked in the menu of their element icon; kept for every graph.
let smoothing = DEFAULT_SMOOTHING;
// Size in pixels of the markers of every series
// (`ddviz.server.plan.parse_shape_size`), picked in the menu of the points'
// element icon or of the legend's color markers; kept for every graph. Null
// for the default: larger for the overlay's shapes than for the circles of
// the points.
let shapeSize = null;
// Sizes of the shapes of single overlay levels, by overlay column and level
// name (`ddviz.server.plan.parse_shape_sizes`), picked in the menu of the
// overlay legend's markers; kept for every graph, dropped when the size of
// every series is picked.
const levelSizes = new Map();
// Wrapped panels to a row, or null to make them closest to square
// (`ddviz.server.plan.parse_wrap_cols`); back to null for another wrap column.
// The user sets it in the Wrap zone, beside its chip.
let wrapCols = null;
const wrapColsInput = document.createElement("input");
Object.assign(wrapColsInput, {
  type: "number",
  min: 1,
  step: 1,
  className: "wrap-cols",
  placeholder: "自動",
  title: "1 行のパネルの数。空なら描画領域の縦横比から、パネルが正方形に近くなる数",
});
wrapColsInput.addEventListener("change", () => {
  const n = Number(wrapColsInput.value);
  wrapCols = wrapColsInput.value !== "" && Number.isInteger(n) && n >= 1 ? n : null;
  if (wrapCols === null) wrapColsInput.value = "";
  if (plottedEncoding?.wrap) plot(plottedEncoding);
});
// Generation of the plot request in flight, or 0. A new size waits for it:
// a request for the old plot would kill its aggregation (or its conversion).
let plotting = 0;
// Bumped by every plot, view request and return to the overview, so that a
// late answer to an older request is dropped.
let generation = 0;
// Ranges of the latest view request, so that the same view is not asked twice.
let requested = { x: [], y: [] };
// Whether a mouse button is held on the plot; a result that comes during a
// drag waits for its end, so the figure does not change under the drag.
let dragging = false;
let dragEnded = null;
gd.addEventListener("mousedown", () => {
  dragging = true;
});
window.addEventListener("mouseup", () => {
  dragging = false;
  dragEnded?.();
  dragEnded = null;
});

// Resolves once no drag is going on.
function noDrag() {
  if (!dragging) return Promise.resolve();
  return new Promise((resolve) => {
    dragEnded = resolve;
  });
}

const hideHover = attachHover(gd, () => current, legend, (ms) => {
  timings.hover.push(ms);
  if (timings.hover.length % 20 === 0) setInfo();
});

// The mode bar holds zoom, pan, box select and reset, and a button that saves
// the plot's data (`datamenu.js`); pan is the starting drag mode (`dragmode` in
// the figure). It shows always, not only on hover, so that the drag mode in
// use is in sight.
const DOWNLOAD_DATA = {
  name: "downloadData",
  title: "データを保存（CSV / Parquet）",
  icon: Plotly.Icons.disk,
  click: (_, event) =>
    openDataMenu(event.currentTarget ?? event.target.closest(".modebar-btn"), () => overview?.meta.task ?? null),
};
const PLOT_CONFIG = {
  displayModeBar: true,
  displaylogo: false,
  scrollZoom: false,
  modeBarButtons: [["zoom2d", "pan2d", "select2d", "resetScale2d", DOWNLOAD_DATA]],
};

// Sets the meta of the result whose images are drawn. Only a grid laid out
// to scroll scrolls: the larger figure drawn while a new size is aggregated
// would otherwise leave scroll bars over a grid that fits.
function setCurrent(meta) {
  current = meta;
  legend.setEmpty(meta);
  elementBar.setPointsText(markerSizeText(meta));
  stage.classList.toggle("scrolls", meta.scroll);
  // The number to a row the size made, while the user sets none.
  wrapColsInput.placeholder = `自動（${meta.ncol}）`;
  sticky.set(meta);
  showHoverWarning(meta.hover);
}

// Tells, in the status bar, which hover columns a result left out to keep its
// hover files within the limit of the settings, or that it has no hover.
function showHoverWarning({ files, dropped, kept, limit_gb: limit }) {
  hoverWarning.hidden = files && !dropped.length;
  const why = `ホバー用のファイルが上限（${Number(limit.toPrecision(3))}GB）を超えるため、`;
  hoverWarning.textContent = files
    ? `${why}ホバーに出す列を ${kept.join("、")} だけにした`
    : `${why}この表示ではホバーを出さない`;
}

// Draws the images of a result on the canvas and frees the ones it replaces.
function showImages(meta, bitmaps) {
  const old = shownImages;
  shownImages = bitmaps;
  layers.set(meta, bitmaps);
  if (old && old !== bitmaps && old !== overview?.bitmaps) closeImages(old);
}

// Keeps `next` as the overview and frees the old overview's images unless drawn.
function setOverview(next) {
  const old = overview?.bitmaps;
  overview = next;
  if (old && old !== shownImages && old !== next.bitmaps) closeImages(old);
}

// Fetches and decodes the images of a result, timing it; null on failure
// (a newer result may have replaced it on the server).
async function fetchImages(meta) {
  const started = performance.now();
  try {
    const bitmaps = await loadImages(meta);
    timings.images = Math.round(performance.now() - started);
    return bitmaps;
  } catch (error) {
    console.error(error);
    return null;
  }
}

// Returns the size of the plot area, which the figure is aggregated for; a
// grid of many panels may be larger and scroll in it.
function stageSize() {
  return { width: Math.floor(stage.clientWidth), height: Math.floor(stage.clientHeight) };
}

function sameSize(a, b) {
  return a !== null && b !== null && a.width === b.width && a.height === b.height;
}

const CONVERT_RETRY_MS = 300;

// Aggregates the overview of a graph (`ddviz.server.encoding.Encoding`) and draws it.
async function plot(encoding) {
  clearSelection(false);
  const size = stageSize();
  plottedEncoding = encoding;
  const body = {
    encoding,
    ...size,
    filters,
    color_bins: colorBins,
    wrap_cols: wrapCols,
    smooth: smoothing,
    shape_size: shapeSize,
    shape_sizes: (encoding.color !== null && levelSizes.get(encoding.overlay)) || null,
  };
  requestedSize = size;
  statusLine.show("集約中…");
  const mine = ++generation;
  plotting = mine;
  const started = performance.now();
  let response;
  for (;;) {
    response = await fetch("/api/plot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    // An edit dropped while an earlier plot converts its columns is refused
    // (it would kill the conversion); it waits for the conversion's end.
    if (response.status !== 409 || mine !== generation) break;
    if ((await response.clone().json()).detail !== "converting") break;
    await new Promise((resolve) => setTimeout(resolve, CONVERT_RETRY_MS));
  }
  if (plotting === mine) plotting = 0;
  if (response.status === 409 || mine !== generation) return; // superseded by a newer request
  const text = await response.text();
  if (!response.ok) {
    converting.hidden = true;
    statusLine.error(errorText(text));
    return;
  }
  converting.hidden = true;
  timings.fetch = Math.round(performance.now() - started);
  timings.size = Math.round(text.length / 1024);
  const { figure, meta } = JSON.parse(text);
  // The images decode while plotly draws the axes.
  const images = fetchImages(meta);
  timings.task = Number(meta.task_seconds.toFixed(2));
  timings.convert = Number(meta.convert_seconds.toFixed(2));
  setOverview({ figure: structuredClone(figure), meta, size, bitmaps: null });
  requested = { x: [], y: [] };
  legend.set(meta);
  setCurrent(meta);
  shownSize = size;
  const drawStarted = performance.now();
  setPending(false);
  empty.hidden = true;
  showImages(meta, null);
  Plotly.purge(gd);
  drawnKey = figureKey(figure.data, figure.layout);
  await Plotly.newPlot(gd, figure.data, figure.layout, PLOT_CONFIG);
  timings.plot = Math.round(performance.now() - drawStarted);
  layers.attach();
  sticky.attach();
  gd.on("plotly_relayout", onRelayout);
  gd.on("plotly_selected", (event) => {
    if (!ownReact) onSelected(event);
  });
  gd.on("plotly_deselect", () => {
    if (!ownReact) clearSelection();
  });
  statusLine.show(rowsText(meta));
  const bitmaps = await images;
  if (overview?.meta !== meta) {
    closeImages(bitmaps);
    return;
  }
  overview.bitmaps = bitmaps;
  if (current === meta) showImages(meta, bitmaps);
  timings.plotAndImages = Math.round(performance.now() - drawStarted);
  setInfo();
  // The area may have changed size, or the filter, while the plot was aggregated.
  if (filtersKey(meta.filters) !== filtersKey(filters)) applyFilters();
  else if (!sameSize(stageSize(), size)) onResize();
}

// Returns the status of a result: its rows, and whether the filter left rows out.
function rowsText(meta, where = "") {
  const filtered = meta.filters.length ? "（フィルタ後）" : "";
  // Box plots without points draw only their outliers as points; smoothing
  // lines without points draw none.
  let drawn = "";
  if (meta.panels.every((p) => !p.points)) {
    drawn = meta.panels.some((p) => p.boxes.length) ? "（外れ値）" : "（点は描いていない）";
  }
  return `task ${meta.task}: ${where}${meta.rows.toLocaleString()} 行${drawn}${filtered}`;
}

// Returns whether two ranges are equal up to a small part of their span.
function sameRange(a, b) {
  const tol = Math.abs(b[1] - b[0]) * 1e-9;
  return Math.abs(a[0] - b[0]) <= tol && Math.abs(a[1] - b[1]) <= tol;
}

// Returns whether two lists of ranges (one per axis column) are equal.
function sameRanges(a, b) {
  return a.length === b.length && a.every((range, i) => sameRange(range, b[i]));
}

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

// Returns the ranges on screen of each x and y column of a result, as
// numbers (a date axis holds dates): the panels of one column share them
// (`matches`).
function shownRanges(meta) {
  const full = gd._fullLayout;
  return {
    x: meta.x_axes.map((id) => linearRange(full[axisKey(id)])),
    y: meta.y_axes.map((id) => linearRange(full[axisKey(id)])),
  };
}

// Returns `layout` with the axis ranges the user has on screen.
function withShownRanges(layout, meta) {
  const shown = shownRanges(meta);
  const out = { ...layout };
  for (const panel of meta.panels) {
    const xKey = axisKey(panel.xaxis);
    const yKey = axisKey(panel.yaxis);
    out[xKey] = { ...layout[xKey], range: shown.x[panel.x] };
    out[yKey] = { ...layout[yKey], range: shown.y[panel.y] };
  }
  return out;
}

// The drawn figure without its axis ranges. A result of the same plot and
// size has the same figure, and then only its images and ranges change:
// plotly redraws the axes of 100 panels in about 0.4s, even for `react`.
let drawnKey = null;
// The ranges this page is setting with `Plotly.relayout`, whose own
// `plotly_relayout` is not a view to aggregate.
let ownRelayout = null;
// Whether this page is drawing a new figure with `Plotly.react`, which drops
// plotly's box of the selection: its events do not drop the selection.
let ownReact = false;

function figureKey(data, layout) {
  const axes = {};
  for (const [key, value] of Object.entries(layout)) {
    axes[key] = /^[xy]axis\d*$/.test(key) ? { ...value, range: null } : value;
  }
  return JSON.stringify([data, axes]);
}

// Returns the relayout that gives every axis its range in `layout`, or null
// when the axes already have them.
function rangeUpdate(layout) {
  const update = {};
  for (const [key, value] of Object.entries(layout)) {
    if (/^[xy]axis\d*$/.test(key) && !sameRange(linearRange(gd._fullLayout[key]), value.range)) {
      update[`${key}.range`] = [...value.range];
    }
  }
  return Object.keys(update).length ? update : null;
}

// Returns `layout` with plotly's box of the selection on the panel of `meta`
// that has the box's facet levels and axis columns; a filter may have moved
// the panel or dropped it.
function withSelectionBox(layout, meta) {
  if (!selection) return layout;
  const { at, x_range: x, y_range: y } = selection.box;
  const panel = meta.panels.find((p) => panelKey(p) === at);
  if (!panel) return layout;
  const box = { type: "rect", xref: panel.xaxis, yref: panel.yaxis, x0: x[0], x1: x[1], y0: y[0], y1: y[1] };
  return { ...layout, selections: [{ ...box, line: { width: 1, dash: "dot" } }] };
}

// Draws `data` with `layout`, and the images of `meta` over it.
async function draw(data, layout, meta, bitmaps) {
  const started = performance.now();
  const key = figureKey(data, layout);
  if (key === drawnKey) {
    const update = rangeUpdate(layout);
    if (update) {
      ownRelayout = update;
      await Plotly.relayout(gd, update);
      ownRelayout = null;
    }
  } else {
    ownReact = true;
    try {
      await Plotly.react(gd, data, withSelectionBox(layout, meta));
    } finally {
      ownReact = false;
    }
    drawnKey = key;
  }
  showImages(meta, bitmaps);
  timings.react = Math.round(performance.now() - started);
}

// Marks the drawn images as a stand-in while a view is aggregated: they fade
// and a notice shows, so that they are not taken for the result. Once a
// result is drawn, the selection follows it.
const pending = document.getElementById("pending");
function setPending(on) {
  gd.classList.toggle("pending", on);
  pending.hidden = !on;
  if (!on) followSelection();
}

// The selection: the box drawn on a panel of the drawn result (its data
// ranges, its panel's facet levels and axis columns (`at`), and the index of
// that panel in the drawn result, -1 when a filter dropped it), the result
// its layer was asked for (`base`), the layer once it came, and whether the
// server holds the selection (`held`). Every panel shows the selected rows
// (`ddviz.compute.selection.selection_filter`); until the layer comes, the box shows
// them in its own panel. A filter may drop or bring back facet panels, so
// the panels' indices change: the box follows its facet levels.
let selection = null;
let selectionGeneration = 0;
const table = new SelectionTable(document.getElementById("table"));

// Returns the panel of a box from plotly's `range` (keyed by axis id), its
// bounds as numbers (a date axis gives dates).
function boxOf(meta, range) {
  const panel = meta.panels.findIndex((p) => p.xaxis in range && p.yaxis in range);
  if (panel < 0) return null;
  const { xaxis, yaxis } = meta.panels[panel];
  const full = gd._fullLayout;
  return {
    panel,
    at: panelKey(meta.panels[panel]),
    x_range: linearRange(full[axisKey(xaxis)], range[xaxis]),
    y_range: linearRange(full[axisKey(yaxis)], range[yaxis]),
  };
}

// Names a panel by its facet levels and axis columns, the same in every result of a plot.
function panelKey(panel) {
  return JSON.stringify([panel.facet, panel.x, panel.y]);
}

// Whether two results draw the same panels in the same order.
function samePanels(a, b) {
  return a.panels.length === b.panels.length && a.panels.every((p, i) => panelKey(p) === panelKey(b.panels[i]));
}

// plotly sends no range for a click beside the box, which drops it.
function onSelected(event) {
  if (!event?.range) {
    clearSelection();
    return;
  }
  if (!current) return;
  const box = boxOf(current, event.range);
  if (!box) return;
  closeImages(selection?.bitmaps);
  selection = { box, base: null, bitmaps: null, fresh: true };
  layers.setSelection({ box });
  // An aggregation in flight would be killed; the selection waits for its result.
  if (pending.hidden && !plotting) followSelection();
}

// Asks for the selected rows' layer over the drawn result, unless asked already.
async function followSelection() {
  if (!selection || !current || plotting || selection.base === current.task) return;
  const mine = ++selectionGeneration;
  const meta = current;
  const { box } = selection;
  box.panel = meta.panels.findIndex((p) => panelKey(p) === box.at);
  if (!selection.held && box.panel < 0) {
    // A filter dropped the box's panel before the server took the box.
    clearSelection();
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
  const body = selection.held ? { task: meta.task } : { task: meta.task, panel, x_range, y_range };
  const response = await fetch("/api/selection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (mine !== selectionGeneration || !selection) return;
  if (!response.ok) {
    // Killed by a newer aggregation: asked again once its result is drawn.
    selection.base = null;
    if (response.status !== 409) statusLine.error(errorText(await response.text()));
    return;
  }
  const layer = await response.json();
  let bitmaps = null;
  try {
    bitmaps = await loadImages({ task: layer.task, images: layer.images }, meta.color);
  } catch (error) {
    console.error(error);
  }
  if (mine !== selectionGeneration || !selection || !bitmaps) {
    closeImages(bitmaps);
    if (selection && mine === selectionGeneration) selection.base = null;
    return;
  }
  closeImages(selection.bitmaps);
  selection.bitmaps = bitmaps;
  selection.layer = layer;
  selection.held = true;
  layers.setSelection({ meta, bitmaps });
  statusLine.show(`選んだ行：${layer.rows.toLocaleString()} 行（${layer.task_seconds.toFixed(1)} 秒）`);
  // A new filter changes the selected rows: the table starts again.
  const key = filtersKey(meta.filters);
  if (selection.fresh || selection.filters !== key) {
    selection.fresh = false;
    selection.filters = key;
    table.show(layer.rows);
  }
}

// Drops the selection; `server` also tells the server (a new plot drops it there).
function clearSelection(server = true) {
  selectionGeneration++;
  if (!selection) return;
  closeImages(selection.bitmaps);
  selection = null;
  layers.setSelection(null);
  table.show(null);
  if (server) {
    fetch("/api/selection", { method: "DELETE" });
    if (current) statusLine.show(rowsText(current));
  }
}

// Goes back to the overview's images and ranges; no worker runs, unless the
// overview was aggregated for another size of the plot area.
async function showOverview() {
  generation++;
  requested = { x: [], y: [] };
  const { meta, size, bitmaps } = overview;
  const figure = structuredClone(overview.figure);
  setCurrent(meta);
  if (!sameSize(size, stageSize()) || filtersKey(meta.filters) !== filtersKey(filters)) {
    // The overview of the old size or filter stands in, stretched to the drawn figure.
    setPending(true);
    const { width, height } = gd._fullLayout;
    await draw(figure.data, { ...figure.layout, width, height }, meta, bitmaps);
    requestOverview();
    return;
  }
  setPending(false);
  shownSize = size;
  await draw(figure.data, figure.layout, meta, bitmaps);
  statusLine.show(rowsText(meta));
  setInfo();
}

// Whether a result is the one drawn, at the figure size drawn: a new size of
// the area that keeps the layout gets the drawn result back, with no redraw.
function isDrawn(meta, layout) {
  const full = gd._fullLayout;
  return meta.task === current.task && full.width === layout.width && full.height === layout.height;
}

// Aggregates the overview again for the current size of the plot area. The
// drawn images stand in, stretched and faded, until the result comes.
async function requestOverview() {
  const mine = ++generation;
  const size = stageSize();
  requestedSize = size;
  requested = { x: [], y: [] };
  statusLine.show("大きさに合わせて集約中…");
  setPending(true);
  const started = performance.now();
  const response = await fetch("/api/overview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...size, filters }),
  });
  if (response.status === 409 || mine !== generation) return; // superseded
  if (!response.ok) {
    setPending(false);
    statusLine.error(errorText(await response.text()));
    return;
  }
  const { figure, meta } = await response.json();
  const drawn = isDrawn(meta, figure.layout);
  const images = drawn ? Promise.resolve(shownImages) : fetchImages(meta);
  await noDrag();
  // A pan or zoom during the request or the drag supersedes it.
  await new Promise((resolve) => setTimeout(resolve));
  const bitmaps = await images;
  if (mine !== generation || !bitmaps) {
    if (!drawn) closeImages(bitmaps);
    return;
  }
  timings.viewFetch = Math.round(performance.now() - started);
  timings.viewTask = Number(meta.task_seconds.toFixed(2));
  setOverview({ figure: structuredClone(figure), meta, size, bitmaps });
  setCurrent(meta);
  shownSize = size;
  hideHover();
  if (!drawn) await draw(figure.data, figure.layout, meta, bitmaps);
  if (mine === generation) setPending(false);
  statusLine.show(rowsText(meta));
  setInfo();
}

// Aggregates the shown ranges again. Until the result comes, plotly keeps
// drawing the current images stretched to the new axes, faded, and the area
// they do not cover stays blank.
async function requestView({ x: xRanges, y: yRanges }) {
  const mine = ++generation;
  const size = stageSize();
  requestedSize = size;
  requested = { x: xRanges, y: yRanges };
  statusLine.show("表示範囲を集約中…");
  setPending(true);
  const started = performance.now();
  const response = await fetch("/api/view", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x_ranges: xRanges, y_ranges: yRanges, ...size, filters }),
  });
  if (response.status === 409 || mine !== generation) return; // superseded
  if (!response.ok) {
    setPending(false);
    statusLine.error(errorText(await response.text()));
    return;
  }
  const { figure, meta } = await response.json();
  const drawn = isDrawn(meta, figure.layout);
  const images = drawn ? Promise.resolve(shownImages) : fetchImages(meta);
  await noDrag();
  // A pan or zoom during the request or the drag supersedes it. Its relayout
  // comes after the mouseup, so let it run first.
  await new Promise((resolve) => setTimeout(resolve));
  const bitmaps = await images;
  if (mine !== generation || !bitmaps) {
    if (!drawn) closeImages(bitmaps);
    return;
  }
  timings.viewFetch = Math.round(performance.now() - started);
  timings.viewTask = Number(meta.task_seconds.toFixed(2));
  setCurrent(meta);
  shownSize = size;
  hideHover();
  // The images and the panels' placement change; the axes stay where the user put them.
  if (!drawn) await draw(figure.data, withShownRanges(figure.layout, meta), meta, bitmaps);
  if (mine === generation) setPending(false);
  statusLine.show(rowsText(meta, "表示範囲に "));
  setInfo();
}

// The panels of one x or y column share its axis (`matches`), so the view is
// the range of each column.
// A relayout during a figure change of this page is not ignored: a pan
// dropped then would be lost, leaving the axes over images of another range.
function onRelayout(event) {
  hideHover();
  if (!overview) return;
  const keys = Object.keys(event);
  if (ownRelayout && keys.every((key) => key in ownRelayout)) return;
  if (keys.some((key) => key.endsWith("autorange"))) {
    showOverview();
    return;
  }
  if (!keys.some((key) => /^[xy]axis\d*\.range/.test(key))) return;
  const shown = shownRanges(overview.meta);
  if (sameRanges(shown.x, overview.meta.x_ranges) && sameRanges(shown.y, overview.meta.y_ranges)) {
    showOverview();
    return;
  }
  if (sameRanges(shown.x, requested.x) && sameRanges(shown.y, requested.y)) return;
  requestView(shown);
}

// A new size of the plot area (the window, or a pane beside it) aggregates
// the shown range again, once the size has stopped changing. Meanwhile the
// drawn images stand in, faded; a grid that fits the area is stretched to it
// when the size settles, and a scrolled grid keeps its size.
const RESIZE_SETTLE_MS = 300;
let resizeTimer = null;

function onResize() {
  clearTimeout(resizeTimer);
  // A plot in flight checks the size when its result comes.
  if (!overview || plotting === generation) return;
  if (sameSize(stageSize(), requestedSize)) {
    // Back to the size asked for last: nothing new to aggregate.
    if (sameSize(requestedSize, shownSize)) setPending(false);
    return;
  }
  hideHover();
  setPending(true);
  resizeTimer = setTimeout(onResizeSettled, RESIZE_SETTLE_MS);
}

async function onResizeSettled() {
  if (plotting === generation) return;
  const size = stageSize();
  if (!current.scroll) {
    // The figure no longer matches a result of its size.
    drawnKey = null;
    await Plotly.relayout(gd, size);
  }
  if (requested.x.length) {
    requestView(shownRanges(current));
  } else {
    requestOverview();
  }
}

new ResizeObserver(onResize).observe(stage);

// A new filter aggregates what is shown again: the view when zoomed, else the
// overview. The levels and the axes' ranges stay those of every row, so only
// the bins change (`ddviz.compute.aggregate.aggregate`). While zoomed, the overview
// keeps its old filter until it is shown again.
function applyFilters() {
  clearTimeout(resizeTimer);
  // A plot in flight checks the filter when its result comes.
  if (!overview || plotting === generation) return;
  hideHover();
  if (requested.x.length) {
    requestView(shownRanges(current));
  } else {
    requestOverview();
  }
}

const leftPane = new LeftPane(document.getElementById("left"));
new FilterPane(
  document.getElementById("filters"),
  (conditions) => {
    filters = conditions;
    applyFilters();
  },
  (count, text) => leftPane.setFilter(count, text),
);

// Removes the figure of a graph that cannot be drawn (`drawable`).
function clearPlot() {
  clearSelection();
  generation++;
  plotting = 0;
  // A new cutting or number to a row has no graph to plot again.
  plottedEncoding = null;
  setPending(false);
  hideHover();
  Plotly.purge(gd);
  drawnKey = null;
  legend.clear();
  showImages(null, null);
  if (overview?.bitmaps) closeImages(overview.bitmaps);
  overview = null;
  current = null;
  elementBar.setPointsText(null);
  stage.classList.remove("scrolls");
  sticky.set(null);
  empty.hidden = false;
  statusLine.show("");
  hoverWarning.hidden = true;
}

// The roles a scatter plot draws (`ddviz.server.plan.drawn_columns`) and
// its elements. Overlay alone takes the place of color.
function drawnRoles(encoding) {
  const { x, y, color, row, col, wrap, elements, overlay } = encoding;
  return JSON.stringify([x, y, color ?? overlay, row, col, wrap, elements, overlay]);
}

// Whether the graph draws every row in one band along x: no x column and
// numeric y columns only (`ddviz.server.plan.one_band`).
function oneBand(encoding) {
  const numeric = (name) => builder.numeric.get(name) !== false;
  return !encoding.x.length && encoding.y.length > 0 && encoding.y.every(numeric);
}

// Whether the graph has a scatter plot (`ddviz.server.plan.drawable`).
function drawable(encoding) {
  return (encoding.x.length > 0 && encoding.y.length > 0) || oneBand(encoding);
}

// Whether a pair of the graph's axis columns can have box plots: a
// categorical x and a numeric y, or the one band
// (`ddviz.server.plan.has_box_pair`).
function hasBoxPair(encoding) {
  const numeric = (name) => builder.numeric.get(name) !== false;
  return (
    oneBand(encoding) || (encoding.x.some((x) => !numeric(x)) && encoding.y.some(numeric))
  );
}

// Whether a pair of the graph's axis columns can have smoothing lines: a
// numeric x and a numeric y (`ddviz.server.plan.has_smooth_pair`).
function hasSmoothPair(encoding) {
  const numeric = (name) => builder.numeric.get(name) !== false;
  return encoding.x.some(numeric) && encoding.y.some(numeric);
}

// Draws the markers of every series in another size, dropping the sizes of
// single overlay levels: the graph is plotted again.
function setShapeSize(size) {
  shapeSize = size;
  levelSizes.clear();
  if (plottedEncoding) plot(plottedEncoding);
}

// Draws the shapes of an overlay level in another size: the graph is plotted again.
function setLevelSize(column, level, size) {
  const sizes = levelSizes.get(column) ?? {};
  sizes[level] = size;
  levelSizes.set(column, sizes);
  if (plottedEncoding) plot(plottedEncoding);
}

// Returns the text of the size of a result's markers (its meta), for the
// points' icon: a range when overlay levels have sizes of their own.
function markerSizeText(meta) {
  const sizes = meta.overlay?.sizes.length ? meta.overlay.sizes : [meta.marker_size];
  const lo = Math.min(...sizes);
  const hi = Math.max(...sizes);
  return lo === hi ? `${lo} px` : `${lo}〜${hi} px`;
}

// Fits the smoothing lines another way: a graph with them is plotted again.
function setSmoothing(picked) {
  smoothing = picked;
  elementBar.setSmoothText(smoothingText(smoothing));
  if (plottedEncoding?.elements.includes("smooth")) plot(plottedEncoding);
}

let drawnRolesKey = drawnRoles({
  x: [],
  y: [],
  color: null,
  row: null,
  col: null,
  wrap: null,
  elements: ["points"],
  overlay: null,
});
// Cuts a numeric color column another way, or draws it as a gradient (null):
// the series change, so the graph is plotted again.
function setColorBins(bins) {
  colorBins = bins;
  if (plottedEncoding) plot(plottedEncoding);
}

// Draws the decoded images again in the scale's new colors: the overview's,
// the drawn result's and the selection layer's. Their files are still on the
// server, so no aggregation runs.
async function recolor() {
  legend.render();
  if (!overview || overview.meta.color.kind === "levels") return;
  const mine = generation;
  const shown = current;
  const layerOf = selection?.bitmaps ? selection : null;
  const [overviewImages, shownImages_, layerImages] = await Promise.all([
    overview.bitmaps ? fetchImages(overview.meta) : null,
    shown && shown !== overview.meta ? fetchImages(shown) : null,
    layerOf ? loadImages(layerOf.layer, shown.color).catch(() => null) : null,
  ]);
  if (mine !== generation) {
    for (const b of [overviewImages, shownImages_, layerImages]) closeImages(b);
    return;
  }
  if (overviewImages) {
    const old = overview.bitmaps;
    overview.bitmaps = overviewImages;
    if (current === overview.meta) showImages(current, overviewImages);
    if (old !== shownImages) closeImages(old);
  }
  if (shownImages_ && current === shown) showImages(shown, shownImages_);
  else closeImages(shownImages_);
  if (layerImages && selection === layerOf) {
    closeImages(selection.bitmaps);
    selection.bitmaps = layerImages;
    layers.setSelection({ meta: layers.selection.meta, bitmaps: layerImages });
  } else {
    closeImages(layerImages);
  }
}

// The element icons, made after the builder whose elements they set.
let elementBar = null;
const builder = new Builder(
  document.getElementById("builder"),
  document.getElementById("columns"),
  (encoding) => {
    // Elements no longer possible are turned off; that edit comes back here.
    if (elementBar?.allow({ box: hasBoxPair(encoding), smooth: hasSmoothPair(encoding) })) return;
    const key = drawnRoles(encoding);
    if (key === drawnRolesKey) return;
    const drawn = JSON.parse(drawnRolesKey);
    if ((encoding.color ?? encoding.overlay) !== drawn[2]) colorBins = null;
    if (encoding.wrap !== drawn[5]) {
      wrapCols = null;
      wrapColsInput.value = "";
      wrapColsInput.placeholder = "自動";
    }
    drawnRolesKey = key;
    if (drawable(encoding)) plot(encoding);
    else clearPlot();
  },
  { wrap: wrapColsInput },
);
elementBar = new ElementBar(
  document.getElementById("elements"),
  (elements) => builder.setElements(elements),
  (event) => openSmoothMenu(event, smoothing, setSmoothing),
  (event) => {
    if (current) openShapeMenu(event, SIZE_HEADING, current.marker_size, setShapeSize);
  },
);
elementBar.setSmoothText(smoothingText(smoothing));
await attachColumnList(document.getElementById("columns"));
showCasts(document.getElementById("casts"));
