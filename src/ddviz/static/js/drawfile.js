// The file of the drawing settings (docs/spec.md, "描画設定のファイル"):
// the columns the settings refer to, which the file lists with their kinds,
// and the check of opened settings against the columns of the data loaded,
// which takes out those it lacks or holds with another kind. The page
// (`app.js`) saves and applies them; the server builds the file
// (`ddviz.shared.drawfile`).

import { ELEMENTS } from "./elements.js";
import { hasBoxPair, hasLinePair, hasSmoothPair } from "./graph.js";
import { STASHABLE } from "./builder.js";

// Returns the column of an angle's key `<role>:<column>` (`AxisControls`).
function angleColumn(key) {
  return key.slice(key.indexOf(":") + 1);
}

// Returns the names of every column the drawing settings `settings`
// (`captureSettings()` of app.js) refer to, sorted: the zones' (stashed too),
// the filter cards', the axes' (the dialog's, the angles', the log and
// reversed ones and those keeping their levels) and the legend's (the sizes
// and the shapes of the symbol levels).
export function referencedColumns(settings) { // noqa: C901
  const { zones, filters, axes, options } = settings;
  const names = new Set([...zones.encoding.x, ...zones.encoding.y]);
  for (const role of STASHABLE) if (zones.encoding[role] !== null) names.add(zones.encoding[role]);
  for (const card of filters) names.add(card.name);
  for (const [column] of axes.dialog) names.add(column);
  for (const [key] of axes.angles) names.add(angleColumn(key));
  for (const axis of ["x", "y"]) {
    for (const column of axes.logs[axis]) names.add(column);
    for (const column of axes.reversed[axis]) names.add(column);
  }
  for (const column of axes.keepLevels) names.add(column);
  for (const [column] of options.levelSizes) names.add(column);
  if (options.levelShapes) names.add(options.levelShapes.column);
  return [...names].sort();
}

// Returns the elements of the settings as the icons let them be after the
// zones changed (`ElementBar.allow`, as a chip removed by hand does): those
// the axis columns no longer allow are turned off and blocked, those they
// allow again unblocked, and the points turned on when nothing is left.
function allowElements(zones, elements) {
  const numeric = new Map(zones.numeric);
  const allowed = {
    line: hasLinePair(zones.encoding, numeric),
    box: hasBoxPair(zones.encoding, numeric),
    smooth: hasSmoothPair(zones.encoding, numeric),
  };
  const chosen = new Set(elements.chosen);
  const blocked = new Set(elements.blocked);
  let changed = false;
  for (const [name, ok] of Object.entries(allowed)) {
    if (ok) blocked.delete(name);
    else blocked.add(name);
    if (!ok && chosen.delete(name)) changed = true;
  }
  if (changed && !ELEMENTS.some((e) => !blocked.has(e.name) && chosen.has(e.name))) chosen.add("points");
  zones.encoding.elements = ELEMENTS.map((e) => e.name).filter((name) => chosen.has(name));
  return { chosen: [...chosen].sort(), blocked: [...blocked].sort() };
}

// Returns the drawing settings `settings` checked against the data loaded:
// `kinds` gives the kind of each column of `columns` (the file's names and
// kinds) in the data, null for one it lacks. A column the data lacks, or
// holds with another kind, is taken out of every place of the settings that
// refers to it (`referencedColumns`), as removing it by hand would: a chip
// out of its zone (and a stashed role with it), its kinds, its filter card,
// its axis settings and its symbol levels' sizes and shapes; a color column
// taken out drops the color bins, a wrap column the number to a row, and
// the elements follow the axis columns left. Returns `{settings, dropped}`,
// `dropped` the names taken out, sorted.
export function reconcile(settings, columns, kinds) {
  const next = structuredClone(settings);
  const dropped = referencedColumns(settings).filter(
    (name) => columns[name] === undefined || kinds[name] !== columns[name],
  );
  if (!dropped.length) return { settings: next, dropped };
  const gone = new Set(dropped);
  const keep = (name) => !gone.has(name);
  const { zones, axes, options } = next;
  const { encoding } = zones;
  encoding.x = encoding.x.filter(keep);
  encoding.y = encoding.y.filter(keep);
  for (const role of STASHABLE) {
    if (encoding[role] !== null && gone.has(encoding[role])) {
      encoding[role] = null;
      zones.stashed = zones.stashed.filter((r) => r !== role);
    }
  }
  zones.numeric = zones.numeric.filter(([name]) => keep(name));
  zones.temporal = zones.temporal.filter(([name]) => keep(name));
  if (settings.zones.encoding.color !== encoding.color) options.colorBins = null;
  if (settings.zones.encoding.wrap !== encoding.wrap) options.wrapCols = null;
  next.elements = allowElements(zones, next.elements);
  next.filters = next.filters.filter((card) => keep(card.name));
  axes.dialog = axes.dialog.filter(([column]) => keep(column));
  axes.angles = axes.angles.filter(([key]) => keep(angleColumn(key)));
  for (const axis of ["x", "y"]) {
    axes.logs[axis] = axes.logs[axis].filter(keep);
    axes.reversed[axis] = axes.reversed[axis].filter(keep);
  }
  axes.keepLevels = axes.keepLevels.filter(keep);
  options.levelSizes = options.levelSizes.filter(([column]) => keep(column));
  if (options.levelShapes && gone.has(options.levelShapes.column)) options.levelShapes = null;
  return { settings: next, dropped };
}

// Returns the warning of the columns `dropped` taken out (`reconcile`).
export function droppedText(dropped) {
  return `描画設定のうち、データに無い列か種類の違う列を外しました：${dropped.join(", ")}`;
}

// Returns the file name of a `Content-Disposition` header
// (`filename*=UTF-8''<quoted>`, as the server sends it), or `fallback`.
export function attachmentName(header, fallback) {
  const match = /filename\*=UTF-8''([^;]+)/i.exec(header ?? "");
  if (!match) return fallback;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return fallback;
  }
}
