// The settings of a numeric or temporal axis, opened by a double click on
// its tick labels: its range, the interval of its ticks, how many minor
// ticks split each interval, and reference lines across its panels. The panels of one
// axis column share its axis (`matches`), so the settings are kept by
// column and drawn on every panel of the column (`decorate`); the range is
// the view of the column, which is aggregated again as a zoom is. The
// format of the tick labels (decimal, exponent, percent) is kept with the
// ticks: it changes only plotly's labels, not the values of the axis. A
// temporal axis (`axisKind`) takes its values as dates, times or seconds
// (`temporal.js`), its interval with a unit, and keeps plotly's labels.
// The angle of the major tick labels is set on a linear numeric axis and
// on a categorical one, whose dialog shows the other settings disabled
// (`dialogKind`); it is kept by role and column apart from the settings.

import { axisText, dateText, isDateKind, readAxisValue } from "./temporal.js";

// The look of a new reference line, and the dashes offered.
export const LINE_COLOR = "#000000";
export const LINE_DASH = "dash";
const DASHES = [
  ["solid", "実線"],
  ["dash", "破線"],
  ["dot", "点線"],
];
const LINE_WIDTH = 1.5;
// Most minor ticks a tick interval is split into, on a numeric axis and on
// a temporal one.
const MAX_MINOR = 100;
const MAX_TEMPORAL_MINOR = 10;
// The units of the interval of a temporal axis, in milliseconds: a day is
// always 24 hours, a week 7 days.
export const UNITS = [
  ["millisecond", "ミリ秒", 1],
  ["second", "秒", 1000],
  ["minute", "分", 60_000],
  ["hour", "時間", 3_600_000],
  ["day", "日", 86_400_000],
  ["week", "週", 604_800_000],
];
const UNIT_MS = Object.fromEntries(UNITS.map(([key, , ms]) => [key, ms]));
// The formats of the tick labels, and the fields each one uses: the digits
// after the decimal point (of the mantissa, of the value times 100) and the
// thousands separators.
const FORMATS = [
  ["auto", "自動"],
  ["fixed", "小数"],
  ["exponent", "指数"],
  ["percent", "パーセント"],
];
const USES_DIGITS = new Set(["fixed", "exponent", "percent"]);
const USES_SEPARATORS = new Set(["auto", "fixed", "percent"]);
// The digits shown for a format that has none set, and the most allowed.
const DEFAULT_DIGITS = 2;
const MAX_DIGITS = 15;
// d3-format's type of each explicit format (plotly's `tickformat`).
const FORMAT_TYPES = { fixed: "f", exponent: "e", percent: "%" };

// Returns the empty settings of a column: automatic ticks and labels, no
// reference lines.
// `unit` is that of the interval of a temporal axis (`UNITS`), null without one.
export function emptySettings() {
  return { dtick: null, unit: null, minor: null, lines: [], format: "auto", digits: null, separators: false };
}

// Returns the kind of the dialog of the axis column `index` of `axis` ("x"
// or "y") of the result `meta`: "number" for a numeric axis (`x_numeric`:
// linear, not categorical, temporal or the one band), the temporal kind
// for a datetime, date or time column, "duration" for a duration column on
// a linear axis; null for an axis without one (categorical, log, the band).
export function axisKind(meta, axis, index) {
  if (meta[`${axis}_numeric`][index]) return "number";
  const kind = meta.temporal?.[meta[`${axis}_columns`][index]];
  if (isDateKind(kind)) return kind;
  return kind === "duration" && !meta[`${axis}_log`][index] ? "duration" : null;
}

// Whether the axis column `index` of `axis` of `meta` is categorical: its
// levels are bands (`axis_levels`), not the one band of an empty x.
function isBandAxis(meta, axis, index) {
  if (axis === "x" && meta.one_band) return false;
  return Boolean(meta.axis_levels?.[meta[`${axis}_columns`][index]]);
}

