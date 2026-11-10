// Values of temporal columns as text, and back. The server holds them as
// numbers (`ddviz.compute.temporal`): a datetime or date as milliseconds
// since the epoch, a time as milliseconds since midnight (both at their
// wall-clock time, read as UTC here), a duration as seconds. A datetime,
// date or time lies on plotly's date axis; a duration is a plain number.
// The text is that of `ddviz.shared.temporal.text`.

const DATE_KINDS = ["datetime", "date", "time"];
const US_PER_DAY = 86_400_000_000;

// Returns whether a column of `kind` (null for a non-temporal one) lies on a date axis.
export function isDateKind(kind) {
  return DATE_KINDS.includes(kind);
}

function pad(value, width) {
  return String(value).padStart(width, "0");
}

// Returns a value of a date kind as text: "2026-10-31 12:34:56.789000" (a
// datetime, always to the microsecond), "2026-10-31" (a date) or
// "12:34:56.789000" (a time); null for another kind or a value that is no date.
export function formatTemporal(kind, ms) {
  if (!isDateKind(kind) || typeof ms !== "number" || !Number.isFinite(ms)) return null;
  let us = Math.round(ms * 1000);
  if (kind === "time") us = ((us % US_PER_DAY) + US_PER_DAY) % US_PER_DAY;
  const seconds = Math.floor(us / 1e6);
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return null;
  const day = `${pad(date.getUTCFullYear(), 4)}-${pad(date.getUTCMonth() + 1, 2)}-${pad(date.getUTCDate(), 2)}`;
  const time = `${pad(date.getUTCHours(), 2)}:${pad(date.getUTCMinutes(), 2)}:${pad(date.getUTCSeconds(), 2)}.${pad(us - seconds * 1e6, 6)}`;
  if (kind === "date") return day;
  if (kind === "time") return time;
  return `${day} ${time}`;
}

const DAY = /^(\d{4})-(\d{1,2})-(\d{1,2})$/;
const TIME = /^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?$/;

// Returns the milliseconds of a time of day "12:34", "12:34:56" or
// "12:34:56.789", or null.
function parseTime(text) {
  const m = TIME.exec(text);
  if (!m) return null;
  const [h, min, s] = [m[1], m[2], m[3] ?? "0"].map(Number);
  if (h > 23 || min > 59 || s > 59) return null;
  const fraction = m[4] ? Number(`0.${m[4]}`) * 1000 : 0;
  return ((h * 60 + min) * 60 + s) * 1000 + fraction;
}

// Returns the milliseconds a text of a date kind stands for, or null: a
// datetime takes a date and an optional time ("2026-10-31 12:34:56.789"),
// a date a date, a time a time of day.
export function parseTemporal(kind, text) {
  const value = text.trim();
  if (kind === "time") return parseTime(value);
  const [dayText, timeText] = value.split(/[ T]+/);
  const m = DAY.exec(dayText ?? "");
  if (!m) return null;
  const [y, mo, d] = m.slice(1).map(Number);
  const day = Date.UTC(y, mo - 1, d);
  const check = new Date(day);
  if (check.getUTCMonth() !== mo - 1 || check.getUTCDate() !== d) return null;
  if (timeText === undefined) return day;
  if (kind === "date") return null;
  const time = parseTime(timeText);
  return time === null ? null : day + time;
}

// Returns the range of a plotly axis in its linear units: a date axis
// holds its range as dates, which are milliseconds there.
export function linearRange(axis, range = axis.range) {
  return range.map((v) => axis.r2l(v));
}

const MS_PER_MINUTE = 60_000;
// How many doubles next to `ms`'s seconds `secondsOf` tries.
const ROUND_TRIP_STEPS = 4;

// Returns the double `step` doubles above (below, negative) the double x >= 0.
function nextDouble(x, step) {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  view.setBigUint64(0, view.getBigUint64(0) + BigInt(step));
  return view.getFloat64(0);
}

// Returns the seconds after `minute` that plotly reads `ms` back from: it
// reads date text as the minute's milliseconds + the seconds * 1000
// (`dateTime2ms`), which may round to a double next to `ms`.
function secondsOf(ms, minute) {
  const seconds = (ms - minute) / 1000;
  for (let i = 0; i <= ROUND_TRIP_STEPS; i++) {
    for (const s of i ? [nextDouble(seconds, i), seconds > 0 ? nextDouble(seconds, -i) : seconds] : [seconds]) {
      if (s < 60 && minute + s * 1000 === ms) return s;
    }
  }
  return seconds;
}

