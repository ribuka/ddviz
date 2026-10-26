// Prototype page: pick columns, plot, hover, and report the selected range.
import { attachHover } from "./hover.js";
import { attachLegendOpacity } from "./legend.js";

const form = document.getElementById("controls");
const status = document.getElementById("status");
const info = document.getElementById("info");
const gd = document.getElementById("plot");
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

async function plot() {
  const body = Object.fromEntries(
    ["x", "y", "color", "row", "col"].map((role) => [role, form.elements[role].value || null]),
  );
  body.width = Math.floor(gd.clientWidth);
  body.height = Math.floor(gd.clientHeight);
  status.textContent = "集約中…";
  const started = performance.now();
  const response = await fetch("/api/plot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 409) return; // superseded by a newer request
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
  const drawStarted = performance.now();
  Plotly.purge(gd);
  await Plotly.newPlot(gd, figure.data, figure.layout, { displaylogo: false, scrollZoom: false });
  timings.plot = Math.round(performance.now() - drawStarted);
  attachLegendOpacity(gd);
  attachHover(gd, meta, (ms) => {
    timings.hover.push(ms);
    if (timings.hover.length % 20 === 0) setInfo();
  });
  gd.on("plotly_selected", (event) => setInfo({ selected_range: event?.range ?? null, selected_points: event?.points?.length }));
  status.textContent = `task ${meta.task}: ${meta.rows.toLocaleString()} 行`;
  setInfo();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  plot();
});

await loadSchema();
plot();
