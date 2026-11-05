// The direction of the x and y axes: a reversed axis puts the larger values
// on the left (x) or at the bottom (y). The direction is the page's alone:
// the page keeps every range ascending (the views, the boxes, what it sends
// to the server) and gives plotly a reversed axis's range descending
// (`oriented`), which plotly draws reversed. plotly's ranges read back
// ascending (`ascending`), whatever the direction.

// Returns a range ascending (a copy).
export function ascending(range) {
  return range[1] < range[0] ? [range[1], range[0]] : [range[0], range[1]];
}

// Returns a range as plotly takes it on an axis of the direction `reversed`:
// descending on a reversed axis, ascending otherwise (a copy).
export function oriented(range, reversed) {
  const [lo, hi] = ascending(range);
  return reversed ? [hi, lo] : [lo, hi];
}

// The axes reversed while one input is open, by role and column: X and Y of
// the same column are apart, the facets and the n-th axes of a column share
// the direction (as `AxisScales`).
export class AxisDirections {
  constructor() {
    this.reversed = { x: new Set(), y: new Set() };
  }

  isReversed(axis, column) {
    return this.reversed[axis].has(column);
  }

  set(axis, column, reversed) {
    if (reversed) this.reversed[axis].add(column);
    else this.reversed[axis].delete(column);
  }

  clear() {
    this.reversed.x.clear();
    this.reversed.y.clear();
  }

  // Returns the direction of each axis of a result's panels, by plotly axis
  // id ("x2", "y"): whether it is reversed.
  byAxis(meta) {
    const out = {};
    for (const panel of meta.panels) {
      out[panel.xaxis] = this.isReversed("x", meta.x_columns[panel.x]);
      out[panel.yaxis] = this.isReversed("y", meta.y_columns[panel.y]);
    }
    return out;
  }
}
