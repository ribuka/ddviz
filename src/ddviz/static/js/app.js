// Prototype page: pick columns, plot, zoom and pan, resize, hover, and report the selected range.
import { attachHover } from "./hover.js";
import { attachLegendOpacity, withLegendState } from "./legend.js";

const form = document.getElementById("controls");
const status = document.getElementById("status");
const info = document.getElementById("info");
const gd = document.getElementById("plot");
const stage = document.getElementById("stage");
const timings = { hover: [] };

const DEFAULTS = { x: "x", y: "y", color: "color", row: "g1", col: "g2" };

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

async function loadSchema() {
  const columns = await (await fetch("/api/schema")).json();
  for (const role of ["x", "y", "color", "row", "col"]) {
    const select = form.elements[role];
    if (!["x", "y"].includes(role)) select.add(new Option("(なし)", ""));
    for (const c of columns) select.add(new Option(`${c.name} (${c.dtype})`, c.name));
    select.value = DEFAULTS[role];
  }
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
// aggregated for, kept to go back to without a worker, and the meta of the
// result whose images are drawn.
let overview = null;
let current = null;
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

const hideHover = attachHover(gd, () => current, (ms) => {
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

// Returns the size of the plot area, which the figure is aggregated for; a
// grid of many panels may be larger and scroll in it.
function stageSize() {
  return { width: Math.floor(stage.clientWidth), height: Math.floor(stage.clientHeight) };
}

function sameSize(a, b) {
  return a !== null && b !== null && a.width === b.width && a.height === b.height;
}

async function plot() {
  const body = Object.fromEntries(
    ["x", "y", "color", "row", "col"].map((role) => [role, form.elements[role].value || null]),
  );
  const size = stageSize();
  Object.assign(body, size);
  requestedSize = size;
  status.textContent = "集約中…";
  const mine = ++generation;
  plotting = mine;
  const started = performance.now();
  const response = await fetch("/api/plot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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
  timings.task = Number(meta.task_seconds.toFixed(2));
  timings.convert = Number(meta.convert_seconds.toFixed(2));
  overview = { figure: structuredClone(figure), meta, size };
  requested = { x: [], y: [] };
  setCurrent(meta);
  shownSize = size;
  const drawStarted = performance.now();
  setPending(false);
  Plotly.purge(gd);
  await Plotly.newPlot(gd, figure.data, figure.layout, PLOT_CONFIG);
  timings.plot = Math.round(performance.now() - drawStarted);
  attachLegendOpacity(gd);
  gd.on("plotly_relayout", onRelayout);
  gd.on("plotly_selected", (event) => setInfo({ selected_range: event?.range ?? null, selected_points: event?.points?.length }));
  status.textContent = `task ${meta.task}: ${meta.rows.toLocaleString()} 行`;
  setInfo();
  // The area may have changed size while the plot was aggregated.
  if (!sameSize(stageSize(), size)) onResize();
}

// Returns whether two ranges are equal up to a small part of their span.
function sameRange(a, b) {
  const tol = Math.abs(b[1] - b[0]) * 1e-9;
  return Math.abs(a[0] - b[0]) <= tol && Math.abs(a[1] - b[1]) <= tol;
}

// Returns `layout` with the axis ranges the user has on screen; every panel
// shares them (`matches`).
function withShownRanges(layout) {
  const full = gd._fullLayout;
  const out = { ...layout };
  for (const key of Object.keys(layout)) {
    const axis = key.match(/^([xy])axis\d*$/);
    if (axis) out[key] = { ...layout[key], range: [...full[`${axis[1]}axis`].range] };
  }
  return out;
}

// Draws `data` with `layout`, keeping each series' legend state.
async function draw(data, layout) {
  const started = performance.now();
  await Plotly.react(gd, withLegendState(gd, data), layout);
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
  const { figure, meta, size } = structuredClone(overview);
  setCurrent(meta);
  if (!sameSize(size, stageSize())) {
    // The overview of the old size stands in, stretched to the drawn figure.
    setPending(true);
    const { width, height } = gd._fullLayout;
    await draw(figure.data, { ...figure.layout, width, height });
    requestOverview();
    return;
  }
  setPending(false);
  shownSize = size;
  await draw(figure.data, figure.layout);
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
  await noDrag();
  // A pan or zoom during the request or the drag supersedes it.
  await new Promise((resolve) => setTimeout(resolve));
  if (mine !== generation) return;
  timings.viewFetch = Math.round(performance.now() - started);
  timings.viewTask = Number(meta.task_seconds.toFixed(2));
  overview = { figure: structuredClone(figure), meta, size };
  const drawn = isDrawn(meta, figure.layout);
  setCurrent(meta);
  shownSize = size;
  hideHover();
  if (!drawn) await draw(figure.data, figure.layout);
  if (mine === generation) setPending(false);
  status.textContent = `task ${meta.task}: ${meta.rows.toLocaleString()} 行`;
  setInfo();
}

// Aggregates the shown ranges again. Until the result comes, plotly keeps
// drawing the current images stretched to the new axes, faded, and the area
// they do not cover stays blank.
async function requestView(xRange, yRange) {
  const mine = ++generation;
  const size = stageSize();
  requestedSize = size;
  requested = { x: xRange, y: yRange };
  status.textContent = "表示範囲を集約中…";
  setPending(true);
  const started = performance.now();
  const response = await fetch("/api/view", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x_range: xRange, y_range: yRange, ...size }),
  });
  if (response.status === 409 || mine !== generation) return; // superseded
  if (!response.ok) {
    setPending(false);
    status.textContent = `エラー: ${await response.text()}`;
    return;
  }
  const { figure, meta } = await response.json();
  await noDrag();
  // A pan or zoom during the request or the drag supersedes it. Its relayout
  // comes after the mouseup, so let it run first.
  await new Promise((resolve) => setTimeout(resolve));
  if (mine !== generation) return;
  timings.viewFetch = Math.round(performance.now() - started);
  timings.viewTask = Number(meta.task_seconds.toFixed(2));
  const drawn = isDrawn(meta, figure.layout);
  setCurrent(meta);
  shownSize = size;
  hideHover();
  // The images and the panels' placement change; the axes stay where the user put them.
  if (!drawn) await draw(figure.data, withShownRanges(figure.layout));
  if (mine === generation) setPending(false);
  status.textContent = `task ${meta.task}: 表示範囲に ${meta.rows.toLocaleString()} 行`;
  setInfo();
}

// Every panel shares the x and y axes (`matches`), so the first panel's
// ranges are the view.
// A relayout during a figure change of this page is not ignored: a pan
// dropped then would be lost, leaving the axes over images of another range.
function onRelayout(event) {
  hideHover();
  if (!overview) return;
  const keys = Object.keys(event);
  if (keys.some((key) => key.endsWith("autorange"))) {
    showOverview();
    return;
  }
  if (!keys.some((key) => /^[xy]axis\d*\.range/.test(key))) return;
  const xRange = [...gd._fullLayout.xaxis.range];
  const yRange = [...gd._fullLayout.yaxis.range];
  if (sameRange(xRange, overview.meta.x_range) && sameRange(yRange, overview.meta.y_range)) {
    showOverview();
    return;
  }
  if (sameRange(xRange, requested.x) && sameRange(yRange, requested.y)) return;
  requestView(xRange, yRange);
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
  if (!current.scroll) await Plotly.relayout(gd, size);
  if (requested.x.length) {
    requestView([...gd._fullLayout.xaxis.range], [...gd._fullLayout.yaxis.range]);
  } else {
    requestOverview();
  }
}

new ResizeObserver(onResize).observe(stage);

form.addEventListener("submit", (event) => {
  event.preventDefault();
  plot();
});

await loadSchema();
plot();
