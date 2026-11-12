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
import { bandTickUpdate, withBandTicks } from "./bandticks.js";
import { openAxisMenu } from "./axismenu.js";
import { AxisScales, isLogAxis, toPosition, toValues } from "./axisscale.js";
import { Builder } from "./builder.js";
import { showCasts } from "./casts.js";
import { colorsChanged, isMissingLevel, keepPicked, levelColors, pickColor } from "./colorscale.js";
import { attachColumnList } from "./columns.js";
import { openDataMenu } from "./datamenu.js";
import { ElementBar } from "./elements.js";
import { FilterPane } from "./filters.js";
import { attachHover } from "./hover.js";
import { ImageLayers, closeImages, loadImages } from "./layers.js";
import { fitBottom, fitMargin, MARGIN_BOTTOM, MARGIN_LEFT, neededBottom, neededMargin } from "./leftmargin.js";
import { LeftPane } from "./leftpane.js";
import { Legend } from "./legend.js";
import { levelText } from "./names.js";
import { MemoryMeter } from "./memory.js";
import { StatusLine, Toasts, errorText } from "./notice.js";
import { attachNullMenu } from "./nullmenu.js";
import { openPlotMenu } from "./plotmenu.js";
import { openScaleMenu } from "./scalemenu.js";
import { levelHeading, openShapeMenu, SIZE_HEADING } from "./shapemenu.js";
import { DEFAULT_SMOOTHING, openSmoothMenu, smoothingText } from "./smoothmenu.js";
import { StickyLabels } from "./sticky.js";
import { SelectionTable } from "./table.js";
import { forPlotly, linearRange, plotlyRange } from "./temporal.js";
import { closeWrapMenu, openWrapMenu, setWrapAuto } from "./wrapmenu.js";

