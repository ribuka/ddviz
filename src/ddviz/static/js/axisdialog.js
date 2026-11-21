// The settings of a numeric or temporal axis, opened by a double click on
// its tick labels: its range, the interval of its ticks, how many minor
// ticks split each interval, and reference lines across its panels: at a
// value, or at the mean plus or minus n standard deviations or a quantile
// of each panel's rows (a numeric axis's, found by the server: the panel's
// `ref_stats`, `refstats.js`). The panels of one
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

import { axisKey } from "./axiskey.js";
import { plainEnter } from "./keys.js";
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
// The kinds of reference line (`type` of a line of the settings): at a value
// of the axis, at the mean plus or minus n standard deviations (`value` is
// n), at a quantile (`value` is the percentile); and the unit written after
// the field of each.
export const LINE_TYPES = [
  ["value", "値"],
  ["sigma", "平均 ± nσ"],
  ["quantile", "分位"],
];
const LINE_UNITS = { sigma: "σ", quantile: "%" };
// The size of the labels of the lines of the statistics, in pixels.
const LABEL_SIZE = 11;
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
// The calendar units of the interval of a date or datetime axis, in
// months: plotly's "M<n>" intervals, which follow the lengths of the months
// and leap years. Their minor ticks are one unit each, checked or not.
export const CALENDAR_UNITS = [
  ["month", "月", 1],
  ["year", "年", 12],
];
const UNIT_MONTHS = Object.fromEntries(CALENDAR_UNITS.map(([key, , months]) => [key, months]));
const COUNT_ERROR = "有効な正の整数を入力してください";
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
// `unit` is that of the interval of a temporal axis (`UNITS`,
// `CALENDAR_UNITS`), null without one. `minor` is the number of parts the
// interval is split into: with a calendar unit, the interval itself (a
// minor tick every month or year), null without them.
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

// Whether an axis of `kind` takes the calendar units: a datetime or date
// axis, not a time's (a day long) nor a duration's.
export function hasCalendar(kind) {
  return kind === "datetime" || kind === "date";
}

// Whether `unit` is a calendar unit (`CALENDAR_UNITS`).
function isCalendar(unit) {
  return Object.hasOwn(UNIT_MONTHS, unit ?? "");
}

// Reads the interval of a calendar `unit` typed in a field: `{value}` (a
// positive integer whose months are a safe integer), `{value: null}` for
// an empty field, or `{error}`. Only ASCII digits.
export function readCount(text, unit) {
  const trimmed = text.trim();
  if (trimmed === "") return { value: null };
  if (!/^[0-9]+$/.test(trimmed)) return { error: COUNT_ERROR };
  const value = Number(trimmed);
  if (value === 0 || !Number.isSafeInteger(value * UNIT_MONTHS[unit])) return { error: COUNT_ERROR };
  return { value };
}