// Returns the kind of the dialog that a double click on the axis column
// `index` of `axis` of `meta` opens: `axisKind`, "category" for a
// categorical axis (the angle of its labels alone), or null (a log axis,
// the one band).
export function dialogKind(meta, axis, index) {
  return axisKind(meta, axis, index) ?? (isBandAxis(meta, axis, index) ? "category" : null);
}

// Whether the angle of the tick labels of the axis column `index` of `axis`
// of `meta` is drawn: a linear numeric axis or a categorical one. A
// temporal or log axis, and the one band, keep plotly's own; the angle set
// stays for the column and is drawn again on a linear axis.
export function hasAngle(meta, axis, index) {
  const kind = dialogKind(meta, axis, index);
  return kind === "number" || kind === "category";
}

// The angles a tick label may be set to, in degrees: 0 is level, a
// positive angle turns it clockwise on the screen.
export const MAX_ANGLE = 90;
const ANGLE_ERROR = "−90〜90 の整数にしてください";

// Reads the angle of the tick labels typed in a field: `{value}` (an
// integer from -90 to 90), `{value: null}` for an empty field (plotly's
// automatic labels), or `{error}`. Only ASCII digits and one sign.
export function readAngle(text) {
  const trimmed = text.trim();
  if (trimmed === "") return { value: null };
  if (!/^[+-]?[0-9]+$/.test(trimmed)) return { error: ANGLE_ERROR };
  const value = Number(trimmed);
  if (Math.abs(value) > MAX_ANGLE) return { error: ANGLE_ERROR };
  return { value: value === 0 ? 0 : value };
}

// Returns the unit picked for the interval of a temporal axis of `kind`
// without one set, from plotly's interval `drawn` of its axis (`dtick`:
// milliseconds on a date axis, seconds of a duration, "M<n>" for months
// and years): the largest unit up to it, milliseconds below them, weeks
// for months; a day for a date and a second otherwise when there is none.
export function drawnUnit(kind, drawn) {
  if (typeof drawn === "string" && /^M\d+$/.test(drawn)) return "week";
  const ms = kind === "duration" ? drawn * 1000 : drawn;
  if (typeof drawn !== "number" || !(Number.isFinite(ms) && ms > 0)) return kind === "date" ? "day" : "second";
  let picked = "millisecond";
  for (const [key, , size] of UNITS) if (size <= ms) picked = key;
  return picked;
}

// Returns the interval of a temporal axis of `kind` as plotly takes it:
// milliseconds on a date axis, seconds of a duration.
function plotlyStep(kind, dtick, unit) {
  const ms = dtick * UNIT_MS[unit];
  return kind === "duration" ? ms / 1000 : ms;
}

// Reads a value of an axis of `kind` typed in a field: `{value}` or `{error}`.
function readValue(kind, text) {
  return kind === "number" ? readNumber(text) : readAxisValue(kind, text);
}

// Writes a value of an axis of `kind` into a field.
function valueText(kind, value) {
  return kind === "number" ? numberText(value) : axisText(kind, value);
}

// Whether `settings` change nothing of plotly's own axis: no settings to keep.
export function isEmpty(settings) {
  return (
    settings.dtick === null && !settings.lines.length && settings.format === "auto" && !settings.separators
  );
}

// Reads a number typed in a field: `{value}`, `{value: null}` for an empty
// field when `optional`, or `{error}`.
function readNumber(text, optional = false) {
  const trimmed = text.trim();
  if (trimmed === "") return optional ? { value: null } : { error: "数値を入れてください" };
  const value = Number(trimmed);
  return Number.isFinite(value) ? { value } : { error: "数値を入れてください" };
}

