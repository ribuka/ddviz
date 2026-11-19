// The statistics of the panels' rows that the reference lines of the axis
// dialog need (`axisdialog.js`: the mean plus or minus n standard deviations,
// a quantile), and whether a result has them. The server finds them while it
// aggregates a graph (`ref_stats` of `POST /api/plot`,
// `ddviz.compute.refstats`); the page aggregates the graph again only when
// its lines need more than the result was aggregated with: the first lines
// of the standard deviations of a column, a new percentile. Removing a line,
// another n, color or dash draw the lines again from the result's
// statistics.

import { axisKind } from "./axisdialog.js";
import { settingsKey } from "./history.js";

// Returns the columns of the numeric axes of the result `meta` (`axisKind`
// "number": linear, neither temporal nor categorical), each once.
export function numericColumns(meta) {
  const columns = [];
  for (const axis of ["x", "y"]) {
    meta[`${axis}_columns`].forEach((column, index) => {
      if (axisKind(meta, axis, index) === "number" && !columns.includes(column)) columns.push(column);
    });
  }
  return columns;
}

// Returns the statistics the reference lines of `columns` need, by column
// (`settingsOf(column)`: the dialog's settings, or undefined): `{moments,
// quantiles}`, whether a line of the standard deviations is there and the
// percentiles of the lines of a quantile, ascending without repeats. A
// column without such lines is left out; `{}` for none.
export function neededStats(settingsOf, columns) {
  // No prototype: a column "__proto__" is a key.
  const needed = Object.create(null);
  for (const column of columns) {
    const lines = settingsOf(column)?.lines ?? [];
    const moments = lines.some((line) => line.type === "sigma");
    const quantiles = [...new Set(lines.filter((line) => line.type === "quantile").map((line) => line.value))];
    quantiles.sort((a, b) => a - b);
    if (moments || quantiles.length) needed[column] = { moments, quantiles };
  }
  return needed;
}

// Whether the statistics a result was aggregated with (`asked`, its meta's
// `ref_stats_asked`) hold those `needed` (`neededStats`): each column, its
// moments when needed and every percentile.
export function coversStats(asked, needed) {
  return Object.entries(needed).every(([column, { moments, quantiles }]) => {
    if (!asked || !Object.hasOwn(asked, column)) return false;
    const has = asked[column];
    return (!moments || has.moments) && quantiles.every((p) => has.quantiles.includes(p));
  });
}

// Whether the step of undo and redo `target` (the drawing settings of
// `history.js`) is drawn on the result `meta` without a plot: it differs
// from the step shown, `shown`, in the settings of the axis dialog alone
// (`axes.dialog`: ticks, labels, reference lines), and `meta` has the
// statistics the lines of `target` need (`coversStats`). Another n, a line
// removed, a color or a dash then draw at once, as from the dialog.
export function drawsWithoutPlot(meta, shown, target) {
  const others = (settings) => settingsKey({ ...settings, axes: { ...settings.axes, dialog: [] } });
  if (others(shown) !== others(target)) return false;
  const dialog = new Map(target.axes.dialog);
  return coversStats(meta.ref_stats_asked, neededStats((column) => dialog.get(column), numericColumns(meta)));
}
