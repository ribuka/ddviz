// The page: drop columns on the graph builder's zones, plot, zoom and pan,
// resize, hover, select rows with a box, and filter rows.
import {
  axisAt,
  axisKind,
  decorate,
  decorationUpdate,
  dialogKind,
  emptySettings,
  hasAngle,
  isEmpty,
  labelAt,
  openAxisDialog,
  yMarginAt,
} from "./axisdialog.js";
import { AxisDirections, ascending, oriented } from "./axisdirection.js";
import { axisKey } from "./axiskey.js";
import { bandTickUpdate, withBandTicks } from "./bandticks.js";
import { openAxisMenu } from "./axismenu.js";
import { AxisScales, isLogAxis, toValues } from "./axisscale.js";
import { Builder } from "./builder.js";
import { showCasts } from "./casts.js";
import { colorsChanged, isMissingLevel, keepPicked, levelColors, pickColor } from "./colorscale.js";
import { openColumnMenu } from "./columnmenu.js";
import { attachColumnList } from "./columns.js";
import { openDataMenu } from "./datamenu.js";
import { ElementBar } from "./elements.js";
import { FilterPane, filtersKey, RestorePoint } from "./filters.js";
import { drawable, drawnRoles, hasBoxPair, hasSmoothPair } from "./graph.js";
import { attachHover } from "./hover.js";
import { ImageLayers, closeImages, loadImages } from "./layers.js";
import { fitBottom, fitMargin, MARGIN_BOTTOM, MARGIN_LEFT, neededBottom, neededMargin } from "./leftmargin.js";
import { LeftPane } from "./leftpane.js";
import { Legend } from "./legend.js";
import { levelText } from "./names.js";
import { MemoryMeter } from "./memory.js";
import { showSaveResult, StatusLine, Toasts, errorText } from "./notice.js";
import { openPlotMenu } from "./plotmenu.js";
import { PlotOptions } from "./plotoptions.js";
import {
  axisCoordinates,
  figureKey,
  rangeUpdate,
  sameAxes,
  sameOrder,
  sameRange,
  sameRanges,
  sameSize,
  shownRanges,
  withRanges,
} from "./ranges.js";
import { markerSizeText, rowsText } from "./resulttext.js";
import { Saves } from "./saves.js";
import { openScaleMenu } from "./scalemenu.js";
import { BoxSelection } from "./boxselection.js";
import { LINE_HEADING, LINE_WIDTHS, levelHeading, openShapeMenu, SIZE_HEADING } from "./shapemenu.js";
import { openSmoothMenu, smoothingText } from "./smoothmenu.js";
import { StickyLabels } from "./sticky.js";
import { SelectionTable } from "./table.js";
import { forPlotly, linearRange, plotlyRange } from "./temporal.js";
import { closeWrapMenu, openWrapMenu, setWrapAuto } from "./wrapmenu.js";
import { attachZoneMenu } from "./zonemenu.js";

const toasts = new Toasts(document.getElementById("toasts"));
const statusLine = new StatusLine(document.getElementById("status"), toasts);
// The saves of the plot's data; the table fetches the pages refused while
// one was written.
const saves = new Saves(toasts, () => table.exportEnded());
// The desktop window saves the plot's data to the Downloads folder by itself
// and calls these with how far it got and how it ended
// (ddviz.desktop.downloads); a browser (`--port`) saves it as its own
// download and never calls them.
window.ddvizSaveProgress = (progress) => saves.transferProgress(progress);
window.ddvizSaved = (result) => {
  if (!saves.saved(result)) showSaveResult(toasts, result);
};
// The memory in use, fetched as soon as the page shows and then about every second.
new MemoryMeter(document.getElementById("memory-backend"), document.getElementById("memory-frontend")).fetch();
const hoverWarning = document.getElementById("hover-warning");
const logWarning = document.getElementById("log-warning");
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
// the cover takes every click, so the plot cannot be edited.
function showConverting(message) {
  converting.hidden = false;
  convertingText.textContent = `列を初めて使うため変換しています（${message.done + 1} / ${message.total}）：${message.column}`;
  convertingBar.max = message.total;
  convertingBar.value = message.done;
}

// What each stage of a plot pool's task does, as the status shows it while
// the task runs. The task number stays internal (Issue #134).
const STAGES = {
  schema: "列を読み込み中…",
  levels: "範囲と水準を調べ中…",
  colors: "フィルタ後の Color の水準を調べ中…",
  facets: "パネルの水準を調べ中…",
  boxes: "箱ひげを計算中…",
  smooth: "平滑化を計算中…",
  lines: "点を結ぶ線を計算中…",
  bins: "点を集約中…",
  rows: "ホバー用のデータを読み込み中…",
  selection: "選んだ行を集約中…",
  raster: "画像を描画中…",
  write: "結果を書き出し中…",
};

const events = new EventSource("/api/events");
events.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.type !== "progress") return;
  if (message.export !== undefined) {
    saves.exportProgress(message);
    return;
  }
  if (message.stage === "convert") {
    showConverting(message);
    return;
  }
  converting.hidden = true;
  statusLine.show(STAGES[message.stage] ?? "処理中…");
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
    openScaleMenu(event, options.colorBins, setColorBins, recolor, options.sharedSize(current), setShapeSize),
  (event, kind, i) => {
    if (kind === "shape") {
      const { column, levels, sizes, shapes, choices } = current.symbol;
      const level = levels[i];
      const heading = levelHeading(levelText(level, levels));
      openShapeMenu(event, heading, sizes[i], (size) => setLevelSize(column, level, size), {
        shape: { current: shapes[i], choices, onPick: (shape) => setLevelShape(column, level, shape) },
      });
    } else if (current.color.kind === "bins" && !isMissingLevel(current, i)) {
      // The intervals take their colors from the scale; the missing level
      // takes its own, as a categorical level.
      openScaleMenu(event, options.colorBins, setColorBins, recolor, options.sharedSize(current), setShapeSize);
    } else {
      const level = current.series[i];
      openShapeMenu(event, SIZE_HEADING, options.sharedSize(current), setShapeSize, {
        color: { current: levelColors(current)[i], onPick: (color) => setLevelColor(level, color) },
      });
    }
  },
);
const layers = new ImageLayers(gd, legend);
// The opacity of the legend's inactive series (`plot.legend.inactive_opacity`).
fetch("/api/settings")
  .then((response) => (response.ok ? response.json() : null))
  .then((settings) => {
    if (!settings) return;
    legend.inactiveOpacity = settings.inactive_opacity;
    layers.draw();
  });