// Checks the fields of the dialog of an axis of `kind` (texts as typed, the
// unit of the interval, the format picked and whether the separators are
// checked) and returns the settings and range they make, `{range, dtick,
// unit, minor, format, digits, separators}`, or the reason of each field
// that is wrong (`{errors: {field: text}}`). An end whose text is that of
// `known` (`{min: {text, value}, max}`) is that value: the text of a
// temporal value is rounded. A field the format does not use is neither
// checked nor kept; a temporal axis keeps plotly's labels.
export function readFields({
  kind = "number",
  min,
  max,
  dtick,
  unit = null,
  minor,
  format = "auto",
  digits = "",
  separators = false,
  known = {},
}) {
  const errors = {};
  const temporal = kind !== "number";
  const end = (name, text) => (known[name]?.text === text ? { value: known[name].value } : readValue(kind, text));
  const lo = end("min", min);
  const hi = end("max", max);
  if (lo.error) errors.min = lo.error;
  if (hi.error) errors.max = hi.error;
  if (!lo.error && !hi.error && lo.value >= hi.value) errors.max = "最小値より大きくしてください";
  const step = readNumber(dtick, true);
  if (step.error) errors.dtick = step.error;
  else if (step.value !== null && step.value <= 0) errors.dtick = "0 より大きくしてください";
  else if (temporal && step.value !== null) {
    const size = plotlyStep(kind, step.value, unit);
    if (!(Number.isFinite(size) && size > 0)) errors.dtick = "この単位では使えない間隔です";
  }
  const most = temporal ? MAX_TEMPORAL_MINOR : MAX_MINOR;
  const parts = readNumber(minor, true);
  if (parts.error) errors.minor = parts.error;
  else if (parts.value !== null) {
    if (!Number.isInteger(parts.value) || parts.value < 2 || parts.value > most) {
      errors.minor = `2〜${most} の整数にしてください`;
    } else if (step.value === null && !errors.dtick) {
      errors.minor = "間隔を入れたときだけ使えます";
    }
  }
  let places = null;
  if (!temporal && USES_DIGITS.has(format)) {
    const trimmed = digits.trim();
    places = /^[0-9]+$/.test(trimmed) ? Number(trimmed) : NaN;
    if (!(places <= MAX_DIGITS)) errors.digits = `0〜${MAX_DIGITS} の整数にしてください`;
  }
  if (Object.keys(errors).length) return { errors };
  return {
    range: [lo.value, hi.value],
    dtick: step.value,
    unit: temporal && step.value !== null ? unit : null,
    minor: parts.value,
    format: temporal ? "auto" : format,
    digits: places,
    separators: !temporal && USES_SEPARATORS.has(format) && separators,
  };
}

// Returns the plotly attributes of the tick labels of an axis with
// `settings`: plotly's own labels (which turn to exponents by the range
// shown, as "1e+5"), with thousands separators when asked, or a d3-format
// (`tickformat`) of the format, its digits and separators. null removes
// what an earlier setting set.
export function formatAttributes(settings) {
  const { format, digits, separators } = { ...emptySettings(), ...settings };
  if (format === "auto") return { tickformat: null, separatethousands: separators || null };
  const comma = separators ? "," : "";
  return { tickformat: `${comma}.${digits}${FORMAT_TYPES[format]}`, separatethousands: null };
}

// Returns the plotly attributes of an axis of `kind` with `settings`:
// linear ticks every `dtick` from 0 and minor grid lines splitting each
// interval, or plotly's automatic ticks (null removes what an earlier
// setting set). The ticks of a temporal axis start at 1970-01-01 00:00 (a
// time's midnight) or at 0 seconds, every `dtick` of its unit.
export function tickAttributes(settings, kind = "number") {
  const { dtick, unit, minor } = { ...emptySettings(), ...settings };
  if (dtick === null) return { tickmode: null, tick0: null, dtick: null, minor: null };
  if (kind !== "number") {
    const step = plotlyStep(kind, dtick, unit);
    const tick0 = isDateKind(kind) ? dateText(0) : 0;
    return {
      tickmode: "linear",
      tick0,
      dtick: step,
      minor: minor === null ? null : { tick0, dtick: step / minor, showgrid: true },
    };
  }
  return {
    tickmode: "linear",
    tick0: 0,
    dtick,
    minor: minor === null ? null : { dtick: dtick / minor, showgrid: true },
  };
}

