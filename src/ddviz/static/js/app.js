// The page: drop columns on the graph builder's zones, plot, zoom and pan,
// resize, hover, and report the selected range.
import { Builder } from "./builder.js";
import { attachColumnList } from "./columns.js";
import { attachHover } from "./hover.js";
import { ImageLayers, closeImages, loadImages } from "./layers.js";
import { Legend } from "./legend.js";

const status = document.getElementById("status");
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
  status.textContent = `task ${message.task}: ${message.stage}`;
};

// The overview (whole data range) as the server sent it with the size it was
// aggregated for and its decoded images, kept to go back to without a worker,
// and the meta of the result whose images are drawn.
let overview = null;
let current = null;
const legend = new Legend(document.getElementById("legend"), () => layers.draw());
const layers = new ImageLayers(gd, legend);
const empty = document.getElementById("empty");
// Decoded images on the canvas; freed when replaced, unless the overview's.
let shownImages = null;
// Size of the plot area that the latest request was made for, and that the
// drawn result was aggregated for.
let requestedSize = null;
let shownSize = null;
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

// The mode bar holds only zoom, pan, box select and reset; pan is the
// starting drag mode (`dragmode` in the figure).
const PLOT_CONFIG = {
  displaylogo: false,
  scrollZoom: false,
  modeBarButtons: [["zoom2d", "pan2d", "select2d", "resetScale2d"]],
};

// Sets the meta of the result whose images are drawn. Only a grid laid out
// to scroll scrolls: the larger figure drawn while a new size is aggregated
// would otherwise leave scroll bars over a grid that fits.
function setCurrent(meta) {
  current = meta;
  stage.classList.toggle("scrolls", meta.scroll);
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

// Aggregates the overview of a graph (`ddviz.encoding.Encoding`) and draws it.
async function plot(encoding) {
  const size = stageSize();
  const body = { encoding, ...size };
  requestedSize = size;
  status.textContent = "集約中…";
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
    status.textContent = `エラー: ${text}`;
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
  setCurrent(meta);
  shownSize = size;
  const drawStarted = performance.now();
  setPending(false);
  empty.hidden = true;
  legend.set(encoding.color, meta.series, meta.colors);
  showImages(meta, null);
  Plotly.purge(gd);
  drawnKey = figureKey(figure.data, figure.layout);
  await Plotly.newPlot(gd, figure.data, figure.layout, PLOT_CONFIG);
  timings.plot = Math.round(performance.now() - drawStarted);
  layers.attach();
  gd.on("plotly_relayout", onRelayout);
  gd.on("plotly_selected", (event) => setInfo({ selected_range: event?.range ?? null, selected_points: event?.points?.length }));
  status.textContent = `task ${meta.task}: ${meta.rows.toLocaleString()} 行`;
  const bitmaps = await images;
  if (overview?.meta !== meta) {
    closeImages(bitmaps);
    return;
  }
  overview.bitmaps = bitmaps;
  if (current === meta) showImages(meta, bitmaps);
  timings.plotAndImages = Math.round(performance.now() - drawStarted);
  setInfo();
  // The area may have changed size while the plot was aggregated.
  if (!sameSize(stageSize(), size)) onResize();
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

// Returns the ranges on screen of each x and y column of a result: the
// panels of one column share them (`matches`).
function shownRanges(meta) {
  const full = gd._fullLayout;
  return {
    x: meta.x_axes.map((id) => [...full[axisKey(id)].range]),
    y: meta.y_axes.map((id) => [...full[axisKey(id)].range]),
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
    if (/^[xy]axis\d*$/.test(key) && !sameRange(gd._fullLayout[key].range, value.range)) {
      update[`${key}.range`] = [...value.range];
    }
  }
  return Object.keys(update).length ? update : null;
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
    await Plotly.react(gd, data, layout);
    drawnKey = key;
  }
  showImages(meta, bitmaps);
  timings.react = Math.round(performance.now() - started);
}

// Marks the drawn images as a stand-in while a view is aggregated: they fade
// and a notice shows, so that they are not taken for the result.
const pending = document.getElementById("pending");
function setPending(on) {
  gd.classList.toggle("pending", on);
  pending.hidden = !on;
}

// Goes back to the overview's images and ranges; no worker runs, unless the
// overview was aggregated for another size of the plot area.
async function showOverview() {
  generation++;
  requested = { x: [], y: [] };
  const { meta, size, bitmaps } = overview;
  const figure = structuredClone(overview.figure);
  setCurrent(meta);
  if (!sameSize(size, stageSize())) {
    // The overview of the old size stands in, stretched to the drawn figure.
    setPending(true);
    const { width, height } = gd._fullLayout;
    await draw(figure.data, { ...figure.layout, width, height }, meta, bitmaps);
    requestOverview();
    return;
  }
  setPending(false);
  shownSize = size;
  await draw(figure.data, figure.layout, meta, bitmaps);
  status.textContent = `task ${meta.task}: ${meta.rows.toLocaleString()} 行`;
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
  status.textContent = "大きさに合わせて集約中…";
  setPending(true);
  const started = performance.now();
  const response = await fetch("/api/overview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(size),
  });
  if (response.status === 409 || mine !== generation) return; // superseded
  if (!response.ok) {
    setPending(false);
    status.textContent = `エラー: ${await response.text()}`;
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
  status.textContent = `task ${meta.task}: ${meta.rows.toLocaleString()} 行`;
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
  status.textContent = "表示範囲を集約中…";
  setPending(true);
  const started = performance.now();
  const response = await fetch("/api/view", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x_ranges: xRanges, y_ranges: yRanges, ...size }),
  });
  if (response.status === 409 || mine !== generation) return; // superseded
  if (!response.ok) {
    setPending(false);
    status.textContent = `エラー: ${await response.text()}`;
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
  status.textContent = `task ${meta.task}: 表示範囲に ${meta.rows.toLocaleString()} 行`;
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

// Removes the figure of a graph that cannot be drawn (no x or no y column).
function clearPlot() {
  generation++;
  plotting = 0;
  setPending(false);
  hideHover();
  Plotly.purge(gd);
  drawnKey = null;
  legend.clear();
  showImages(null, null);
  if (overview?.bitmaps) closeImages(overview.bitmaps);
  overview = null;
  current = null;
  stage.classList.remove("scrolls");
  empty.hidden = false;
  status.textContent = "";
}

// The roles a scatter plot draws (`ddviz.plan.drawn_columns`): placing
// overlay changes nothing drawn, so it aggregates nothing.
function drawnRoles(encoding) {
  const { x, y, color, row, col } = encoding;
  return JSON.stringify([x, y, color, row, col]);
}

let drawnRolesKey = drawnRoles({ x: [], y: [], color: null, row: null, col: null });
new Builder(document.getElementById("builder"), document.getElementById("columns"), (encoding) => {
  const key = drawnRoles(encoding);
  if (key === drawnRolesKey) return;
  drawnRolesKey = key;
  if (encoding.x.length && encoding.y.length) plot(encoding);
  else clearPlot();
});
await attachColumnList(document.getElementById("columns"));
