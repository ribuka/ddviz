// The categorical x and y columns whose bands keep the levels of every row,
// those the local filter leaves without rows as empty bands ("フィルタで除外
// された水準も軸に残す", `ddviz.shared.scatter.ScatterSpec.keep_unfiltered_axis_levels`):
// by column name, so that a column on both X and Y has one setting, as it
// has one set of levels. Picked in the axis menu (`axismenu.js`); kept while
// the page is open, whatever role the column is on or whether it is placed,
// off after a reload.
export class AxisLevels {
  #columns = new Set();

  has(column) {
    return this.#columns.has(column);
  }

  set(column, keep) {
    if (keep) this.#columns.add(column);
    else this.#columns.delete(column);
  }

  clear() {
    this.#columns.clear();
  }

  // The columns kept, sorted: JSON values for the drawing settings of undo
  // and redo (`AxisControls.settings`).
  columns() {
    return [...this.#columns].sort();
  }

  // Returns `keep_unfiltered_axis_levels` of a plot request: the columns kept
  // that the graph `encoding` places on x or y as categorical columns
  // (`numeric`, a Map of the placed columns, false), once each
  // (`ddviz.server.plotoptions.parse_keep_axis_levels`).
  request(encoding, numeric) {
    const placed = [...new Set([...encoding.x, ...encoding.y])];
    return placed.filter((column) => this.has(column) && numeric.get(column) === false);
  }
}