const sticky = new StickyLabels(document.getElementById("scroller"), gd, (meta, role, index) =>
  angleOn(meta, role, index),
);
const builderRoot = document.getElementById("builder");
const yZone = builderRoot.querySelector(':scope > .zone[data-role="y"]');
// The elements of the axes' left margin outside the plot (`axisHit`): the
// gap between the y zone and the plot area is the builder's, the stage's or
// the scroller's.
const MARGIN_TARGETS = [builderRoot, ...["stage", "scroller", "canvas"].map((id) => document.getElementById(id))];
const empty = document.getElementById("empty");
// Over a plot whose whole result has no rows, which draws empty panels.
const noRows = document.getElementById("no-rows");
// Decoded images on the canvas; freed when replaced, unless the overview's.
let shownImages = null;
// Size of the plot area that the latest request was made for, and that the
// drawn result was aggregated for, with the left margin (`stageSize`).
let requestedSize = null;
let shownSize = null;
// Left margin the y tick labels of the drawn figure need (`leftmargin.js`),
// as measured when a plot, a view or the axis settings were last settled;
// a request asks for it, within the area's width (`stageSize`).
let leftMargin = MARGIN_LEFT;
// Bottom margin the x tick labels at an angle set need, as `leftMargin`.
let bottomMargin = MARGIN_BOTTOM;
// Conditions of the local filter (`ddviz.server.plan.parse_filters`) that every
// request carries; a result's meta has those it was aggregated with.
let filters = [];
// The settings of the plot requests that are not the graph's (`PlotOptions`).
const options = new PlotOptions();
// The graph last plotted, to plot again with other settings.
let plottedEncoding = null;
// Generation of the plot request in flight, or 0. A new size waits for it:
// a request for the old plot would kill its aggregation (or its conversion).
let plotting = 0;

// Marks the plot area busy while a plot is in flight or the page waits for
// a result of a view or a new size (`setPending`), at once and also while a
// new size or margin waits `RESIZE_SETTLE_MS` before it is aggregated. The
// E2E tests wait for its end: the status shows no such state as a whole.
function markBusy() {
  gd.classList.toggle("busy", waiting || plotting !== 0);
}
// Bumped by every plot, view request and return to the overview, so that a
// late answer to an older request is dropped.
let generation = 0;
// Ranges of the latest view request, so that the same view is not asked twice.
let requested = { x: [], y: [] };
// Whether a mouse button is held on the plot; a result that comes during a
// drag waits for its end, so the figure does not change under the drag.
let dragging = false;
let dragEnded = null;
// A right button press does not reach plotly: it would count toward a double
// click (which resets the axes) and, in Box Select, drop the selection. The
// right click opens the plot's menu instead (`plotmenu.js`).
gd.addEventListener(
  "mousedown",
  (event) => {
    if (event.button === 2) event.stopPropagation();
  },
  { capture: true },
);
gd.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  if (!gd._fullLayout || event.target.closest(".modebar")) return;
  hideHover();
  // On the tick labels of an axis, the menu of its column (`axismenu.js`).
  const hit = current && axisHit(event);
  if (hit) {
    openAxisMenuOf(event, hit);
    return;
  }
  openPlotMenu(event, gd);
});
// The left margin of the y axes reaches out of the plot, over the gap
// between the plot area and the y zone (`axisHit`): a right click there
// opens the axis's menu too. One on the plot is the handler's above.
builderRoot.addEventListener("contextmenu", (event) => {
  if (gd.contains(event.target)) return;
  const hit = current && gd._fullLayout && axisHit(event);
  if (!hit) return;
  event.preventDefault();
  hideHover();
  openAxisMenuOf(event, hit);
});

// Opens the menu of the axis column `hit` (`axisHit`) of the result drawn.
function openAxisMenuOf(event, { axis, index }) {
  const meta = current;
  const column = meta[`${axis}_columns`][index];
  openAxisMenu(event, {
    axis,
    column,
    log: meta[`${axis}_log`][index],
    loggable: meta[`${axis}_loggable`][index],
    onLog: (log) => setAxisLog(meta, axis, column, log),
    reversed: axisDirections.isReversed(axis, column),
    onReverse: (reversed) => setAxisReversed(axis, column, reversed),
  });
}
gd.addEventListener("mousedown", () => {
  dragging = true;
});

// The settings of the axis columns with a dialog (`axisdialog.js`: numeric
// and temporal), by column name: their ticks, the format of their labels
// and reference lines, kept for every graph that draws the column on such
// an axis (a duration's on a linear one). The range set
// in the dialog is a view, as a zoom's: going back to the overview drops it.
const axisSettings = new Map();
const settingsOf = (column) => axisSettings.get(column);
// The angle of the major tick labels of each x and y column (`hasAngle`:
// linear numeric and categorical axes), in degrees, by role and column: a
// column on both x and y has one of each. Every panel of the role's
// column draws it; it stays through zooms and graphs until the page
// reloads. A column without one has plotly's automatic labels.
const axisAngles = new Map();
const angleOf = (role, column) => axisAngles.get(`${role}:${column}`) ?? null;
// The angle drawn on the axis column `index` of `role` of `meta`, or null.
function angleOn(meta, role, index) {
  return hasAngle(meta, role, index) ? angleOf(role, meta[`${role}_columns`][index]) : null;
}
// A double click on the tick labels of an axis with a dialog (`dialogKind`) opens it
// instead of plotly's autorange of that axis. plotly counts the presses
// itself, within its `doubleClickDelay`, so the second press does not reach
// it. The wait here is plotly's own, read on each press, so that every pair
// plotly would count as a double click opens the dialog, whatever plotly's
// version or config. The presses are taken on the builder, before plotly's
// handlers, as the axes' left margin reaches out of the plot (`axisHit`).
let axisPress = null;
builderRoot.addEventListener(
  "mousedown",
  (event) => {
    if (event.button !== 0) return;
    const hit = current && gd._fullLayout ? axisUnder(event) : null;
    const last = axisPress;
    axisPress = null;
    if (!hit) return;
    // The strips let the pointer through to the plot area below: plotly
    // would take the first press as one on the plot, which clears a Box
    // Select's selection. A press on a strip's numeric axis is the axis's.
    if (hit.strip) event.stopPropagation();
    const near = last && Math.hypot(event.clientX - last.x, event.clientY - last.y) <= 4;
    if (near && last.axis === hit.axis && last.index === hit.index && event.timeStamp - last.time < gd._context.doubleClickDelay) {
      event.stopPropagation();
      event.preventDefault();
      hideHover();
      openAxis(hit);
      return;
    }
    axisPress = { ...hit, x: event.clientX, y: event.clientY, time: event.timeStamp };
  },
  { capture: true },
);

// Returns the axis column with a dialog (`dialogKind`) whose tick labels are under a pointer
// event, as `{axis, index}`, or null: in the strips of a grid that scrolls
// (`sticky.js`), which let the pointer through to the panels, or on plotly's
// own labels.
function axisUnder(event) {
  const hit = axisHit(event);
  return hit && dialogKind(current, hit.axis, hit.index) ? hit : null;
}