// Returns the plotly shapes of the reference lines of every axis column of
// a result (`meta`) with a dialog (`axisKind`): a vertical line across each
// panel of an x column, a horizontal one across each panel of a y column.
// A line on a date axis is at plotly's date text (`dateText`).
function lineShapes(meta, settingsOf) {
  const shapes = [];
  for (const panel of meta.panels) {
    const across = [
      [axisKind(meta, "x", panel.x), meta.x_columns[panel.x], panel.xaxis, panel.yaxis, "x"],
      [axisKind(meta, "y", panel.y), meta.y_columns[panel.y], panel.yaxis, panel.xaxis, "y"],
    ];
    for (const [kind, column, along, other, axis] of across) {
      const settings = kind ? settingsOf(column) : undefined;
      for (const line of settings?.lines ?? []) {
        const at = isDateKind(kind) ? dateText(line.value) : line.value;
        const [ref, otherRef] = axis === "x" ? ["xref", "yref"] : ["yref", "xref"];
        const [at0, at1, span0, span1] = axis === "x" ? ["x0", "x1", "y0", "y1"] : ["y0", "y1", "x0", "x1"];
        shapes.push({
          type: "line",
          layer: "above",
          [ref]: along,
          [otherRef]: `${other} domain`,
          [at0]: at,
          [at1]: at,
          [span0]: 0,
          [span1]: 1,
          line: { color: line.color, dash: line.dash, width: LINE_WIDTH },
        });
      }
    }
  }
  return shapes;
}

// Returns the axes of the panels of `meta` with a dialog, as `[key, kind,
// column]` (`xaxis2`, `axisKind`, the axis column).
function dialogAxes(meta) {
  const axes = [];
  for (const panel of meta.panels) {
    for (const [role, axis, index] of [
      ["x", panel.xaxis, panel.x],
      ["y", panel.yaxis, panel.y],
    ]) {
      const kind = axisKind(meta, role, index);
      if (kind) axes.push([axis.replace(/^([xy])/, "$1axis"), kind, meta[`${role}_columns`][index]]);
    }
  }
  return axes;
}

// Returns the axes of the panels of `meta` whose labels take an angle
// (`hasAngle`), as `[key, role, column]`.
function angleAxes(meta) {
  const axes = [];
  for (const panel of meta.panels) {
    for (const [role, axis, index] of [
      ["x", panel.xaxis, panel.x],
      ["y", panel.yaxis, panel.y],
    ]) {
      if (hasAngle(meta, role, index)) axes.push([axis.replace(/^([xy])/, "$1axis"), role, meta[`${role}_columns`][index]]);
    }
  }
  return axes;
}

// Returns `layout` (a figure's layout for `meta`) with the ticks and
// reference lines of the settings of its axis columns with a dialog
// (`settingsOf(column)`, or undefined for none), and the angles of their
// tick labels (`angleOf(role, column)`, or null for plotly's own).
export function decorate(layout, meta, settingsOf, angleOf = () => null) {
  const out = { ...layout };
  for (const [key, kind, column] of dialogAxes(meta)) {
    const settings = settingsOf(column);
    if (settings) out[key] = { ...out[key], ...withoutNulls(axisAttributes(settings, kind)) };
  }
  for (const [key, role, column] of angleAxes(meta)) {
    const angle = angleOf(role, column);
    if (angle !== null) out[key] = { ...out[key], tickangle: angle };
  }
  const shapes = lineShapes(meta, settingsOf);
  if (shapes.length) out.shapes = shapes;
  return out;
}

