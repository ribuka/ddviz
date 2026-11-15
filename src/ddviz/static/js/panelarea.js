// The plot area of a panel, in the plot's pixels (from the top left of
// `gd`), and whether a point is in it.
import { axisKey } from "./axiskey.js";

// Returns the plot area of a panel's axes `xa` and `ya` (plotly's full
// layout axes), in the plot's pixels: {left, top, right, bottom}.
export function areaOf(xa, ya) {
  return { left: xa._offset, top: ya._offset, right: xa._offset + xa._length, bottom: ya._offset + ya._length };
}

// Returns the plot area of `panel` (of a result's meta) in `full`
// (`gd._fullLayout`), or null when either axis is not laid out.
export function panelArea(full, panel) {
  const xa = full[axisKey(panel.xaxis)];
  const ya = full[axisKey(panel.yaxis)];
  return xa && ya ? areaOf(xa, ya) : null;
}

// Whether a point (in the same pixels as `area`) is in `area`, edges included.
export function inArea(area, x, y) {
  return area.left <= x && x <= area.right && area.top <= y && y <= area.bottom;
}