// Returns the axis column whose tick labels are under a pointer event, of
// any kind, as `{axis, index}` (with `strip: true` in a strip of a grid that
// scrolls), or null (`axisUnder`). A y axis also takes
// its whole left margin, from the y zone's right edge (the zone keeps its
// chips and drops) to the plot area of the leftmost panel at that height:
// in a grid that scrolls, the left strip and the gap left of it
// (`sticky.js`), which the strip shows the leftmost panels' labels of
// whatever the scroll; otherwise the figure's margin and the gap
// (`yMarginAt`). Other UI over the margin (the mode bar, the table) keeps
// its own.
function axisHit(event) {
  const { clientX, clientY, target } = event;
  const open = gd.contains(target) ? !target.closest(".modebar") : MARGIN_TARGETS.includes(target);
  if (!open) return null;
  const from = yZone.getBoundingClientRect().right;
  const strip = sticky.axisAt(clientX, clientY, from);
  if (strip) return { axis: strip.axis, index: strip.axis === "x" ? strip.panel.x : strip.panel.y, strip: true };
  if (sticky.shown) return axisAt(event, gd, current);
  return (
    axisAt(event, gd, current) ??
    yMarginAt(clientX, clientY, gd, current, from) ??
    labelAt(clientX, clientY, gd, current)
  );
}

// The scale of each x and y column while the input is open (`axisscale.js`).
const axisScales = new AxisScales();

// The direction of each x and y column while the input is open (`axisdirection.js`).
const axisDirections = new AxisDirections();

// Reverses the axes of a column, or puts them back, on the result drawn: only
// their direction changes, at the shown range. Nothing is aggregated or
// asked of the server, and the selection stays, unless the labels need
// another left margin (`followMargin`).
async function setAxisReversed(axis, column, reversed) {
  axisDirections.set(axis, column, reversed);
  if (!current || !gd._fullLayout) return;
  const meta = current;
  const update = {};
  meta.panels.forEach((panel) => {
    if (meta[`${axis}_columns`][panel[axis]] !== column) return;
    const key = axisKey(panel[`${axis}axis`]);
    const full = gd._fullLayout[key];
    if (!full) return;
    const range = oriented(linearRange(full), reversed);
    if (!sameOrder(linearRange(full), range)) update[`${key}.range`] = plotlyRange(full, range);
  });
  if (!Object.keys(update).length) return;
  hideHover();
  ownRelayout = update;
  try {
    await Plotly.relayout(gd, update);
  } finally {
    ownRelayout = null;
  }
  if (meta === current) followMargin(false);
}

// Returns `layout` with the axis ranges (ascending) given the direction of
// their columns (`axisdirection.js`).
function orientedLayout(layout, meta) {
  const out = { ...layout };
  for (const [id, reversed] of Object.entries(axisDirections.byAxis(meta))) {
    const key = axisKey(id);
    if (out[key]?.range) out[key] = { ...out[key], range: oriented(out[key].range, reversed) };
  }
  return out;
}

// Puts an axis column of the drawn result `meta` on a log or a linear axis:
// the graph is plotted again, with the column's axis over its whole range
// (its coordinates changed) and the other columns' axes at their shown
// ranges (`carriedView`). A refusal (no positive value) keeps the drawn
// plot, its selection and the scale.
async function setAxisLog(meta, axis, column, log) {
  if (meta !== current || !plottedEncoding) return;
  axisScales.set(axis, column, log);
  if ((await plot(plottedEncoding)) === "refused") axisScales.set(axis, column, !log);
}

// Opens the dialog of the axis column `index` of `axis` ("x" or "y") of the drawn result.
function openAxis({ axis, index }) {
  const column = current[`${axis}_columns`][index];
  const full = gd._fullLayout[axisKey(current[`${axis}_axes`][index])];
  openAxisDialog({
    title: `${axis.toUpperCase()} 軸: ${column}`,
    kind: dialogKind(current, axis, index),
    range: ascending(linearRange(full)),
    settings: settingsOf(column) ?? emptySettings(),
    // plotly's interval of the ticks drawn, for the unit of a temporal one.
    drawn: full.dtick,
    angle: angleOf(axis, column),
    onApply: (settings, picked, angle) => applyAxis(axis, column, settings, picked, angle),
  });
}

// Keeps the settings of an axis column and draws them, with the range
// `picked` when it differs from the shown one: the view is aggregated
// again, as after a zoom. The drawn result may have changed since the
// dialog opened: the range goes to the column's axis, if it still has a
// dialog (`axisKind`), in linear units (milliseconds on a date axis).
// The angle of the labels (null for plotly's own; undefined from a dialog
// without one) is the column's in that role. A categorical axis has no
// settings nor range (null): only its angle changes.
async function applyAxis(axis, column, settings, picked, angle) {
  if (settings) {
    if (isEmpty(settings)) axisSettings.delete(column);
    else axisSettings.set(column, settings);
  }
  if (angle === null) axisAngles.delete(`${axis}:${column}`);
  else if (angle !== undefined) axisAngles.set(`${axis}:${column}`, angle);
  if (!current || !gd._fullLayout) return;
  const meta = current;
  const update = decorationUpdate(meta, settingsOf, angleOf);
  ownRelayout = update;
  try {
    await Plotly.relayout(gd, update);
  } finally {
    ownRelayout = null;
  }
  if (meta !== current) return;
  const index = meta[`${axis}_columns`].indexOf(column);
  const key = index < 0 || !axisKind(meta, axis, index) ? null : axisKey(meta[`${axis}_axes`][index]);
  const full = key && gd._fullLayout[key];
  if (!full || !picked || sameRange(ascending(linearRange(full)), picked)) {
    // The ticks' labels changed at the same range.
    followMargin(false);
    return;
  }
  // A new range is a view (`onRelayout`), which measures the margin.
  const range = oriented(picked, axisDirections.isReversed(axis, column));
  await Plotly.relayout(gd, { [`${key}.range`]: plotlyRange(full, range) });
}
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
    openDataMenu(event.currentTarget ?? event.target.closest(".modebar-btn"), () => overview?.meta.task ?? null, saves),
};
const PLOT_CONFIG = {
  displayModeBar: true,
  displaylogo: false,
  scrollZoom: false,
  // A click on an axis's end would open plotly's box to type that end, and
  // take the second press of a double click there: the axis dialog
  // (`axisdialog.js`) sets the range instead.
  showAxisRangeEntryBoxes: false,
  modeBarButtons: [["zoom2d", "pan2d", "select2d", "resetScale2d", DOWNLOAD_DATA]],
};