// Returns milliseconds on a date axis as the date text plotly takes them as:
// "2026-10-31 12:34:56.789", in UTC. plotly reads a number on a date axis (a
// range, a box) at the browser's local time, but date text and the axis's
// `r2l` at UTC; the server's milliseconds are UTC (wall-clock time). plotly
// reads the text back as the same double (`secondsOf`): a range under a
// second spans few doubles, and one off is another range to the page.
export function dateText(ms) {
  let minute = Math.floor(ms / MS_PER_MINUTE) * MS_PER_MINUTE;
  // The division may round up to the next minute.
  if (minute > ms) minute -= MS_PER_MINUTE;
  const date = new Date(minute);
  const year = date.getUTCFullYear();
  const y = year < 0 ? `-${pad(-year, 4)}` : pad(year, 4);
  const day = `${y}-${pad(date.getUTCMonth() + 1, 2)}-${pad(date.getUTCDate(), 2)}`;
  // The shortest decimals that read as the same double; under 1e-6, where
  // `String` writes an exponent, all its decimals (at most 100 for one over
  // 1e-15) without trailing zeros.
  const seconds = secondsOf(ms, minute);
  const text = seconds === 0 || seconds >= 1e-6 ? String(seconds) : seconds.toFixed(100).replace(/\.?0+$/, "");
  const time = `${pad(date.getUTCHours(), 2)}:${pad(date.getUTCMinutes(), 2)}:${seconds < 10 ? "0" : ""}${text}`;
  return `${day} ${time}`;
}

// Returns a range in linear units (milliseconds on a date axis) as plotly
// takes it on the layout axis `axis`: date text (`dateText`) on a date axis.
export function plotlyRange(axis, range) {
  return axis?.type === "date" ? range.map(dateText) : range;
}

// Returns a plotly layout whose axis ranges and selection boxes, in linear
// units, are as plotly takes them (`plotlyRange`).
export function forPlotly(layout) {
  const out = { ...layout };
  for (const [key, value] of Object.entries(layout)) {
    if (/^[xy]axis\d*$/.test(key) && value.range) out[key] = { ...value, range: plotlyRange(value, value.range) };
  }
  if (layout.selections) {
    out.selections = layout.selections.map((box) => {
      const [x0, x1] = plotlyRange(layout[box.xref.replace(/^x/, "xaxis")], [box.x0, box.x1]);
      const [y0, y1] = plotlyRange(layout[box.yref.replace(/^y/, "yaxis")], [box.y0, box.y1]);
      return { ...box, x0, x1, y0, y1 };
    });
  }
  return out;
}

// The values of a temporal axis in the axis dialog (`axisdialog.js`), as
// text and back. Unlike the filters' text, a date may hold a time of day
// (an end of a zoom within a day), and a time is the signed time since
// midnight, past a day too ("-00:01:00", "24:01:00"): the axis is panned
// there. A duration is seconds.

const US_PER_MS = 1000;
const US_PER_SECOND = 1_000_000;
const AXIS_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
const AXIS_CLOCK = /^(\d+):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?$/;
// A time zone after a time: "Z", "+09:00", "-0500".
const AXIS_ZONE = /(?:Z|[+-]\d{1,2}(?::?\d{2})?)$/i;

// Returns the fraction of a second of `us` microseconds (0 <= us < 1e6) as
// ".123456" without trailing zeros, or "" for none.
function fractionText(us) {
  return us ? `.${pad(us, 6)}`.replace(/0+$/, "") : "";
}