// Returns the plotly attributes of the ticks and their labels of an axis
// of `kind` with `settings` (or undefined for none): a temporal axis keeps
// plotly's labels.
function axisAttributes(settings, kind) {
  const ticks = tickAttributes(settings, kind);
  return kind === "number" ? { ...ticks, ...formatAttributes(settings) } : ticks;
}

// Returns the relayout that draws `settingsOf` and `angleOf` on the drawn
// figure of `meta`: the tick and label attributes of every axis of its
// columns with a dialog, the shapes, and the angles of the labels (null
// gives an axis plotly's own back).
export function decorationUpdate(meta, settingsOf, angleOf = () => null) {
  const update = { shapes: lineShapes(meta, settingsOf) };
  for (const [key, kind, column] of dialogAxes(meta)) {
    for (const [name, value] of Object.entries(axisAttributes(settingsOf(column), kind))) {
      update[`${key}.${name}`] = value;
    }
  }
  for (const [key, role, column] of angleAxes(meta)) update[`${key}.tickangle`] = angleOf(role, column);
  return update;
}

function withoutNulls(attributes) {
  return Object.fromEntries(Object.entries(attributes).filter(([, value]) => value !== null));
}

// plotly's drag areas of the axes (`ewdrag` along x, `nsdrag` along y, and
// their ends), each in the group of its subplot (`x2y2`).
const AXIS_DRAGS = { ewdrag: "x", wdrag: "x", edrag: "x", nsdrag: "y", sdrag: "y", ndrag: "y" };

// Returns the axis column (of any kind) under a pointer event on `gd`, the plot
// of the result `meta`, as `{axis: "x" | "y", index}` (of `x_columns` or
// `y_columns`), or null. Only the drag areas of the tick labels count,
// outside every panel: an axis's area reaches over the edge of a
// neighboring panel, whose double click resets the view.
export function axisAt(event, gd, meta) {
  const drag = event.target.closest?.(".draglayer rect.drag");
  if (!drag || !meta) return null;
  const axis = [...drag.classList].map((name) => AXIS_DRAGS[name]).find(Boolean);
  const subplot = drag.parentElement?.getAttribute("class")?.match(/^(x\d*)(y\d*)$/);
  if (!axis || !subplot) return null;
  const full = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  for (const panel of meta.panels) {
    const xa = full[panel.xaxis.replace(/^x/, "xaxis")];
    const ya = full[panel.yaxis.replace(/^y/, "yaxis")];
    if (!xa || !ya) continue;
    const inside =
      px >= xa._offset && px <= xa._offset + xa._length && py >= ya._offset && py <= ya._offset + ya._length;
    if (inside) return null;
  }
  const id = axis === "x" ? subplot[1] : subplot[2];
  const panel = meta.panels.find((p) => (axis === "x" ? p.xaxis : p.yaxis) === id);
  if (!panel) return null;
  const index = axis === "x" ? panel.x : panel.y;
  return { axis, index };
}

// Returns the y axis column whose left margin holds a point (client
// coordinates) of the plot `gd` of the result `meta`, as `{axis: "y", index}`,
// or null: right of `from` (the right edge of the y zone, which keeps its
// chips and drops) and left of the plot area of the leftmost panel at the
// point's height, from that panel's top to its bottom. The whole margin is
// its axis's, not only plotly's drag area along the tick labels: gaps
// between the labels, above them and left of them count. The margins
// between panel rows, above the top row and below the bottom row are no
// axis's. Laid out as drawn: null before the plot is drawn.
export function yMarginAt(clientX, clientY, gd, meta, from) {
  const full = gd._fullLayout;
  if (!meta || !full || clientX <= from) return null;
  const origin = gd.getBoundingClientRect();
  let left = Infinity;
  let index = null;
  for (const panel of meta.panels) {
    const xa = full[panel.xaxis.replace(/^x/, "xaxis")];
    const ya = full[panel.yaxis.replace(/^y/, "yaxis")];
    if (!xa || !ya) continue;
    const top = origin.top + ya._offset;
    if (clientY < top || clientY > top + ya._length) continue;
    if (origin.left + xa._offset < left) {
      left = origin.left + xa._offset;
      index = panel.y;
    }
  }
  return index !== null && clientX < left ? { axis: "y", index } : null;
}