const statusLine = new StatusLine(document.getElementById("status"), new Toasts(document.getElementById("toasts")));
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
  facets: "パネルの水準を調べ中…",
  boxes: "箱ひげを計算中…",
  smooth: "平滑化を計算中…",
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
    openScaleMenu(event, colorBins, setColorBins, recolor, sharedSize(), setShapeSize),
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
      openScaleMenu(event, colorBins, setColorBins, recolor, sharedSize(), setShapeSize);
    } else {
      const level = current.series[i];
      openShapeMenu(event, SIZE_HEADING, sharedSize(), setShapeSize, {
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
// for the default: larger for the symbol's shapes than for the circles of
// the points.
let shapeSize = null;
// Sizes of the shapes of single symbol levels, by symbol column and level
// name (`ddviz.server.plan.parse_shape_sizes`), picked in the menu of the
// symbol legend's markers; kept for every graph, dropped when the size of
// every series is picked.
const levelSizes = new Map();
// Shapes of single symbol levels, by level name, of the symbol column
// `column` (`ddviz.server.plan.parse_level_shapes`), picked in the panel of
// the menu of the symbol legend's markers. They stay while the symbol
// column does, as the colors picked for the color levels: a graph of
// another symbol column drops them.
const levelShapes = { column: undefined, shapes: Object.create(null) };
// Whether the Color and the Symbol zone draw the rows of a null or NaN
// value (`ddviz.server.models.ShowNullRows`), set in the zones' menu
// (nullmenu.js); kept whatever column the zone holds, true after a reload.
const showNullRows = { color: true, symbol: true };
// Wrapped panels to a row, or null to make them closest to square
// (`ddviz.server.plan.parse_wrap_cols`); back to null for another wrap column.
// The user sets it in the Wrap zone's form (wrapmenu.js).
let wrapCols = null;
// The number to a row with none set, of the latest result for the wrap
// column (`wrap_auto_cols` of its meta), or null without one.
let wrapAuto = null;
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

// Whether two ranges run the same way.
function sameOrder(a, b) {
  return a[1] < a[0] === b[1] < b[0];
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
// the graph is aggregated again, with the column's axis over its whole
// range and the other columns' axes at their shown ranges. A refusal (no
// positive value) keeps the drawn plot, its selection and the scale.
async function setAxisLog(meta, axis, column, log) {
  if (meta !== current || !plottedEncoding) return;
  const shown = shownRanges(meta);
  const kept = {};
  for (const role of ["x", "y"]) {
    meta[`${role}_columns`].forEach((c, i) => {
      if (!(role === axis && c === column)) kept[`${role}:${c}`] = shown[role][i];
    });
  }
  axisScales.set(axis, column, log);
  const drawn = await plot(plottedEncoding);
  if (drawn === "refused") axisScales.set(axis, column, !log);
  if (!drawn || drawn === "refused") return;
  // The other axes back at their ranges: a view, as after a zoom.
  const next = current;
  const update = {};
  for (const role of ["x", "y"]) {
    next[`${role}_columns`].forEach((c, i) => {
      const range = kept[`${role}:${c}`];
      const key = axisKey(next[`${role}_axes`][i]);
      const full = gd._fullLayout[key];
      if (range && !sameRange(ascending(linearRange(full)), range)) {
        update[`${key}.range`] = plotlyRange(full, oriented(range, axisDirections.isReversed(role, c)));
      }
    });
  }
  if (next === drawn && Object.keys(update).length) await Plotly.relayout(gd, update);
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
    openDataMenu(event.currentTarget ?? event.target.closest(".modebar-btn"), () => overview?.meta.task ?? null),
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
// would otherwise leave scroll bars over a grid that fits.
function setCurrent(meta) {
  current = meta;
  legend.setEmpty(meta);
  elementBar.setPointsText(markerSizeText(meta));
  stage.classList.toggle("scrolls", meta.scroll);
  wrapAuto = meta.wrap_auto_cols;
  setWrapAuto(wrapAuto);
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

function sameSize(a, b) {
  return (
    a !== null &&
    b !== null &&
    a.width === b.width &&
    a.height === b.height &&
    a.margin_left === b.margin_left &&
    a.margin_bottom === b.margin_bottom
  );
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
  // Another symbol column drops the shapes picked once its result is drawn.
  const shapes = encoding.symbol === levelShapes.column ? pickedShapes(encoding.symbol) : null;
  const body = {
    encoding,
    ...size,
    filters,
    color_bins: colorBins,
    wrap_cols: wrapCols,
    smooth: smoothing,
    shape_size: shapeSize,
    shape_sizes: levelSizes.get(encoding.symbol) || null,
    level_shapes: shapes,
    show_null_rows: { ...showNullRows },
    axis_scales: axisScales.request(encoding),
  };
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
  const drawStarted = performance.now();
  try {
    // The selection and the shapes of another symbol column go with the drawn plot.
    clearSelection(false);
    movedWhilePlotting = false;
    setOverview({ figure: structuredClone(figure), meta, size, bitmaps });
    requested = { x: [], y: [] };
    setCurrent(meta);
    shownSize = size;
    setPending(false);
    empty.hidden = true;
    showImages(meta, null);
    // A plot drawn again after a failure has the view and the box drawn before.
    const view = keep && sameAxes(keep, meta) ? keep : null;
    if (view?.box) selection = { box: view.box, base: null, bitmaps: null, fresh: true };
    const ranged = view?.zoomed ? withRanges(figure.layout, meta, view.ranges) : figure.layout;
    const layout = withBandTicks(orientedLayout(decorate(ranged, meta, settingsOf, angleOf), meta), meta);
    drawnKey = figureKey(figure.data, layout);
    Plotly.purge(gd);
    await Plotly.newPlot(gd, figure.data, forPlotly(withSelectionBox(layout, meta)), PLOT_CONFIG);
    timings.plot = Math.round(performance.now() - drawStarted);
    // The legend and the colors and shapes picked change once the figure is
    // drawn: a figure that fails keeps them for the graph drawn again.
    legend.set(meta);
    // The colors picked for the levels stay while the color column does.
    keepPicked(meta.color.column);
    // The shapes picked stay while the symbol column does.
    pickedShapes(encoding.symbol);
    layers.attach();
    sticky.attach();
    // The chips of X and Y follow the axes drawn now and on every later draw.
    for (const event of ["plotly_afterplot", "plotly_relayout"]) gd.on(event, () => builder.layout());
    builder.layout();
    gd.on("plotly_relayout", onRelayout);
    gd.on("plotly_selected", (event) => {
      if (!ownReact) onSelected(event);
    });
    gd.on("plotly_deselect", () => {
      if (!ownReact) clearSelection();
    });
    showImages(meta, bitmaps);
    if (view?.box) layers.setSelection({ box: view.box });
    // The figure drawn is this graph's: a later failure comes back to it.
    builder.commit(candidate);
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
  else followSelection();
  return meta;
}

// Returns the view and the selection drawn now, for a plot of the same
// graph to draw again (`plot`'s `keep`): the ranges of each x and y column
// (`shownRanges`), whether they are zoomed from the overview's, and the
// selection's box. Null without a figure.
function keptView() {
  if (!overview || !gd._fullLayout) return null;
  const ranges = shownRanges(overview.meta);
  const { x_ranges: x, y_ranges: y } = overview.meta;
  const zoomed = !(sameRanges(ranges.x, x) && sameRanges(ranges.y, y));
  return { ranges, zoomed, box: selection ? structuredClone(selection.box) : null };
}

// Whether a kept view (`keptView`) has a range for each axis column of a result.
function sameAxes(keep, meta) {
  return keep.ranges.x.length === meta.x_axes.length && keep.ranges.y.length === meta.y_axes.length;
}

// Returns `layout` with the axis ranges of each x and y column given (`shownRanges`).
function withRanges(layout, meta, ranges) {
  const out = { ...layout };
  for (const panel of meta.panels) {
    const xKey = axisKey(panel.xaxis);
    const yKey = axisKey(panel.yaxis);
    out[xKey] = { ...layout[xKey], range: ranges.x[panel.x] };
    out[yKey] = { ...layout[yKey], range: ranges.y[panel.y] };
  }
  return out;
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
    const shown = shownRanges(overview.meta);
    if (sameRanges(shown.x, overview.meta.x_ranges) && sameRanges(shown.y, overview.meta.y_ranges)) showOverview();
    else requestView(shown);
  } else {
    followSelection();
  }
}

// Shows the status of a result drawn, and marks the status with its task:
// tests wait for a new result by the mark, as the text may stay the same.
function showRows(meta, where = "") {
  statusLine.element.dataset.task = meta.task;
  statusLine.show(rowsText(meta, where));
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
  return `${where}${meta.rows.toLocaleString()} 行${drawn}${filtered}`;
}

// Returns whether two ranges are equal up to a small part of their span. A
// date axis's range comes back from plotly as the same milliseconds
// (`dateText`), however short it is.
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
// numbers (a date axis holds dates), ascending on a reversed axis too: the panels of one column share them
// (`matches`).
function shownRanges(meta) {
  const full = gd._fullLayout;
  return {
    x: meta.x_axes.map((id) => ascending(linearRange(full[axisKey(id)]))),
    y: meta.y_axes.map((id) => ascending(linearRange(full[axisKey(id)]))),
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

function figureKey(data, layout) {
  const axes = {};
  for (const [key, value] of Object.entries(layout)) {
    axes[key] = /^[xy]axis\d*$/.test(key) ? { ...value, range: null, tickvals: null, ticktext: null } : value;
  }
  return JSON.stringify([data, axes]);
}

// Returns the relayout that gives every axis its range in `layout`, and a
// categorical axis its ticks, or null when the axes already have them.
function rangeUpdate(layout) {
  const update = {};
  for (const [key, value] of Object.entries(layout)) {
    if (!/^[xy]axis\d*$/.test(key)) continue;
    if (!sameRange(linearRange(gd._fullLayout[key]), value.range)) {
      update[`${key}.range`] = plotlyRange(value, value.range);
    }
    const drawn = gd.layout[key] ?? {};
    for (const name of ["tickvals", "ticktext"]) {
      if (value[name] && JSON.stringify(value[name]) !== JSON.stringify(drawn[name])) {
        update[`${key}.${name}`] = value[name];
      }
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
  // plotly's box on a log axis is of values, as its `event.range` (`boxRange`).
  const [x0, x1] = toValues(isLogAxis(layout[axisKey(panel.xaxis)]), x);
  const [y0, y1] = toValues(isLogAxis(layout[axisKey(panel.yaxis)]), y);
  const box = { type: "rect", xref: panel.xaxis, yref: panel.yaxis, x0, x1, y0, y1 };
  return { ...layout, selections: [{ ...box, line: { width: 1, dash: "dot" } }] };
}

// Draws `data` with `layout`, and the images of `meta` over it, with the
// ticks and reference lines of the axis settings.
async function draw(data, plain, meta, bitmaps) {
  const started = performance.now();
  const layout = withBandTicks(orientedLayout(decorate(plain, meta, settingsOf, angleOf), meta), meta);
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
      await Plotly.react(gd, data, forPlotly(withSelectionBox(layout, meta)));
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
  followSelection();
}
function markPending() {
  gd.classList.add("pending");
  pending.hidden = false;
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
    x_range: boxRange(full[axisKey(xaxis)], range[xaxis]),
    y_range: boxRange(full[axisKey(yaxis)], range[yaxis]),
  };
}

// Returns the bounds of plotly's box along an axis in linear units. On a
// log axis, plotly's `event.range` holds values (checked in Chrome), not the
// exponents of the axis's range: they become exponents here.
function boxRange(axis, range) {
  return ascending(isLogAxis(axis) ? range.map((v) => toPosition(true, v)) : linearRange(axis, range));
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
  statusLine.release();
  const box = boxOf(current, event.range);
  if (!box) return;
  closeImages(selection?.bitmaps);
  selection = { box, base: null, bitmaps: null, fresh: true };
  layers.setSelection({ box });
  // An aggregation in flight would be killed; the selection waits for its result.
  if (!waiting && !plotting) followSelection();
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
  const response = await fetch("/api/selection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (mine !== selectionGeneration || !selection) return;
  if (!response.ok) {
    // Killed by a newer aggregation: asked again once its result is drawn.
    selection.base = null;
    const text = await response.text();
    if (response.status !== 409) statusLine.error(errorText(text));
    // Killed by a plot that failed: asked again, unless another aggregation goes on.
    else if (errorText(text) === "cancelled" && !plotting && !waiting && mine === selectionGeneration) followSelection();
    return;
  }
  const layer = await response.json();
  let bitmaps = null;
  try {
    bitmaps = await loadImages({ task: layer.task, images: layer.images }, meta);
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
  layers.setSelection({ meta, bitmaps, piles: new Set(layer.piles) });
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
    if (current) showRows(current);
  }
}

// Goes back to the overview's images and ranges; no worker runs, unless the
// overview was aggregated for another size of the plot area.
async function showOverview() {
  const mine = ++generation;
  requested = { x: [], y: [] };
  const { meta, size, bitmaps } = overview;
  const figure = structuredClone(overview.figure);
  setCurrent(meta);
  // The overview has its own margin, which its labels are measured at below.
  const area = stageSize();
  if (size.width !== area.width || size.height !== area.height || filtersKey(meta.filters) !== filtersKey(filters)) {
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
  showRows(meta);
  setInfo();
  if (mine === generation) followMargin(true);
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
  // The server takes values, ascending: the powers of 10 of the exponents of
  // a log axis (`axisscale.js`).
  const logs = overview.meta;
  const values = {
    x: xRanges.map((range, i) => toValues(logs.x_log[i], range)),
    y: yRanges.map((range, i) => toValues(logs.y_log[i], range)),
  };
  const started = performance.now();
  const response = await fetch("/api/view", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x_ranges: values.x, y_ranges: values.y, ...size, filters }),
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
  showRows(meta, "表示範囲に ");
  setInfo();
  if (mine === generation) followMargin(true);
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
  const shown = shownRanges(overview.meta);
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
    statusLine.release();
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
  wrapAuto = null;
  setWrapAuto(null);
  elementBar.setPointsText(null);
  stage.classList.remove("scrolls");
  sticky.set(null);
  builder.layout();
  empty.hidden = false;
  noRows.hidden = true;
  statusLine.show("");
  hoverWarning.hidden = true;
  logWarning.hidden = true;
}

// The roles a scatter plot draws (`ddviz.server.plan.drawn_columns`) and
// its elements.
function drawnRoles(encoding) {
  const { x, y, color, row, col, wrap, elements, symbol } = encoding;
  return JSON.stringify([x, y, color, row, col, wrap, elements, symbol]);
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
// single symbol levels: the graph is plotted again.
function setShapeSize(size) {
  shapeSize = size;
  levelSizes.clear();
  if (plottedEncoding) plot(plottedEncoding);
}

// Draws the shapes of a symbol level in another size: the graph is plotted again.
function setLevelSize(column, level, size) {
  // Level names come from the data: no prototype, so that "__proto__" is a
  // name like the others.
  const sizes = levelSizes.get(column) ?? Object.create(null);
  sizes[level] = size;
  levelSizes.set(column, sizes);
  if (plottedEncoding) plot(plottedEncoding);
}

// Returns the shapes picked for the levels of a symbol column, or null for
// none; the shapes of another column are dropped.
function pickedShapes(column) {
  if (column !== levelShapes.column) {
    levelShapes.column = column;
    levelShapes.shapes = Object.create(null);
  }
  return Object.keys(levelShapes.shapes).length ? levelShapes.shapes : null;
}

// Draws the points of a symbol level in another shape, or in the shape of
// its place again (null): the graph is plotted again.
function setLevelShape(column, level, shape) {
  pickedShapes(column);
  if (shape === null) delete levelShapes.shapes[level];
  else levelShapes.shapes[level] = shape;
  if (plottedEncoding) plot(plottedEncoding);
}

// Returns the size of every series' markers drawn, checked in the menus of
// the size of every series; null while symbol levels have sizes of their
// own, of any symbol column, so that picking any size, that one too, drops
// them.
function sharedSize() {
  return current && levelSizes.size === 0 ? current.marker_size : null;
}

// Returns the text of the size of a result's markers (its meta), for the
// points' icon: a range when symbol levels have sizes of their own.
function markerSizeText(meta) {
  const sizes = meta.symbol?.sizes.length ? meta.symbol.sizes : [meta.marker_size];
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
  symbol: null,
});
// Cuts a numeric color column another way, or draws it as a gradient (null):
// the series change, so the graph is plotted again.
function setColorBins(bins) {
  colorBins = bins;
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
  const layerOf = selection?.bitmaps ? selection : null;
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
  if (layerImages && selection === layerOf) {
    closeImages(selection.bitmaps);
    selection.bitmaps = layerImages;
    layers.setSelection({ ...layers.selection, bitmaps: layerImages });
  } else {
    closeImages(layerImages);
  }
}

// The element icons, made after the builder whose elements they set.
let elementBar = null;
const builder = new Builder(
  builderRoot,
  document.getElementById("columns"),
  (encoding) => {
    // Elements no longer possible are turned off; that edit comes back here.
    if (elementBar?.allow({ box: hasBoxPair(encoding), smooth: hasSmoothPair(encoding) })) return;
    const key = drawnRoles(encoding);
    if (key === drawnRolesKey) return;
    const drawn = JSON.parse(drawnRolesKey);
    if (encoding.color !== drawn[2]) colorBins = null;
    if (encoding.wrap !== drawn[5]) {
      wrapCols = null;
      wrapAuto = null;
      closeWrapMenu();
    }
    drawnRolesKey = key;
    if (drawable(encoding)) {
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
    save: () => ({ drawnRolesKey, colorBins, wrapCols, plottedEncoding, elements: elementBar?.state() ?? null }),
    load: (state) => {
      ({ drawnRolesKey, colorBins, wrapCols, plottedEncoding } = state);
      if (state.elements) elementBar.restore(state.elements);
      wrapAuto = current?.wrap_auto_cols ?? null;
      setWrapAuto(wrapAuto);
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
  openWrapMenu(event, wrapCols, wrapAuto, (cols) => {
    if (cols === wrapCols) return;
    wrapCols = cols;
    if (plottedEncoding?.wrap) plot(plottedEncoding);
  });
});
// A changed "Show null rows" plots the graph again: its levels change.
attachNullMenu(
  builderRoot,
  (role) => builder.placed(role).length > 0,
  showNullRows,
  () => {
    if (plottedEncoding) plot(plottedEncoding);
  },
);
elementBar = new ElementBar(
  document.getElementById("elements"),
  (elements) => builder.setElements(elements),
  (event) => openSmoothMenu(event, smoothing, setSmoothing),
  (event) => {
    if (current) openShapeMenu(event, SIZE_HEADING, sharedSize(), setShapeSize);
  },
);
elementBar.setSmoothText(smoothingText(smoothing));
// The empty graph with its element icons is the first committed state.
builder.commit();
// The chips of X and Y follow the drawn axes, and their zones' sizes.
builder.setAxes(drawnAxes);
const axisZones = builderRoot.querySelectorAll(':scope > .zone[data-role="x"], :scope > .zone[data-role="y"]');
const zoneObserver = new ResizeObserver(() => builder.layout());
for (const zone of axisZones) zoneObserver.observe(zone);
await attachColumnList(document.getElementById("columns"));
showCasts(document.getElementById("casts"));