// Returns a value of an axis of `kind` (milliseconds of a date kind,
// seconds of a duration) as the dialog writes it: a datetime as
// "2026-10-31 12:34:56.123456", a date as "2026-10-31" at midnight (else as
// a datetime), a time as "-00:01:00" or "24:01:00.5"; to the microsecond,
// without trailing zeros.
export function axisText(kind, value) {
  if (!isDateKind(kind)) return String(value);
  const us = Math.round(value * US_PER_MS);
  if (kind === "time") {
    const a = Math.abs(us);
    const s = Math.floor(a / US_PER_SECOND);
    const clock = `${pad(Math.floor(s / 3600), 2)}:${pad(Math.floor(s / 60) % 60, 2)}:${pad(s % 60, 2)}`;
    return `${us < 0 ? "-" : ""}${clock}${fractionText(a - s * US_PER_SECOND)}`;
  }
  const seconds = Math.floor(us / US_PER_SECOND);
  const date = new Date(seconds * 1000);
  const day = `${pad(date.getUTCFullYear(), 4)}-${pad(date.getUTCMonth() + 1, 2)}-${pad(date.getUTCDate(), 2)}`;
  if (kind === "date" && us % US_PER_DAY === 0) return day;
  const clock = `${pad(date.getUTCHours(), 2)}:${pad(date.getUTCMinutes(), 2)}:${pad(date.getUTCSeconds(), 2)}`;
  return `${day} ${clock}${fractionText(us - seconds * US_PER_SECOND)}`;
}

// Returns the milliseconds of a clock "12:34", "12:34:56" or
// "12:34:56.123456789" (hours of any count), or null.
function clockMs(text, maxHours) {
  const m = AXIS_CLOCK.exec(text);
  if (!m) return null;
  const [h, min, s] = [m[1], m[2], m[3] ?? "0"].map(Number);
  if (h > maxHours || min > 59 || s > 59) return null;
  const fraction = m[4] ? Number(`0.${m[4]}`) * 1000 : 0;
  return ((h * 60 + min) * 60 + s) * 1000 + fraction;
}

// The reason a text is no value of a date kind.
const SHAPES = {
  datetime: "2026-10-31 12:34:56 の形で入れてください",
  date: "2026-10-31 か 2026-10-31 12:30 の形で入れてください",
  time: "12:34:56 や -00:01:00 の形で入れてください",
};

// Reads a value of an axis of `kind` typed in the dialog (`axisText`):
// `{value}`, or `{error}` with the reason. A datetime or a date takes a
// date and an optional time of day (0:00 up to 24:00, apart by a space or
// "T"); a time a signed clock of any hours; a duration finite seconds.
// Minutes and seconds go up to 59, a fraction of a second to 9 digits. No
// time zone: the axis is at the column's wall-clock time.
export function readAxisValue(kind, text) {
  const value = text.trim();
  if (!isDateKind(kind)) {
    const seconds = value === "" ? NaN : Number(value);
    return Number.isFinite(seconds) ? { value: seconds } : { error: "秒数を入れてください" };
  }
  if (value === "") return { error: "値を入れてください" };
  if (kind === "time") {
    const m = /^([+-]?)(.*)$/.exec(value);
    const ms = clockMs(m[2], Infinity);
    if (ms !== null) return { value: m[1] === "-" ? -ms : ms };
    if (AXIS_ZONE.test(value) && clockMs(value.replace(AXIS_ZONE, ""), Infinity) !== null) {
      return { error: "タイムゾーンは付けられません" };
    }
    return { error: /^[+-]?\d+:\d{2}/.test(value) ? "時刻が正しくありません" : SHAPES.time };
  }
  const m = /^(\d{4}-\d{2}-\d{2})(?:(?:\s+|T)(.*))?$/.exec(value);
  const d = m && AXIS_DAY.exec(m[1]);
  if (!d) return { error: SHAPES[kind] };
  const [y, mo, dd] = d.slice(1).map(Number);
  const date = new Date(0);
  date.setUTCFullYear(y, mo - 1, dd);
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== mo - 1 || date.getUTCDate() !== dd) {
    return { error: "存在しない日付です" };
  }
  if (m[2] === undefined) return { value: date.getTime() };
  const time = m[2].trim();
  const ms = clockMs(time, 23);
  if (ms !== null) return { value: date.getTime() + ms };
  if (AXIS_ZONE.test(time) && clockMs(time.replace(AXIS_ZONE, ""), 23) !== null) {
    return { error: "タイムゾーンは付けられません" };
  }
  return { error: /^\d+:\d{2}/.test(time) ? "時刻が正しくありません" : SHAPES[kind] };
}