// Returns the axis column whose tick label drawn by plotly holds a point
// (client coordinates) of the plot `gd` of the result `meta`, as `{axis,
// index}`, or null. A label turned to an angle reaches out of plotly's drag
// area of its axis: an x label below it, a y label above or below its
// panel's margin (`yMarginAt`); a point in a panel's plot area is the
// panel's.
export function labelAt(clientX, clientY, gd, meta) {
  const full = gd._fullLayout;
  if (!meta || !full) return null;
  const origin = gd.getBoundingClientRect();
  const within = (r) => clientX >= r.left && clientX <= r.right && clientY >= r.top && clientY <= r.bottom;
  let hit = null;
  for (const panel of meta.panels) {
    const xa = full[panel.xaxis.replace(/^x/, "xaxis")];
    const ya = full[panel.yaxis.replace(/^y/, "yaxis")];
    if (!xa || !ya) continue;
    const area = {
      left: origin.left + xa._offset,
      right: origin.left + xa._offset + xa._length,
      top: origin.top + ya._offset,
      bottom: origin.top + ya._offset + ya._length,
    };
    if (within(area)) return null;
    for (const [axis, id, index] of [
      ["x", panel.xaxis, panel.x],
      ["y", panel.yaxis, panel.y],
    ]) {
      if (hit) break;
      for (const text of gd.querySelectorAll(`.${id}tick text`)) {
        if (within(text.getBoundingClientRect())) {
          hit = { axis, index };
          break;
        }
      }
    }
  }
  return hit;
}

// Writes a number into a field, as the shortest text that reads back the
// same number: a rounded one could make the range of a deep zoom empty, or
// change the settings when they are applied again.
function numberText(value) {
  return value === null || value === undefined ? "" : String(value);
}

let open = null;