// Sets the meta of the result whose images are drawn. Only a grid laid out
// to scroll scrolls: the larger figure drawn while a new size is aggregated
// would otherwise leave scroll bars over a grid that fits. The legend shows
// its levels (`Legend.set`: other series than the legend's start with every
// level active), unless `legend` is false: the legend then stays as it is,
// for a result that only stands in until another comes.
function setCurrent(meta, { legend: withLegend = true } = {}) {
  current = meta;
  if (withLegend) legend.set(meta);
  elementBar.setPointsText(markerSizeText(meta));
  elementBar.setLineText(meta.line_width === null ? null : `${meta.line_width} px`);
  stage.classList.toggle("scrolls", meta.scroll);
  options.wrapAuto = meta.wrap_auto_cols;
  setWrapAuto(options.wrapAuto);
  sticky.set(meta);
  showHoverWarning(meta.hover);
  showLogWarning(meta.nonpositive);
  builder.layout();
}

// Returns the span along the axis (`[start, end]`, client coordinates) of
// the drawn axis of each X or Y column, the first panel's of each (the
// leftmost facet column's x axes, the top facet row's y axes), for the
// chips and drops of the role (`Builder.setAxes`). Null without a figure,
// when the drawn columns are not the role's in its order (a plot of the
// new ones is pending), or when the figure scrolls in that direction: the
// axes then move away from the zone.
function drawnAxes(role) {
  const meta = current;
  const full = gd._fullLayout;
  if (!meta || !full) return null;
  const drawn = meta[`${role}_columns`];
  const placed = builder.placed(role);
  if (drawn.length !== placed.length || drawn.some((column, i) => column !== placed[i])) return null;
  const scroller = document.getElementById("scroller");
  const scrolls =
    role === "x" ? scroller.scrollWidth > scroller.clientWidth : scroller.scrollHeight > scroller.clientHeight;
  if (meta.scroll && scrolls) return null;
  const origin = gd.getBoundingClientRect();
  const spans = [];
  for (const id of meta[`${role}_axes`]) {
    const axis = full[axisKey(id)];
    if (!axis?._length) return null;
    const start = (role === "x" ? origin.left : origin.top) + axis._offset;
    spans.push([start, start + axis._length]);
  }
  return spans;
}

// Tells, in the status bar, which log axis columns have rows left out for a
// value that is not positive (`ddviz.compute.aggregate.Aggregation.nonpositive`).
// It stays with the result drawn, beside the progress and the rows.
function showLogWarning(nonpositive) {
  logWarning.hidden = !nonpositive?.length;
  if (logWarning.hidden) return;
  const names = nonpositive.map(([axis, column]) => `${axis.toUpperCase()} の ${column}`).join("、");
  logWarning.textContent = `対数表示のため、${names} の0以下の値を持つ行を描画対象から除外しています`;
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
  showNoRows(next.meta);
  if (old && old !== shownImages && old !== next.bitmaps) closeImages(old);
}

