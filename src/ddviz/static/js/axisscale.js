// Linear and log10 axes of the x and y columns (`ddviz.shared.axisscale`).
// The page works in plotly's linear units: on a log axis, the exponents
// (its range, a box, the bins of `meta.x_ranges`). The server takes the
// values themselves, ascending (`toValues`); box plots and smoothing lines
// come as values and are drawn at their positions (`toPosition`).

// Exponents whose powers of 10 are positive finite doubles
// (`ddviz.shared.axisscale.MIN_EXPONENT`, `MAX_EXPONENT`).
const MIN_EXPONENT = -323;
const MAX_EXPONENT = 308;

// Returns the position of a value on an axis: its log10 on a log axis, NaN
// there unless positive and finite.
export function toPosition(log, value) {
  if (!log) return value;
  return value > 0 && Number.isFinite(value) ? Math.log10(value) : NaN;
}

// Returns the values of a range of positions, ascending: the powers of 10 of
// a log axis's exponents, kept to the positive finite doubles.
export function toValues(log, range) {
  const values = log
    ? range.map((v) => 10 ** Math.min(MAX_EXPONENT, Math.max(MIN_EXPONENT, v)))
    : [...range];
  return values.sort((a, b) => a - b);
}

// Returns whether an axis of a plotly layout is a log axis.
export function isLogAxis(axis) {
  return axis?.type === "log";
}

// The scale picked for each x and each y column while one input is open,
// by role and column: X and Y of the same column are apart, the facets and
// the n-th axes of a column share it.
export class AxisScales {
  constructor() {
    this.logs = { x: new Set(), y: new Set() };
  }

  isLog(axis, column) {
    return this.logs[axis].has(column);
  }

  set(axis, column, log) {
    if (log) this.logs[axis].add(column);
    else this.logs[axis].delete(column);
  }

  clear() {
    this.logs.x.clear();
    this.logs.y.clear();
  }

  // Returns `axis_scales` of a plot request: the log columns placed on x and
  // y (`ddviz.shared.axisscale.parse_axis_scales`); the rest is linear.
  request(encoding) {
    const out = { x: {}, y: {} };
    for (const axis of ["x", "y"]) {
      for (const column of encoding[axis]) if (this.isLog(axis, column)) out[axis][column] = "log";
    }
    return out;
  }
}