// Opens the dialog of an axis column of `kind` (`dialogKind`). `title` heads
// it ("X 軸: x"), `range` is the range shown (ascending), `settings` the
// column's (`emptySettings` for none), `drawn` plotly's interval of the
// drawn axis (`drawnUnit`), `angle` that of its tick labels (null for
// plotly's own). `onApply(settings, range, angle)` draws them, on OK
// (which closes the dialog) and on Apply (which keeps it open); Cancel and
// Esc close it, keeping what was applied. An end left as written is the
// very value it was written from, so that applying a range left alone
// moves no axis. A categorical axis shows the fields of a numeric one
// disabled: only the angle is checked and applied (`onApply(null, null,
// angle)`). A temporal axis has no angle (`angle` undefined to `onApply`).
export function openAxisDialog({ title, kind = "number", range, settings, drawn = null, angle = null, onApply }) {
  const category = kind === "category";
  if (category) kind = "number";
  const temporal = kind !== "number";
  open?.close();
  const dialog = document.createElement("dialog");
  dialog.className = "axis-dialog";
  const head = document.createElement("h2");
  head.className = "axis-dialog-title";
  head.textContent = title;
  dialog.append(head);

  const errors = new Map();
  const field = (section, label, value, name, placeholder = "") => {
    const row = document.createElement("label");
    row.className = "axis-dialog-field";
    const text = document.createElement("span");
    text.className = "axis-dialog-label";
    text.textContent = label;
    const input = document.createElement("input");
    const typed = isDateKind(kind) && ["min", "max", "line"].includes(name) ? "text" : "decimal";
    Object.assign(input, { type: "text", inputMode: typed, value, placeholder, name });
    input.spellcheck = false;
    const error = document.createElement("span");
    error.className = "axis-dialog-error";
    errors.set(name, error);
    row.append(text, input);
    // The values of a duration are seconds.
    if (kind === "duration" && ["min", "max", "line"].includes(name)) {
      const unit = document.createElement("span");
      unit.className = "axis-dialog-unit";
      unit.textContent = "秒";
      row.append(unit);
    }
    row.append(error);
    section.append(row);
    return input;
  };
  const section = (heading) => {
    const box = document.createElement("section");
    box.className = "axis-dialog-section";
    const h = document.createElement("h3");
    h.textContent = heading;
    box.append(h);
    dialog.append(box);
    return box;
  };

  const rangeBox = section("範囲");
  const min = field(rangeBox, "最小値", valueText(kind, range[0]), "min");
  const max = field(rangeBox, "最大値", valueText(kind, range[1]), "max");
  // The ends as written, and the values they stand for (`readFields`).
  let known = {
    min: { text: min.value, value: range[0] },
    max: { text: max.value, value: range[1] },
  };
  const ticksBox = section("目盛り");
  const dtick = field(ticksBox, "間隔", numberText(settings.dtick), "dtick", "自動");
  // The unit of a temporal interval: the one set, else that of plotly's ticks.
  const unit = document.createElement("select");
  unit.name = "unit";
  unit.title = "間隔の単位。1 日は 24 時間、1 週は 7 日";
  const picked = settings.dtick !== null && settings.unit ? settings.unit : drawnUnit(kind, drawn);
  for (const [key, text] of UNITS) unit.append(new Option(text, key, false, key === picked));
  if (temporal) dtick.after(unit);
  const minor = field(ticksBox, "補助目盛りの数", numberText(settings.minor), "minor", "なし");
  minor.inputMode = "numeric";
  const most = temporal ? MAX_TEMPORAL_MINOR : MAX_MINOR;
  minor.title = `主目盛りの 1 間隔を何分割するか（2〜${most}）。間隔を入れたときだけ使える`;
  // The format of the labels. A field the format does not use is disabled
  // but keeps what was typed, shown again when a format using it is picked.
  const format = document.createElement("select");
  format.name = "format";
  for (const [key, text] of FORMATS) format.append(new Option(text, key, false, key === settings.format));
  const formatRow = document.createElement("label");
  formatRow.className = "axis-dialog-field";
  const formatLabel = document.createElement("span");
  formatLabel.className = "axis-dialog-label";
  formatLabel.textContent = "表示形式";
  formatRow.append(formatLabel, format);
  ticksBox.append(formatRow);
  const digits = field(ticksBox, "小数桁数", numberText(settings.digits ?? DEFAULT_DIGITS), "digits");
  digits.inputMode = "numeric";
  const separators = document.createElement("input");
  Object.assign(separators, { type: "checkbox", name: "separators", checked: settings.separators });
  const separatorsRow = document.createElement("label");
  separatorsRow.className = "axis-dialog-field axis-dialog-check";
  separatorsRow.append(separators, "3 桁区切り (,)");
  ticksBox.append(separatorsRow);
  const usable = () => {
    digits.disabled = !USES_DIGITS.has(format.value);
    separators.disabled = !USES_SEPARATORS.has(format.value);
    if (digits.disabled) errors.get("digits").textContent = "";
  };
  format.addEventListener("change", usable);
  usable();
  // A temporal axis keeps plotly's labels: no format to pick, nor angle.
  if (temporal) {
    for (const row of [formatRow, digits.parentElement, separatorsRow]) row.remove();
  }
  const turn = temporal ? null : field(ticksBox, "ラベルの角度 (°)", angle === null ? "" : String(angle), "angle", "自動");
  if (turn) {
    turn.inputMode = "numeric";
    turn.title = "−90〜90 の整数。0 は水平、正は時計回り。空欄は自動";
    turn.parentElement.classList.add("axis-dialog-angle");
  }

  const linesBox = section("参照線");
  const value = field(linesBox, "値", "", "line");
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "追加";
  value.parentElement.insertBefore(add, errors.get("line"));
  const list = document.createElement("div");
  list.className = "axis-dialog-lines";
  linesBox.append(list);
  let lines = settings.lines.map((line) => ({ ...line }));

  const renderLines = () => {
    list.replaceChildren(
      ...lines.map((line, i) => {
        const row = document.createElement("div");
        row.className = "axis-dialog-line";
        const at = document.createElement("span");
        at.className = "axis-dialog-line-value";
        at.textContent = valueText(kind, line.value);
        const color = document.createElement("input");
        Object.assign(color, { type: "color", value: line.color, title: "色" });
        color.addEventListener("input", () => {
          line.color = color.value;
        });
        const dash = document.createElement("select");
        dash.title = "線の種類";
        for (const [key, text] of DASHES) dash.append(new Option(text, key, false, key === line.dash));
        dash.addEventListener("change", () => {
          line.dash = dash.value;
        });
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "削除";
        remove.addEventListener("click", () => {
          lines = lines.filter((_, j) => j !== i);
          renderLines();
        });
        row.append(at, color, dash, remove);
        return row;
      }),
    );
    list.hidden = !lines.length;
  };
  renderLines();

  const addLine = () => {
    const read = readValue(kind, value.value);
    errors.get("line").textContent = read.error ?? "";
    if (read.error) return;
    lines = [...lines, { value: read.value, color: LINE_COLOR, dash: LINE_DASH }];
    value.value = "";
    renderLines();
  };
  add.addEventListener("click", addLine);
  value.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    addLine();
  });

  // A categorical axis takes the angle alone: the other fields show, but
  // can be neither edited nor focused.
  if (category) {
    for (const control of dialog.querySelectorAll("input, select, button")) {
      if (control === turn) continue;
      control.disabled = true;
      control.closest(".axis-dialog-field, .axis-dialog-line")?.classList.add("off");
    }
  }

  // Applies the fields, or shows why not; returns whether they were applied.
  const apply = () => {
    const turned = turn ? readAngle(turn.value) : { value: undefined };
    if (turn) errors.get("angle").textContent = turned.error ?? "";
    if (category) {
      if (turned.error) return false;
      onApply(null, null, turned.value);
      return true;
    }
    const read = readFields({
      kind,
      min: min.value,
      max: max.value,
      dtick: dtick.value,
      unit: unit.value,
      minor: minor.value,
      format: format.value,
      digits: digits.value,
      separators: separators.checked,
      known,
    });
    for (const name of ["min", "max", "dtick", "minor", "digits"]) {
      errors.get(name).textContent = read.errors?.[name] ?? "";
    }
    if (read.errors || turned.error) return false;
    known = {
      min: { text: min.value, value: read.range[0] },
      max: { text: max.value, value: read.range[1] },
    };
    onApply(
      {
        dtick: read.dtick,
        unit: read.unit,
        minor: read.minor,
        lines: lines.map((line) => ({ ...line })),
        format: read.format,
        digits: read.digits,
        separators: read.separators,
      },
      read.range,
      turned.value,
    );
    return true;
  };

  const buttons = document.createElement("div");
  buttons.className = "axis-dialog-buttons";
  const button = (text, run) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = text;
    b.addEventListener("click", run);
    buttons.append(b);
    return b;
  };
  button("OK", () => {
    if (apply()) dialog.close();
  }).classList.add("primary");
  button("キャンセル", () => dialog.close());
  button("適用", apply);
  dialog.append(buttons);

  // Enter in a field of the range or ticks, or in the angle, is OK; Esc is
  // Cancel (the dialog's own).
  for (const input of [min, max, dtick, minor, digits, turn].filter(Boolean)) {
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      if (apply()) dialog.close();
    });
  }
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (open === dialog) open = null;
  });
  document.body.append(dialog);
  open = dialog;
  dialog.showModal();
  const first = category ? turn : min;
  first.focus();
  first.select();
  return dialog;
}