// Tells, over the plot, that its whole result has no rows: the filter's
// conditions leave none, or the drawn columns have no values together. A
// zoomed view without rows does not count: the legend tells of that.
function showNoRows(meta) {
  noRows.hidden = meta.rows !== 0;
  noRows.textContent = meta.filters.length ? "フィルタの条件に合う行が無い" : "描く列に値のある行が無い";
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

// Returns the size of the plot area, which the figure is aggregated for, and
// the left and bottom margins it is asked for (`leftMargin` within its
// width, `bottomMargin` within its height); a grid of many panels may be
// larger and scroll in it.
function stageSize() {
  const width = Math.floor(stage.clientWidth);
  const height = Math.floor(stage.clientHeight);
  return {
    width,
    height,
    margin_left: fitMargin(leftMargin, width),
    margin_bottom: fitBottom(bottomMargin, height),
  };
}

// Measures the left margin the y tick labels of the figure drawn need, and
// the bottom margin its x tick labels at an angle set need
// (`leftmargin.js`), and keeps them as `leftMargin` and `bottomMargin`. A
// plot, a view or axis settings once settled take them as measured: they
// grow or shrink. Within an operation, the result drawn for the margins
// asked for may need more (its panels and their ticks changed): `grow`
// keeps only a larger margin, and a smaller one waits for the next
// operation. Returns whether either changed.
function measureMargin(grow) {
  const angled = (meta, role, index) => angleOn(meta, role, index) !== null;
  const left = neededMargin(gd, current, sticky, angled);
  const bottom = neededBottom(gd, current, sticky, angled);
  if (left === null || bottom === null) return false;
  const nextLeft = grow ? Math.max(left, leftMargin) : left;
  const nextBottom = grow ? Math.max(bottom, bottomMargin) : bottom;
  if (nextLeft === leftMargin && nextBottom === bottomMargin) return false;
  leftMargin = nextLeft;
  bottomMargin = nextBottom;
  return true;
}

// Measures the left margin (`measureMargin`), and aggregates the shown
// figure again for a new one, as for a new size of the area (`onResize`).
// The same margin, or one that its width does not let grow, asks nothing.
function followMargin(grow) {
  if (measureMargin(grow)) onResize();
}

const CONVERT_RETRY_MS = 300;

// Whether the server may hold a result that the page did not draw: a plot
// whose answer was lost, or that failed after the server replaced its
// results (its images did not come, or it could not be drawn). A failure
// then plots the committed graph again, back at the drawn view and
// selection, so that the server's results are those drawn.
let serverAhead = false;
// Whether the axes were zoomed or panned while a plot was in flight: no view
// is asked for meanwhile, so a failed plot asks for it (`resumeShown`).
let movedWhilePlotting = false;

// Aggregates the overview of a graph (`ddviz.server.encoding.Encoding`) and draws it.
// The graph and the state derived from it are a candidate (`Builder`) until
// its result is drawn with its images: only then are they committed, the
// selection dropped and the drawn figure, legend and ranges replaced. A
// failure keeps the drawn figure, its ranges, legend and selection, and
// rolls the zones back to the last committed graph (`plotFailed`). Returns
// the meta drawn, "refused" on a failure, or null when a newer request
// superseded it. `restoring` plots the committed graph again after a
// failure, leaving the error shown; `keep` (`keptView`) is the view and the
// selection it draws again.
async function plot(encoding, { restoring = false, keep = null } = {}) {
  if (!restoring) statusLine.release();
  const size = stageSize();
  plottedEncoding = encoding;
  const candidate = builder.snapshot();
  const body = {
    encoding,
    ...size,
    filters,
    ...options.request(encoding),
    axis_scales: axisScales.request(encoding),
  };

  // The filter pane's state of these conditions, which the pane goes back to
  // once the result is drawn (`RestorePoint`).
  const filterCandidate = restorePoint.propose(filterPane.sent);
  const askedSize = requestedSize;
  requestedSize = size;
  statusLine.show("集約中…");
  const mine = ++generation;
  // The plot is in flight until it is drawn or has failed, its images
  // included: meanwhile no view, size or selection is asked for, which would
  // supersede it or kill its task.
  plotting = mine;
  markBusy();
  const settled = () => {
    if (plotting === mine) plotting = 0;
    markBusy();
  };
  const started = performance.now();
  let response = null;
  let text;
  try {
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
    text = await response.text();
  } catch (error) {
    console.error(error);
    settled();
    if (mine !== generation) return null;
    // The answer was lost: the server may have taken the plot.
    serverAhead = true;
    return plotFailed(`描画の要求に失敗した（${error.message}）`, askedSize, restoring);
  }
  // Superseded by a newer request. The server drops a plot that a newer plot
  // superseded while it ran (409), but not one it finished before.
  if (mine !== generation) {
    if (response.ok) supersededDone(text);
    return null;
  }
  if (!response.ok) {
    settled();
    // A cancel that no newer request of this page made is a failure too.
    return plotFailed(response.status === 409 ? "描画が中断された" : errorText(text), askedSize, restoring);
  }
  converting.hidden = true;
  // The server's results are this plot's until it is drawn.
  serverAhead = true;
  let figure;
  let meta;
  try {
    ({ figure, meta } = JSON.parse(text));
  } catch (error) {
    console.error(error);
    settled();
    return plotFailed(`描画の応答を読めなかった（${error.message}）`, askedSize, restoring);
  }
  timings.fetch = Math.round(performance.now() - started);
  timings.size = Math.round(text.length / 1024);
  timings.task = Number(meta.task_seconds.toFixed(2));
  timings.convert = Number(meta.convert_seconds.toFixed(2));
  // The images come before the drawn figure changes: a failure keeps it.
  const bitmaps = await fetchImages(meta);
  if (mine !== generation) {
    // A newer request decides; the server holds this result (`serverAhead`).
    closeImages(bitmaps);
    return null;
  }
  if (!bitmaps) {
    settled();
    return plotFailed("図の画像を読み込めなかった", askedSize, restoring);
  }
  const kept = keptView();
  // The ranges zoomed of the axes this edit kept, read just before the switch.
  const carried = keep ? null : carriedView(meta);
  const drawStarted = performance.now();
  try {
    // The selection and the shapes of another symbol column go with the drawn plot.
    boxSelection.clear(false);
    movedWhilePlotting = false;
    setOverview({ figure: structuredClone(figure), meta, size, bitmaps });
    requested = { x: [], y: [] };
    // The legend changes below, once the figure is drawn.
    setCurrent(meta, { legend: false });
    shownSize = size;
    setPending(false);
    empty.hidden = true;
    showImages(meta, null);
    // A plot drawn again after a failure has the view and the box drawn before.
    const view = keep && sameAxes(keep, meta) ? keep : carried;
    if (view?.box) boxSelection.restore(view.box);
    const shaped = (ranged) => withBandTicks(orientedLayout(decorate(ranged, meta, settingsOf, angleOf), meta), meta);
    const layout = shaped(figure.layout);
    drawnKey = figureKey(figure.data, layout);
    Plotly.purge(gd);
    await Plotly.newPlot(gd, figure.data, forPlotly(boxSelection.withBox(layout, meta)), PLOT_CONFIG);
    // The view's ranges go on after the whole ones: plotly keeps the ranges
    // of its first draw for Reset axes and a double click.
    const zoomedUpdate = view?.zoomed && rangeUpdate(gd, shaped(withRanges(figure.layout, meta, view.ranges)));
    if (zoomedUpdate) await Plotly.relayout(gd, zoomedUpdate);
    timings.plot = Math.round(performance.now() - drawStarted);
    // The legend and the colors and shapes picked change once the figure is
    // drawn: a figure that fails keeps them for the graph drawn again.
    legend.set(meta);
    // The colors picked for the levels stay while the color column does.
    keepPicked(meta.color.column);
    // The shapes picked stay while the symbol column does.
    options.pickedShapes(encoding.symbol);
    layers.attach();
    sticky.attach();
    // The chips of X and Y follow the axes drawn now and on every later draw.
    for (const event of ["plotly_afterplot", "plotly_relayout"]) gd.on(event, () => builder.layout());
    builder.layout();
    gd.on("plotly_relayout", onRelayout);
    gd.on("plotly_selected", (event) => {
      if (!ownReact) boxSelection.pick(event);
    });
    gd.on("plotly_deselect", () => {
      if (!ownReact) boxSelection.clear();
    });
    showImages(meta, bitmaps);
    if (view?.box) layers.setSelection({ box: view.box });
    // The figure drawn is this graph's: a later failure comes back to it.
    builder.commit(candidate);
    restorePoint.confirm(filterCandidate);
    serverAhead = false;
    settled();
    showRows(meta);
    timings.plotAndImages = Math.round(performance.now() - drawStarted);
    setInfo();
    // The labels of the new figure set its margin; a new one is aggregated
    // as a new size is (below), or with the view drawn again.
    measureMargin(false);
    if (view?.zoomed) {
      requestView(view.ranges);
      return meta;
    }
  } catch (error) {
    console.error(error);
    settled();
    if (overview?.bitmaps !== bitmaps) closeImages(bitmaps);
    if (mine !== generation) return null;
    return plotFailed(`図を描けなかった（${error.message}）`, askedSize, restoring, kept);
  }
  // The area may have changed size, or the filter, while the plot was aggregated.
  if (filtersKey(meta.filters) !== filtersKey(filters)) applyFilters();
  else if (!sameSize(stageSize(), size)) onResize();
  else boxSelection.follow();
  return meta;
}

// Returns the view and the selection drawn now, for a plot of the same
// graph to draw again (`plot`'s `keep`): the ranges of each x and y column
// (`shownRanges`), whether they are zoomed from the overview's, and the
// selection's box. Null without a figure.
function keptView() {
  if (!overview || !gd._fullLayout) return null;
  const ranges = shownRanges(gd, overview.meta);
  const { x_ranges: x, y_ranges: y } = overview.meta;
  const zoomed = !(sameRanges(ranges.x, x) && sameRanges(ranges.y, y));
  return { ranges, zoomed, box: boxSelection.state ? structuredClone(boxSelection.state.box) : null };
}

// Returns the view of a new result `meta` that keeps the drawn figure's
// zoomed ranges (`shownRanges`): an axis column keeps its range while it
// stays in its role on the same coordinates (`axisCoordinates`), unless it
// was shown over its whole range; any other axis column has the new whole
// range. Null when no range is kept, or without a figure.
function carriedView(meta) {
  if (!overview || !gd._fullLayout) return null;
  const old = overview.meta;
  const shown = shownRanges(gd, old);
  const ranges = { x: [], y: [] };
  let zoomed = false;
  for (const role of ["x", "y"]) {
    meta[`${role}_columns`].forEach((column, i) => {
      const whole = meta[`${role}_ranges`][i];
      const j = old[`${role}_columns`].indexOf(column);
      const range = j < 0 ? null : shown[role][j];
      const keeps =
        range &&
        !sameRange(range, old[`${role}_ranges`][j]) &&
        axisCoordinates(old, role, j) === axisCoordinates(meta, role, i) &&
        !sameRange(range, whole);
      ranges[role].push(keeps ? range : whole);
      zoomed ||= Boolean(keeps);
    });
  }
  return zoomed ? { ranges, zoomed, box: null } : null;
}

// A superseded plot that the server finished before the newer request came
// replaced the server's results, unless a newer plot's result replaced them
// since (a later task): the drawn graph is plotted again, now or on the
// failure of the plot in flight (`serverAhead`).
function supersededDone(text) {
  if (!overview) return;
  let task;
  try {
    task = JSON.parse(text).meta.task;
  } catch {
    return;
  }
  if (task <= overview.meta.task) return;
  if (plotting) serverAhead = true;
  else if (plottedEncoding) plot(plottedEncoding, { restoring: true, keep: keptView() });
}

// Tells of a failed plot in the status bar and a toast, and keeps the drawn
// state: the zones go back to the committed graph with what derives from it
// (`Builder.rollback`), and the drawn figure, its ranges, legend and
// selection stay, as the server's results do. When the server may hold a
// result that is not drawn (`serverAhead`), the committed graph is plotted
// again at the drawn view with the drawn selection (`kept`), or the figure
// removed when none was drawn. The error stays shown until the next edit
// (`StatusLine.hold`). Returns "refused".
function plotFailed(message, askedSize, restoring, kept = keptView()) {
  converting.hidden = true;
  statusLine.error(message);
  statusLine.hold();
  requestedSize = askedSize;
  if (builder.uncommitted() || serverAhead) builder.rollback();
  if (serverAhead && !restoring) {
    if (plottedEncoding) {
      plot(plottedEncoding, { restoring: true, keep: kept });
    } else {
      clearPlot();
      builder.commit();
      serverAhead = false;
    }
  } else {
    resumeShown();
  }
  return "refused";
}

// Brings the drawn figure up to date after a failed plot, which superseded
// the requests of its views: a new size, a pending view, a zoom or a filter
// is aggregated again; else the selection, whose task the plot may have
// killed, is asked for again.
function resumeShown() {
  if (!overview) return;
  if (!sameSize(stageSize(), requestedSize)) {
    onResize();
  } else if (waiting || movedWhilePlotting || filtersKey(current.filters) !== filtersKey(filters)) {
    movedWhilePlotting = false;
    hideHover();
    const shown = shownRanges(gd, overview.meta);
    if (sameRanges(shown.x, overview.meta.x_ranges) && sameRanges(shown.y, overview.meta.y_ranges)) showOverview();
    else requestView(shown);
  } else {
    boxSelection.follow();
  }
}

// Shows the status of a result drawn, and marks the status with its task:
// tests wait for a new result by the mark, as the text may stay the same.
function showRows(meta, where = "") {
  statusLine.element.dataset.task = meta.task;
  statusLine.show(rowsText(meta, where));
}

// The drawn figure without its axis ranges and the ticks of its categorical
// axes, which follow the ranges (`bandticks.js`). A result of the same plot
// and size has the same figure, and then only its images and ranges change:
// plotly redraws the axes of 100 panels in about 0.4s, even for `react`.
let drawnKey = null;
// The ranges this page is setting with `Plotly.relayout`, whose own
// `plotly_relayout` is not a view to aggregate.
let ownRelayout = null;
// Whether this page is drawing a new figure with `Plotly.react`, which drops
// plotly's box of the selection: its events do not drop the selection.
let ownReact = false;

// Draws `data` with `layout`, and the images of `meta` over it, with the
// ticks and reference lines of the axis settings.
async function draw(data, plain, meta, bitmaps) {
  const started = performance.now();
  const layout = withBandTicks(orientedLayout(decorate(plain, meta, settingsOf, angleOf), meta), meta);
  const key = figureKey(data, layout);
  if (key === drawnKey) {
    const update = rangeUpdate(gd, layout);
    if (update) {
      ownRelayout = update;
      await Plotly.relayout(gd, update);
      ownRelayout = null;
    }
  } else {
    ownReact = true;
    try {
      await Plotly.react(gd, data, forPlotly(boxSelection.withBox(layout, meta)));
    } finally {
      ownReact = false;
    }
    drawnKey = key;
  }
  showImages(meta, bitmaps);
  timings.react = Math.round(performance.now() - started);
}

// Marks the drawn images as a stand-in while a view is aggregated: they fade
// and a notice shows, so that they are not taken for the result. They mark it
// only when no result came within `PENDING_DELAY_MS`: a mark that flashes on
// a fast result makes it look slow. Once a result is drawn, the selection
// follows it, however soon it came.
const PENDING_DELAY_MS = 200;
const pending = document.getElementById("pending");
let waiting = false;
let pendingTimer = 0;
function setPending(on) {
  waiting = on;
  markBusy();
  clearTimeout(pendingTimer);
  if (on) {
    // A request that supersedes one already marked keeps the mark.
    if (pending.hidden) pendingTimer = setTimeout(markPending, PENDING_DELAY_MS);
    return;
  }
  gd.classList.remove("pending");
  pending.hidden = true;
  boxSelection.follow();
}
function markPending() {
  gd.classList.add("pending");
  pending.hidden = false;
}

// The selection of rows with a box, its layer and the table of its rows.
const table = new SelectionTable(document.getElementById("table"));
table.exporting = () => saves.running;
const boxSelection = new BoxSelection({
  gd,
  layers,
  table,
  statusLine,
  current: () => current,
  busy: () => ({ plotting: plotting !== 0, waiting }),
  showRows,
});

// Goes back to the overview's images and ranges; no worker runs, unless the
// overview was aggregated for another size of the plot area.
async function showOverview() {
  const mine = ++generation;
  requested = { x: [], y: [] };
  const { meta, size, bitmaps } = overview;
  const figure = structuredClone(overview.figure);
  // The overview has its own margin, which its labels are measured at below.
  const area = stageSize();
  const otherFilter = filtersKey(meta.filters) !== filtersKey(filters);
  // The overview of an old filter stands in with the legend of the result
  // shown, until the overview of the filter comes.
  setCurrent(meta, { legend: !otherFilter });
  if (size.width !== area.width || size.height !== area.height || otherFilter) {
    // The overview of the old size or filter stands in, stretched to the drawn figure.
    setPending(true);
    const { width, height } = gd._fullLayout;
    await draw(figure.data, { ...figure.layout, width, height }, meta, bitmaps);
    measureMargin(false);
    requestOverview();
    return;
  }
  setPending(false);
  requestedSize = size;
  shownSize = size;
  await draw(figure.data, figure.layout, meta, bitmaps);
  showRows(meta);
  setInfo();
  // The overview's labels set the margin again: back from a zoom, it may shrink.
  if (mine === generation) followMargin(false);
}

// Whether a result is the one drawn, at the figure size drawn: a new size of
// the area that keeps the layout gets the drawn result back, with no redraw.
function isDrawn(meta, layout) {
  const full = gd._fullLayout;
  return (
    meta.task === current.task &&
    full.width === layout.width &&
    full.height === layout.height &&
    full.margin.l === layout.margin.l
  );
}

// Aggregates the drawn plot again, at the stage's size with the page's
// filters, and draws the result: the overview (`whole`) or the view of
// `ranges` (`{x, y}`, as the axes show them). `path` is the endpoint,
// `body` what it takes besides the size and the filters, `status` the
// text shown meanwhile.
async function requestAgain({ path, body, ranges, whole, status }) {
  const mine = ++generation;
  const size = stageSize();
  requestedSize = size;
  requested = ranges;
  statusLine.show(status);
  setPending(true);
  const filterCandidate = restorePoint.propose(filterPane.sent);
  const started = performance.now();
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, ...size, filters }),
  });
  if (response.status === 409 || mine !== generation) return; // superseded
  if (!response.ok) {
    const text = await response.text();
    // A newer request may have come while the answer was read.
    if (mine === generation) viewFailed(text);
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
  if (whole) setOverview({ figure: structuredClone(figure), meta, size, bitmaps });
  setCurrent(meta);
  shownSize = size;
  hideHover();
  // The images and the panels' placement change; the axes of a view stay
  // where the user put them.
  const layout = whole ? figure.layout : withRanges(figure.layout, meta, shownRanges(gd, meta));
  if (!drawn) await draw(figure.data, layout, meta, bitmaps);
  restorePoint.confirm(filterCandidate);
  if (mine === generation) setPending(false);
  showRows(meta, whole ? "" : "表示範囲に ");
  setInfo();
  if (mine === generation) followMargin(true);
}

