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