// Returns the unit picked for the interval of a temporal axis of `kind`
// without one set, from plotly's interval `drawn` of its axis (`dtick`:
// milliseconds on a date axis, seconds of a duration, "M<n>" for months
// and years): the largest unit up to it, milliseconds below them; for
// "M<n>", years when n is a multiple of 12 and months otherwise (weeks on
// an axis without calendar units); a day for a date and a second otherwise
// when there is none.
export function drawnUnit(kind, drawn) {
  const months = typeof drawn === "string" ? drawn.match(/^M(\d+)$/) : null;
  if (months) {
    if (!hasCalendar(kind)) return "week";
    return Number(months[1]) % 12 === 0 ? "year" : "month";
  }
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

// Reads the number of a reference line of `type` (`LINE_TYPES`) typed in a
// field of an axis of `kind`: `{value}` or `{error}`. A value is the axis's
// (`readValue`); the n of the standard deviations is a finite number from
// 0, the percentile one from 0 to 100.
export function readLine(kind, type, text) {
  if (type === "value") return readValue(kind, text);
  const read = readNumber(text);
  if (read.error) return read;
  const value = read.value === 0 ? 0 : read.value;
  if (type === "sigma") return value < 0 ? { error: "0 以上の数を入れてください" } : { value };
  return value < 0 || value > 100 ? { error: "0〜100 の数を入れてください" } : { value };
}

// Returns the text a reference line of an axis of `kind` is listed with:
// its value, "平均 ± 3σ" ("平均" for n = 0) or "分位 95%".
export function lineText(kind, line) {
  if (line.type === "sigma") return line.value === 0 ? "平均" : `平均 ± ${String(line.value)}σ`;
  if (line.type === "quantile") return `分位 ${String(line.value)}%`;
  return valueText(kind, line.value);
}

// Returns the text the field of a reference line's edit starts from: the
// value as listed, or the n or percentile alone.
function editText(kind, line) {
  return line.type === "value" ? valueText(kind, line.value) : numberText(line.value);
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

// Returns the range and end-field errors. Reuses a known end when its text
// is unchanged because the displayed text of a temporal value is rounded.
function readRangeFields(kind, min, max, known) {
  const errors = {};
  const end = (name, text) => (known[name]?.text === text ? { value: known[name].value } : readValue(kind, text));
  const lo = end("min", min);
  const hi = end("max", max);
  if (lo.error) errors.min = lo.error;
  if (hi.error) errors.max = hi.error;
  if (!lo.error && !hi.error && lo.value >= hi.value) errors.max = "最小値より大きくしてください";
  return { range: [lo.value, hi.value], errors };
}

// Reads a fixed interval as {value} or {error}, allowing an empty field.
function readFixedStep(kind, text, unit) {
  const step = readNumber(text, true);
  if (step.error || step.value === null) return step;
  if (step.value <= 0) return { error: "0 より大きくしてください" };
  if (kind !== "number") {
    const size = plotlyStep(kind, step.value, unit);
    if (!(Number.isFinite(size) && size > 0)) return { error: "この単位では使えない間隔です" };
  }
  return step;
}

// Reads fixed minor splits as {value} or {error}. A valid split needs a
// step; an invalid step already has its own error.
function readMinorSplits(text, most, step) {
  const parts = readNumber(text, true);
  if (parts.error || parts.value === null) return parts;
  if (!Number.isInteger(parts.value) || parts.value < 2 || parts.value > most) {
    return { error: `2〜${most} の整数にしてください` };
  }
  if (step.value === null) return { error: "間隔を入れたときだけ使えます" };
  return parts;
}

// Returns the interval, unit, minor ticks and errors. Calendar units use
// the checkbox from an interval of 2 on and skip the minor splits field.
function readTickFields(kind, dtick, unit, minor, calendarMinor) {
  const errors = {};
  const temporal = kind !== "number";
  const calendar = hasCalendar(kind) && isCalendar(unit);
  const step = calendar ? readCount(dtick, unit) : readFixedStep(kind, dtick, unit);
  if (step.error) errors.dtick = step.error;
  const most = temporal ? MAX_TEMPORAL_MINOR : MAX_MINOR;
  const parts = calendar
    ? { value: calendarMinor && step.value >= 2 ? step.value : null }
    : readMinorSplits(minor, most, step);
  if (parts.error) errors.minor = parts.error;
  return {
    dtick: step.value,
    unit: temporal && step.value !== null ? unit : null,
    minor: parts.value,
    errors,
  };
}

// Returns the label format, digits, separators and errors, checking and
// keeping only the fields used by the chosen format on a numeric axis.
function readNumericFormatFields(kind, format, digits, separators) {
  const errors = {};
  if (kind !== "number") return { format: "auto", digits: null, separators: false, errors };
  let places = null;
  if (USES_DIGITS.has(format)) {
    const trimmed = digits.trim();
    places = /^[0-9]+$/.test(trimmed) ? Number(trimmed) : NaN;
    if (!(places <= MAX_DIGITS)) errors.digits = `0〜${MAX_DIGITS} の整数にしてください`;
  }
  return {
    format,
    digits: places,
    separators: USES_SEPARATORS.has(format) && separators,
    errors,
  };
}

// Returns the dialog's {range, dtick, unit, minor, format, digits,
// separators} or all field errors as {errors: {field: text}}.
export function readFields({
  kind = "number",
  min,
  max,
  dtick,
  unit = null,
  minor,
  calendarMinor = false,
  format = "auto",
  digits = "",
  separators = false,
  known = {},
}) {
  const bounds = readRangeFields(kind, min, max, known);
  const ticks = readTickFields(kind, dtick, unit, minor, calendarMinor);
  const labels = readNumericFormatFields(kind, format, digits, separators);
  const errors = { ...bounds.errors, ...ticks.errors, ...labels.errors };
  if (Object.keys(errors).length) return { errors };
  return {
    range: bounds.range,
    dtick: ticks.dtick,
    unit: ticks.unit,
    minor: ticks.minor,
    format: labels.format,
    digits: labels.digits,
    separators: labels.separators,
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
// time's midnight) or at 0 seconds, every `dtick` of its unit. Those of a
// calendar unit (on a datetime or date axis) are plotly's "M<n>" from
// 1970-01-01, with a minor grid line every month or year (plotly draws
// none where a major tick is); on another axis, plotly's own.
export function tickAttributes(settings, kind = "number") {
  const { dtick, unit, minor } = { ...emptySettings(), ...settings };
  const auto = { tickmode: null, tick0: null, dtick: null, minor: null };
  if (dtick === null) return auto;
  if (isCalendar(unit)) {
    if (!hasCalendar(kind)) return auto;
    const tick0 = dateText(0);
    const months = UNIT_MONTHS[unit];
    return {
      tickmode: "linear",
      tick0,
      dtick: `M${dtick * months}`,
      minor: minor === null ? null : { tick0, dtick: `M${months}`, showgrid: true },
    };
  }
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

// Returns where a reference line lies on a panel of an axis of `kind`, as
// `[at, label]` pairs: a value's line at its value (plotly's date text on a
// date axis, `dateText`) without a label; the lines of the statistics at the
// values of the panel's rows (`stats`: its `ref_stats` of the line's axis,
// null for none), on a numeric axis only. n > 0 standard deviations draw two
// lines ("+3σ", "−3σ"), none without a deviation (a single row); n = 0 the
// mean ("μ"); a quantile one line ("P95", "中央値" for 50).
function linePlaces(kind, line, stats) { // noqa: C901
  if (line.type === "value") return [[isDateKind(kind) ? dateText(line.value) : line.value, null]];
  if (kind !== "number" || !stats) return [];
  if (line.type === "sigma") {
    if (stats.mean === null) return [];
    if (line.value === 0) return [[stats.mean, "μ"]];
    if (stats.std === null) return [];
    const n = String(line.value);
    const step = line.value * stats.std;
    return [
      [stats.mean + step, `+${n}σ`],
      [stats.mean - step, `−${n}σ`],
    ];
  }
  if (line.type === "quantile") {
    const found = stats.quantiles.find(([p]) => p === line.value);
    return found ? [[found[1], line.value === 50 ? "中央値" : `P${String(line.value)}`]] : [];
  }
  return [];
}

// Returns the plotly shapes of the reference lines of every axis column of
// a result (`meta`) with a dialog (`axisKind`): a vertical line across each
// panel of an x column, a horizontal one across each panel of a y column,
// each panel's own for the lines of the statistics (`linePlaces`). Their
// labels lie inside the panel, level, in the line's color: a horizontal
// line's above it at the right end, a vertical one's right of it at the top.
function lineShapes(meta, settingsOf) { // noqa: C901
  const shapes = [];
  for (const panel of meta.panels) {
    const across = [
      [axisKind(meta, "x", panel.x), meta.x_columns[panel.x], panel.xaxis, panel.yaxis, "x"],
      [axisKind(meta, "y", panel.y), meta.y_columns[panel.y], panel.yaxis, panel.xaxis, "y"],
    ];
    for (const [kind, column, along, other, axis] of across) {
      const settings = kind ? settingsOf(column) : undefined;
      const [ref, otherRef] = axis === "x" ? ["xref", "yref"] : ["yref", "xref"];
      const [at0, at1, span0, span1] = axis === "x" ? ["x0", "x1", "y0", "y1"] : ["y0", "y1", "x0", "x1"];
      for (const line of settings?.lines ?? []) {
        for (const [at, text] of linePlaces(kind, line, panel.ref_stats?.[axis] ?? null)) {
          const shape = {
            type: "line",
            layer: "above",
            [ref]: along,
            [otherRef]: `${other} domain`,
            [at0]: at,
            [at1]: at,
            [span0]: 0,
            [span1]: 1,
            line: { color: line.color, dash: line.dash, width: LINE_WIDTH },
          };
          if (text !== null) {
            shape.label = {
              text,
              textposition: "end",
              textangle: 0,
              xanchor: axis === "x" ? "left" : "right",
              yanchor: axis === "x" ? "top" : "bottom",
              font: { size: LABEL_SIZE, color: line.color },
            };
          }
          shapes.push(shape);
        }
      }
    }
  }
  return shapes;
}

// Returns the axes of the panels of `meta`, as `[key, role, index]`
// (`xaxis2`, "x" or "y", the index of the axis column).
function panelAxes(meta) {
  return meta.panels.flatMap((panel) => [
    [axisKey(panel.xaxis), "x", panel.x],
    [axisKey(panel.yaxis), "y", panel.y],
  ]);
}

// Returns the axes of the panels of `meta` with a dialog, as `[key, kind,
// column]` (`xaxis2`, `axisKind`, the axis column).
function dialogAxes(meta) {
  return panelAxes(meta)
    .map(([key, role, index]) => [key, axisKind(meta, role, index), meta[`${role}_columns`][index]])
    .filter(([, kind]) => kind);
}

// Returns the axes of the panels of `meta` whose labels take an angle
// (`hasAngle`), as `[key, role, column]`.
function angleAxes(meta) {
  return panelAxes(meta)
    .filter(([, role, index]) => hasAngle(meta, role, index))
    .map(([key, role, index]) => [key, role, meta[`${role}_columns`][index]]);
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

// Writes a number into a field, as the shortest text that reads back the
// same number: a rounded one could make the range of a deep zoom empty, or
// change the settings when they are applied again.
function numberText(value) {
  return value === null || value === undefined ? "" : String(value);
}

let open = null;

// The dialog being built: the <dialog>, the kind of its axis ("number",
// a temporal kind; a categorical axis builds a numeric one), and the error
// line of each field by name. `section(heading)` appends a section;
// `field(section, label, value, name, placeholder)` appends a labeled text
// field with its error line (and "秒" for a duration's values) and returns its input.
class DialogForm {
  constructor(kind) {
    this.kind = kind;
    this.dialog = document.createElement("dialog");
    this.dialog.className = "axis-dialog";
    this.errors = new Map();
  }

  section(heading) {
    const box = document.createElement("section");
    box.className = "axis-dialog-section";
    const h = document.createElement("h3");
    h.textContent = heading;
    box.append(h);
    this.dialog.append(box);
    return box;
  }

  field(section, label, value, name, placeholder = "") {
    const row = document.createElement("label");
    row.className = "axis-dialog-field";
    const text = document.createElement("span");
    text.className = "axis-dialog-label";
    text.textContent = label;
    const input = document.createElement("input");
    const typed = isDateKind(this.kind) && ["min", "max", "line"].includes(name) ? "text" : "decimal";
    Object.assign(input, { type: "text", inputMode: typed, value, placeholder, name });
    input.spellcheck = false;
    const error = document.createElement("span");
    error.className = "axis-dialog-error";
    this.errors.set(name, error);
    row.append(text, input);
    // The values of a duration are seconds.
    if (this.kind === "duration" && ["min", "max", "line"].includes(name)) {
      const unit = document.createElement("span");
      unit.className = "axis-dialog-unit";
      unit.textContent = "秒";
      row.append(unit);
    }
    row.append(error);
    section.append(row);
    return input;
  }
}

// The range's fields: {min, max, known()}; `known()` is the ends as written
// and the values they stand for (`readFields`), `remember(range)` sets it
// after an apply.
function rangeFields(form, range) {
  const box = form.section("範囲");
  const min = form.field(box, "最小値", valueText(form.kind, range[0]), "min");
  const max = form.field(box, "最大値", valueText(form.kind, range[1]), "max");
  // The ends as written, and the values they stand for (`readFields`).
  const written = (values) => ({
    min: { text: min.value, value: values[0] },
    max: { text: max.value, value: values[1] },
  });
  let known = written(range);
  return {
    min,
    max,
    known: () => known,
    remember: (applied) => {
      known = written(applied);
    },
  };
}

// The ticks' fields: {dtick, unit, minor, monthly, format, digits,
// separators, turn, calendarFields}; `turn` is null on a temporal axis.
function tickFields(form, settings, drawn, angle) { // noqa: C901, PLR0915
  const { kind, errors } = form;
  const temporal = kind !== "number";
  const box = form.section("目盛り");
  const dtick = form.field(box, "間隔", numberText(settings.dtick), "dtick", "自動");
  // The unit of a temporal interval: the one set, else that of plotly's ticks.
  const calendar = hasCalendar(kind);
  const unit = document.createElement("select");
  unit.name = "unit";
  unit.title = `間隔の単位。1 日は 24 時間、1 週は 7 日${calendar ? "。月・年は暦に沿う" : ""}`;
  const picked = settings.dtick !== null && settings.unit ? settings.unit : drawnUnit(kind, drawn);
  for (const [key, text] of [...UNITS, ...(calendar ? CALENDAR_UNITS : [])]) {
    unit.append(new Option(text, key, false, key === picked));
  }
  if (temporal) dtick.after(unit);
  // The minor splits of a fixed interval, and in their place the check of
  // the minor ticks of a calendar one: two inputs, neither turned into the other.
  const setCalendar = isCalendar(settings.unit);
  const minor = form.field(box, "補助目盛りの数", setCalendar ? "" : numberText(settings.minor), "minor", "なし");
  minor.inputMode = "numeric";
  const most = temporal ? MAX_TEMPORAL_MINOR : MAX_MINOR;
  minor.title = `主目盛りの 1 間隔を何分割するか（2〜${most}）。間隔を入れたときだけ使える`;
  const monthly = document.createElement("input");
  Object.assign(monthly, { type: "checkbox", name: "calendar-minor" });
  monthly.checked = setCalendar && settings.minor !== null;
  const monthlyText = document.createElement("span");
  const monthlyRow = document.createElement("label");
  monthlyRow.className = "axis-dialog-field axis-dialog-check";
  monthlyRow.title = "間隔が 2 以上のときだけ使える";
  monthlyRow.append(monthly, monthlyText);
  if (calendar) minor.parentElement.after(monthlyRow);
  // Shows the input of the unit picked. The check is usable from an
  // interval of 2 on, and keeps its state while it is not.
  const calendarFields = () => {
    const on = calendar && isCalendar(unit.value);
    minor.parentElement.hidden = on;
    monthlyRow.hidden = !on;
    monthlyText.textContent = unit.value === "year" ? "1年ごとに補助目盛りを表示" : "1か月ごとに補助目盛りを表示";
    monthly.disabled = !(on && readCount(dtick.value, unit.value).value >= 2);
    monthlyRow.classList.toggle("off", monthly.disabled);
  };
  unit.addEventListener("change", calendarFields);
  dtick.addEventListener("input", calendarFields);
  calendarFields();
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
  box.append(formatRow);
  const digits = form.field(box, "小数桁数", numberText(settings.digits ?? DEFAULT_DIGITS), "digits");
  digits.inputMode = "numeric";
  const separators = document.createElement("input");
  Object.assign(separators, { type: "checkbox", name: "separators", checked: settings.separators });
  const separatorsRow = document.createElement("label");
  separatorsRow.className = "axis-dialog-field axis-dialog-check";
  separatorsRow.append(separators, "3 桁区切り (,)");
  box.append(separatorsRow);
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
  const turn = temporal ? null : form.field(box, "ラベルの角度 (°)", angle === null ? "" : String(angle), "angle", "自動");
  if (turn) {
    turn.inputMode = "numeric";
    turn.title = "−90〜90 の整数。0 は水平、正は時計回り。空欄は自動";
    turn.parentElement.classList.add("axis-dialog-angle");
  }
  return { dtick, unit, minor, monthly, format, digits, separators, turn, calendarFields };
}

// The pencil of a reference line's row (as `undo.js` writes its icons).
const PENCIL =
  '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" aria-hidden="true">' +
  '<path d="M11 2.5 13.5 5 5.5 13H3v-2.5z M9.5 4l2.5 2.5" stroke-width="1.5" stroke-linejoin="round"/></svg>';

// The reference lines: {value, lines(), settle()}; `lines()` returns copies
// of the lines listed. A line is added with its kind picked (`LINE_TYPES`;
// the statistics on a numeric axis only) and its number typed, the unit of
// the kind written after it; another kind keeps the text typed. The pencil
// of a row edits its value (a statistic's n or percentile) in place: Enter
// or leaving the field replaces the value alone (its color, dash and place
// kept), Esc puts the value back; a wrong value shows why on the row and
// keeps the field. `settle()` ends an edit left in the field, and returns
// false (focusing the field) while its value is wrong.
function lineFields(form, settings) {
  const { kind, errors } = form;
  const box = form.section("参照線");
  const adding = document.createElement("div");
  adding.className = "axis-dialog-field axis-dialog-add-line";
  const type = document.createElement("select");
  Object.assign(type, { name: "line-type", className: "axis-dialog-line-type", title: "参照線の種類" });
  for (const [key, text] of LINE_TYPES) {
    const option = new Option(text, key, key === "value", key === "value");
    // The statistics of the panels' rows are of a numeric column alone.
    option.disabled = key !== "value" && kind !== "number";
    type.append(option);
  }
  const value = document.createElement("input");
  Object.assign(value, { type: "text", inputMode: isDateKind(kind) ? "text" : "decimal", value: "", name: "line" });
  value.spellcheck = false;
  value.setAttribute("aria-label", "参照線の値");
  // The unit of the kind picked; a duration's values are seconds.
  const unit = document.createElement("span");
  unit.className = "axis-dialog-unit";
  const showUnit = () => {
    unit.textContent = LINE_UNITS[type.value] ?? (kind === "duration" ? "秒" : "");
  };
  type.addEventListener("change", showUnit);
  showUnit();
  const add = Object.assign(document.createElement("button"), { type: "button", textContent: "追加" });
  const lineError = document.createElement("span");
  lineError.className = "axis-dialog-error";
  errors.set("line", lineError);
  adding.append(type, value, unit, add, lineError);
  box.append(adding);
  const list = document.createElement("div");
  list.className = "axis-dialog-lines";
  box.append(list);
  let lines = settings.lines.map((line) => ({ ...line }));
  // The edit under way: the row's index, the text it started from (the
  // value as listed), the text in its field, why it is wrong ("" for not
  // shown yet), and the field and error line drawn; null for none.
  let editing = null;
  // Whether the rows are being drawn again: the field taken out of the list
  // then may lose focus, which must not end its edit a second time.
  let rendering = false;
  // Whether a pointer is pressed in the dialog, and whether the field lost
  // the focus to that press: the edit then ends after the press's click
  // (which may itself end it: another pencil, OK, Apply).
  let pressing = false;
  let leftWhilePressing = false;
  form.dialog.addEventListener("pointerdown", () => {
    pressing = true;
  }, true);
  const released = () => {
    // After the click that follows the release.
    setTimeout(() => {
      pressing = false;
      if (!leftWhilePressing) return;
      leftWhilePressing = false;
      if (editing && document.activeElement !== editing.input) commit();
    });
  };
  form.dialog.addEventListener("pointerup", released, true);
  form.dialog.addEventListener("pointercancel", released, true);
  const valueSpan = (line) => {
    const at = document.createElement("span");
    at.className = "axis-dialog-line-value";
    at.textContent = lineText(kind, line);
    return at;
  };
  // Shows the value of the row edited again in place of its field, leaving
  // the rest of the list as it is: a click that ended the edit by taking
  // the focus (another pencil, a "削除", the color) still lands on its
  // control, and Tab still moves on.
  const endEdit = () => {
    const { index, input, errorLine } = editing;
    editing = null;
    input.replaceWith(valueSpan(lines[index]));
    errorLine.remove();
  };
  const renderLines = () => {
    rendering = true;
    list.replaceChildren(
      ...lines.map((line, i) => {
        const row = document.createElement("div");
        row.className = "axis-dialog-line";
        const edit = document.createElement("button");
        Object.assign(edit, { type: "button", className: "axis-dialog-line-edit", title: "値を編集", innerHTML: PENCIL });
        edit.setAttribute("aria-label", "値を編集");
        edit.addEventListener("click", () => startEdit(i));
        let at;
        if (editing?.index === i) {
          at = document.createElement("input");
          Object.assign(at, { type: "text", className: "axis-dialog-line-input", value: editing.text });
          at.inputMode = isDateKind(kind) && line.type === "value" ? "text" : "decimal";
          at.spellcheck = false;
          editing.input = at;
          const field = at;
          at.addEventListener("input", () => {
            if (editing?.input === field) editing.text = field.value;
          });
          at.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !event.isComposing) {
              // Esc takes back the edit only: the dialog stays open.
              event.preventDefault();
              event.stopPropagation();
              endEdit();
              list.children[i]?.querySelector(".axis-dialog-line-edit")?.focus();
              return;
            }
            if (!plainEnter(event)) return;
            event.preventDefault();
            if (commit()) list.children[i]?.querySelector(".axis-dialog-line-edit")?.focus();
          });
          at.addEventListener("blur", () => {
            if (rendering || editing?.input !== field) return;
            // A press that took the focus ends the edit once its click is
            // done: drawn back at once, the value could move the control
            // pressed away from under the pointer.
            if (pressing) leftWhilePressing = true;
            else commit();
          });
        } else {
          at = valueSpan(line);
        }
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
          if (editing?.index === i) editing = null;
          else if (editing && editing.index > i) editing.index -= 1;
          lines = lines.filter((_, j) => j !== i);
          renderLines();
        });
        row.append(edit, at, color, dash, remove);
        if (editing?.index === i) {
          const error = document.createElement("span");
          error.className = "axis-dialog-error";
          error.textContent = editing.error;
          editing.errorLine = error;
          row.append(error);
        }
        return row;
      }),
    );
    list.hidden = !lines.length;
    rendering = false;
  };
  // Ends the edit with the value in its field; returns whether it was right.
  // A right one replaces the line's value alone and shows the value again;
  // a wrong one says why. The text left as it started is the very value it
  // was written from (as `known` of the range): the text of a temporal
  // value is rounded to microseconds, which must not move the line.
  const commit = () => {
    if (editing.text !== editing.shown) {
      const read = readLine(kind, lines[editing.index].type, editing.text);
      if (read.error) {
        editing.error = read.error;
        editing.errorLine.textContent = read.error;
        return false;
      }
      lines[editing.index].value = read.value;
    }
    endEdit();
    return true;
  };
  // Ends an edit left in its field; false, focusing it, while it is wrong.
  const settle = () => {
    if (editing && !commit()) {
      editing.input.focus();
      return false;
    }
    return true;
  };
  // Edits the value of row `i`, when no edit with a wrong value is left.
  const startEdit = (i) => {
    if (!settle()) return;
    const shown = editText(kind, lines[i]);
    editing = { index: i, shown, text: shown, error: "", input: null, errorLine: null };
    renderLines();
    editing.input.focus();
    editing.input.select();
  };
  renderLines();
  const addLine = () => {
    const read = readLine(kind, type.value, value.value);
    lineError.textContent = read.error ?? "";
    if (read.error) return;
    lines = [...lines, { type: type.value, value: read.value, color: LINE_COLOR, dash: LINE_DASH }];
    value.value = "";
    renderLines();
  };
  add.addEventListener("click", addLine);
  value.addEventListener("keydown", (event) => {
    if (!plainEnter(event)) return;
    event.preventDefault();
    addLine();
  });
  return { value, lines: () => lines.map((line) => ({ ...line })), settle };
}

// Disables every control but `turn`, as a categorical axis has only its
// angle: the other fields show, but can be neither edited nor focused.
function angleOnly(dialog, turn) {
  for (const control of dialog.querySelectorAll("input, select, button")) {
    if (control === turn) continue;
    control.disabled = true;
    control.closest(".axis-dialog-field, .axis-dialog-line")?.classList.add("off");
  }
}

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
  open?.close();
  const form = new DialogForm(kind);
  const { dialog, errors } = form;
  const head = document.createElement("h2");
  head.className = "axis-dialog-title";
  head.textContent = title;
  dialog.append(head);

  const ends = rangeFields(form, range);
  const ticks = tickFields(form, settings, drawn, angle);
  const { turn } = ticks;
  const lines = lineFields(form, settings);
  if (category) angleOnly(dialog, turn);

  // Applies the fields, or shows why not; returns whether they were applied.
  const apply = () => {
    const turned = turn ? readAngle(turn.value) : { value: undefined };
    if (turn) errors.get("angle").textContent = turned.error ?? "";
    if (category) {
      if (turned.error) return false;
      onApply(null, null, turned.value);
      return true;
    }
    // An edit of a reference line's value left wrong applies nothing.
    if (!lines.settle()) return false;
    const read = readFields({
      kind,
      min: ends.min.value,
      max: ends.max.value,
      dtick: ticks.dtick.value,
      unit: ticks.unit.value,
      minor: ticks.minor.value,
      calendarMinor: ticks.monthly.checked,
      format: ticks.format.value,
      digits: ticks.digits.value,
      separators: ticks.separators.checked,
      known: ends.known(),
    });
    for (const name of ["min", "max", "dtick", "minor", "digits"]) {
      errors.get(name).textContent = read.errors?.[name] ?? "";
    }
    if (read.errors || turned.error) return false;
    ends.remember(read.range);
    // An empty interval or one of 1 applied takes the minor ticks off.
    if (hasCalendar(kind) && isCalendar(ticks.unit.value) && read.minor === null) {
      ticks.monthly.checked = false;
      ticks.calendarFields();
    }
    const { dtick, unit, minor, format, digits, separators } = read;
    onApply({ dtick, unit, minor, lines: lines.lines(), format, digits, separators }, read.range, turned.value);
    return true;
  };

  const buttons = document.createElement("div");
  buttons.className = "axis-dialog-buttons";
  const button = (text, run) => {
    const b = Object.assign(document.createElement("button"), { type: "button", textContent: text });
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
  for (const input of [ends.min, ends.max, ticks.dtick, ticks.minor, ticks.digits, turn].filter(Boolean)) {
    input.addEventListener("keydown", (event) => {
      if (!plainEnter(event)) return;
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
  const first = category ? turn : ends.min;
  first.focus();
  first.select();
  return dialog;
}