// Aggregates the overview again for the current size of the plot area. The
// drawn images stand in, stretched and faded, until the result comes.
async function requestOverview() {
  return requestAgain({
    path: "/api/overview",
    body: {},
    ranges: { x: [], y: [] },
    whole: true,
    status: "大きさに合わせて集約中…",
  });
}

// Aggregates the shown ranges again. Until the result comes, plotly keeps
// drawing the current images stretched to the new axes, faded, and the area
// they do not cover stays blank.
async function requestView({ x: xRanges, y: yRanges }) {
  // The server takes values, ascending: the powers of 10 of the exponents of
  // a log axis (`axisscale.js`).
  const logs = overview.meta;
  const values = {
    x: xRanges.map((range, i) => toValues(logs.x_log[i], range)),
    y: yRanges.map((range, i) => toValues(logs.y_log[i], range)),
  };
  return requestAgain({
    path: "/api/view",
    body: { x_ranges: values.x, y_ranges: values.y },
    ranges: { x: xRanges, y: yRanges },
    whole: false,
    status: "表示範囲を集約中…",
  });
}

// Tells of a failed view or overview (the latest request), whose answer is
// `text`. One that the color levels of its filter refused
// (`ddviz.compute.aggregate.FilteredColorLevelsError`) leaves the figure, the
// legend and the selection drawn, and puts the filter pane back to the
// conditions of the result drawn last (`RestorePoint`), without asking for
// anything; but when the axes were moved meanwhile, or the result shown is
// not of those conditions, the shown ranges are aggregated with them. The error stays shown until
// the next edit (`StatusLine.hold`).
function viewFailed(text) {
  setPending(false);
  statusLine.error(errorText(text));
  let refused = false;
  try {
    refused = JSON.parse(text).error === "filtered_color_levels";
  } catch {
    // Not the server's JSON: no filter to go back from.
  }
  if (!refused || !current) return;
  statusLine.hold();
  filterPane.restore(restorePoint.point());
  filters = filterPane.conditions();
  const whole = current === overview.meta;
  requested = whole ? { x: [], y: [] } : { x: current.x_ranges, y: current.y_ranges };
  // The result shown may be an old overview standing in (`showOverview`):
  // it has other conditions, so the shown ranges are aggregated again.
  const shown = shownRanges(gd, current);
  const sameFilter = filtersKey(current.filters) === filtersKey(filters);
  if (sameFilter && sameRanges(shown.x, current.x_ranges) && sameRanges(shown.y, current.y_ranges)) return;
  hideHover();
  if (sameRanges(shown.x, overview.meta.x_ranges) && sameRanges(shown.y, overview.meta.y_ranges)) showOverview();
  else requestView(shown);
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
  const autorange = keys.some((key) => key.endsWith("autorange"));
  if (!autorange && !keys.some((key) => /^[xy]axis\d*\.range/.test(key))) return;
  // The labels of the new range come at once, before its result.
  setTimeout(followBandTicks);
  // A view asked for now would kill the plot in flight: a failed plot asks for it.
  if (plotting) {
    movedWhilePlotting = true;
    return;
  }
  statusLine.release();
  if (autorange) {
    showOverview();
    return;
  }
  const shown = shownRanges(gd, overview.meta);
  if (sameRanges(shown.x, overview.meta.x_ranges) && sameRanges(shown.y, overview.meta.y_ranges)) {
    showOverview();
    return;
  }
  // The labels of the new range, drawn now, set the margin the view asks for.
  measureMargin(false);
  if (sameRanges(shown.x, requested.x) && sameRanges(shown.y, requested.y) && sameSize(stageSize(), requestedSize)) {
    return;
  }
  requestView(shown);
}

