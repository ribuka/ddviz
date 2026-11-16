// Whether the graph the user built can be drawn, and with which elements:
// the same judgement as the server's (`ddviz.server.plan`). `numeric` maps a
// column name to whether it is numeric (a temporal column is); a column not
// in it counts as numeric, as on the server.

// The roles a scatter plot draws (`ddviz.server.plan.drawn_columns`) and
// its elements.
export function drawnRoles(encoding) {
  const { x, y, color, row, col, wrap, elements, symbol } = encoding;
  return JSON.stringify([x, y, color, row, col, wrap, elements, symbol]);
}

// Whether the graph draws every row in one band along x: no x column and
// numeric y columns only (`ddviz.server.plan.one_band`).
export function oneBand(encoding, numeric) {
  const isNumeric = (name) => numeric.get(name) !== false;
  return !encoding.x.length && encoding.y.length > 0 && encoding.y.every(isNumeric);
}

// Whether the graph has a scatter plot (`ddviz.server.plan.drawable`).
export function drawable(encoding, numeric) {
  return (encoding.x.length > 0 && encoding.y.length > 0) || oneBand(encoding, numeric);
}

// Whether a pair of the graph's axis columns can have box plots: a
// categorical x and a numeric y, or the one band
// (`ddviz.server.plan.has_box_pair`).
export function hasBoxPair(encoding, numeric) {
  const isNumeric = (name) => numeric.get(name) !== false;
  return (
    oneBand(encoding, numeric) || (encoding.x.some((x) => !isNumeric(x)) && encoding.y.some(isNumeric))
  );
}

// Whether a pair of the graph's axis columns can have smoothing lines: a
// numeric x and a numeric y (a temporal column is numeric;
// `ddviz.server.plan.has_smooth_pair`).
export function hasSmoothPair(encoding, numeric) {
  const isNumeric = (name) => numeric.get(name) !== false;
  return encoding.x.some(isNumeric) && encoding.y.some(isNumeric);
}

// Whether a pair of the graph's axis columns can join its points with
// lines: any x column and a numeric y (`ddviz.server.plan.has_line_pair`).
export function hasLinePair(encoding, numeric) {
  const isNumeric = (name) => numeric.get(name) !== false;
  return encoding.x.length > 0 && encoding.y.some(isNumeric);
}