// Gives the categorical axes drawn the ticks of their shown ranges (`bandticks.js`).
async function followBandTicks() {
  if (!current || !gd._fullLayout || ownRelayout) return;
  const update = bandTickUpdate(gd, current);
  if (!update) return;
  ownRelayout = update;
  try {
    await Plotly.relayout(gd, update);
  } finally {
    ownRelayout = null;
  }
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
  if (!current.scroll) {
    // The figure no longer matches a result of its size.
    drawnKey = null;
    const { width, height } = stageSize();
    await Plotly.relayout(gd, { width, height });
    // Its panels, and so its labels, changed with the size.
    measureMargin(false);
  }
  if (requested.x.length) {
    requestView(shownRanges(gd, current));
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
    requestView(shownRanges(gd, current));
  } else {
    requestOverview();
  }
}

const leftPane = new LeftPane(document.getElementById("left"));
// The state of the filter pane that the result drawn last was aggregated
// with: a filter whose color levels are refused goes back to it (`viewFailed`).
const restorePoint = new RestorePoint();
const filterPane = new FilterPane(
  document.getElementById("filters"),
  (conditions) => {
    filters = conditions;
    statusLine.release();
    applyFilters();
  },
  (count, text) => leftPane.setFilter(count, text),
);

// Removes the figure of a graph that cannot be drawn (`drawable`).
function clearPlot() {
  boxSelection.clear();
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
  options.wrapAuto = null;
  setWrapAuto(null);
  elementBar.setPointsText(null);
  elementBar.setLineText(null);
  stage.classList.remove("scrolls");
  sticky.set(null);
  builder.layout();
  empty.hidden = false;
  noRows.hidden = true;
  statusLine.show("");
  hoverWarning.hidden = true;
  logWarning.hidden = true;
}

// Draws the markers of every series in another size, dropping the sizes of
// single symbol levels: the graph is plotted again.
function setShapeSize(size) {
  options.setShapeSize(size);
  if (plottedEncoding) plot(plottedEncoding);
}

// Draws the shapes of a symbol level in another size: the graph is plotted again.
function setLevelSize(column, level, size) {
  options.setLevelSize(column, level, size);
  if (plottedEncoding) plot(plottedEncoding);
}

// Draws the points of a symbol level in another shape, or in the shape of
// its place again (null): the graph is plotted again.
function setLevelShape(column, level, shape) {
  options.setLevelShape(column, level, shape);
  if (plottedEncoding) plot(plottedEncoding);
}

// Draws the lines of every series in another width: a graph with them is
// plotted again.
function setLineWidth(width) {
  options.lineWidth = width;
  if (plottedEncoding?.elements.includes("line")) plot(plottedEncoding);
}

// Fits the smoothing lines another way: a graph with them is plotted again.
function setSmoothing(picked) {
  options.smoothing = picked;
  elementBar.setSmoothText(smoothingText(picked));
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
  symbol: null,
});
// Cuts a numeric color column another way, or draws it as a gradient (null):
// the series change, so the graph is plotted again.
function setColorBins(bins) {
  options.colorBins = bins;
  if (plottedEncoding) plot(plottedEncoding);
}

// Picks the color of a color level, or the palette's again (null).
function setLevelColor(level, color) {
  pickColor(level, color);
  recolor();
}

// Draws the decoded images again in new colors (of the scale, or picked for
// the levels): the overview's, the drawn result's and the selection layer's.
// Their files are still on the server, so no aggregation runs. Images being
// decoded meanwhile are decoded again in the new colors (`loadImages`).
async function recolor() {
  colorsChanged();
  legend.render();
  // The boxes and the smoothing lines take the new colors at once.
  layers.draw();
  if (!overview) return;
  const mine = generation;
  const shown = current;
  const layerOf = boxSelection.layerToRecolor();
  const [overviewImages, shownImages_, layerImages] = await Promise.all([
    overview.bitmaps ? fetchImages(overview.meta) : null,
    shown && shown !== overview.meta ? fetchImages(shown) : null,
    layerOf ? loadImages(layerOf.layer, shown).catch(() => null) : null,
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
  if (layerImages) boxSelection.replaceBitmaps(layerOf, layerImages);
}

// The element icons, made after the builder whose elements they set.
let elementBar = null;
const builder = new Builder(
  builderRoot,
  document.getElementById("columns"),
  (encoding) => {
    // Elements no longer possible are turned off; that edit comes back here.
    const smooth = hasSmoothPair(encoding, builder.numeric);
    if (elementBar?.allow({ line: smooth, box: hasBoxPair(encoding, builder.numeric), smooth })) return;
    const key = drawnRoles(encoding);
    if (key === drawnRolesKey) return;
    const drawn = JSON.parse(drawnRolesKey);
    if (encoding.color !== drawn[2]) options.colorBins = null;
    if (encoding.wrap !== drawn[5]) {
      options.wrapCols = null;
      options.wrapAuto = null;
      closeWrapMenu();
    }
    drawnRolesKey = key;
    if (drawable(encoding, builder.numeric)) {
      plot(encoding);
    } else {
      // A graph without a figure is committed at once: no plot can fail.
      statusLine.release();
      clearPlot();
      serverAhead = false;
      builder.commit();
    }
  },
  {
    // The state derived from the graph, which a failed plot rolls back with
    // it. The wrap's number to a row with none set is the drawn result's.
    save: () => ({
      drawnRolesKey,
      plottedEncoding,
      elements: elementBar?.state() ?? null,
      ...options.saved(),
    }),
    load: (state) => {
      ({ drawnRolesKey, plottedEncoding } = state);
      options.load(state);
      if (state.elements) elementBar.restore(state.elements);
      options.wrapAuto = current?.wrap_auto_cols ?? null;
      setWrapAuto(options.wrapAuto);
      closeWrapMenu();
    },
  },
);
// A right click on the Wrap zone while it holds a column opens the form of
// the number to a row; a new number plots the graph again.
document.querySelector('#builder .zone[data-role="wrap"]').addEventListener("contextmenu", (event) => {
  event.preventDefault();
  closeWrapMenu();
  if (!builder.placed("wrap").length) return;
  openWrapMenu(event, options.wrapCols, options.wrapAuto, (cols) => {
    if (cols === options.wrapCols) return;
    options.wrapCols = cols;
    if (plottedEncoding?.wrap) plot(plottedEncoding);
  });
});
// A changed "Show null rows", or keeping the levels the filter leaves out,
// plots the graph again: its levels change. A plot that fails turns the
// setting back (`plotFailed` keeps the drawn figure); without a graph to
// plot, the next plot takes it.
attachZoneMenu(builderRoot, {
  hasColumn: (role) => builder.placed(role).length > 0,
  showNullRows: options.showNullRows,
  onNullRows: () => {
    if (plottedEncoding) plot(plottedEncoding);
  },
  categoricalColor: () => {
    const [column] = builder.placed("color");
    return column !== undefined && !builder.numeric.get(column);
  },
  keepLevels: () => options.keepColorLevels,
  onKeepLevels: async () => {
    const before = options.keepColorLevels;
    options.keepColorLevels = !before;
    if (!plottedEncoding) {
      builder.commit();
      return;
    }
    const toggled = options.keepColorLevels;
    if ((await plot(plottedEncoding)) === "refused" && options.keepColorLevels === toggled) {
      options.keepColorLevels = before;
    }
  },
});
elementBar = new ElementBar(
  document.getElementById("elements"),
  (elements) => builder.setElements(elements),
  (event) => openSmoothMenu(event, options.smoothing, setSmoothing),
  (event) => {
    if (current) openShapeMenu(event, SIZE_HEADING, options.sharedSize(current), setShapeSize);
  },
  (event) => {
    if (current) openShapeMenu(event, LINE_HEADING, current.line_width, setLineWidth, { sizes: LINE_WIDTHS });
  },
);
elementBar.setSmoothText(smoothingText(options.smoothing));
// The empty graph with its element icons is the first committed state.
builder.commit();
// The chips of X and Y follow the drawn axes, and their zones' sizes.
builder.setAxes(drawnAxes);
const axisZones = builderRoot.querySelectorAll(':scope > .zone[data-role="x"], :scope > .zone[data-role="y"]');
const zoneObserver = new ResizeObserver(() => builder.layout());
for (const zone of axisZones) zoneObserver.observe(zone);
// A right click on a listed column opens its menu of the roles and the
// filter pane to place it on.
await attachColumnList(document.getElementById("columns"), (event, column) =>
  openColumnMenu(event, column, builder, filterPane),
);
showCasts(document.getElementById("casts"));
