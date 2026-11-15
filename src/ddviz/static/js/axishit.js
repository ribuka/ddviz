// Which axis column is under the pointer on the plot, for the axes'
// right-click menu and double click.
import { inArea, panelArea } from "./panelarea.js";

// plotly's drag areas of the axes (`ewdrag` along x, `nsdrag` along y, and
// their ends), each in the group of its subplot (`x2y2`).
const AXIS_DRAGS = { ewdrag: "x", wdrag: "x", edrag: "x", nsdrag: "y", sdrag: "y", ndrag: "y" };

// Returns the axis column (of any kind) under a pointer event on `gd`, the plot
// of the result `meta`, as `{axis: "x" | "y", index}` (of `x_columns` or
// `y_columns`), or null. Only the drag areas of the tick labels count,
// outside every panel: an axis's area reaches over the edge of a
// neighboring panel, whose double click resets the view.
export function axisAt(event, gd, meta) {
  const drag = event.target.closest?.(".draglayer rect.drag");
  if (!drag || !meta) return null;
  const axis = [...drag.classList].map((name) => AXIS_DRAGS[name]).find(Boolean);
  const subplot = drag.parentElement?.getAttribute("class")?.match(/^(x\d*)(y\d*)$/);
  if (!axis || !subplot) return null;
  const full = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  for (const panel of meta.panels) {
    const area = panelArea(full, panel);
    if (area && inArea(area, px, py)) return null;
  }
  const id = axis === "x" ? subplot[1] : subplot[2];
  const panel = meta.panels.find((p) => (axis === "x" ? p.xaxis : p.yaxis) === id);
  if (!panel) return null;
  const index = axis === "x" ? panel.x : panel.y;
  return { axis, index };
}

// Returns the y axis column whose left margin holds a point (client
// coordinates) of the plot `gd` of the result `meta`, as `{axis: "y", index}`,
// or null: right of `from` (the right edge of the y zone, which keeps its
// chips and drops) and left of the plot area of the leftmost panel at the
// point's height, from that panel's top to its bottom. The whole margin is
// its axis's, not only plotly's drag area along the tick labels: gaps
// between the labels, above them and left of them count. The margins
// between panel rows, above the top row and below the bottom row are no
// axis's. Laid out as drawn: null before the plot is drawn.
export function yMarginAt(clientX, clientY, gd, meta, from) {
  const full = gd._fullLayout;
  if (!meta || !full || clientX <= from) return null;
  const origin = gd.getBoundingClientRect();
  let left = Infinity;
  let index = null;
  for (const panel of meta.panels) {
    const area = panelArea(full, panel);
    if (!area) continue;
    if (clientY < origin.top + area.top || clientY > origin.top + area.bottom) continue;
    if (origin.left + area.left < left) {
      left = origin.left + area.left;
      index = panel.y;
    }
  }
  return index !== null && clientX < left ? { axis: "y", index } : null;
}

// Returns the axis column whose tick label drawn by plotly holds a point
// (client coordinates) of the plot `gd` of the result `meta`, as `{axis,
// index}`, or null. A label turned to an angle reaches out of plotly's drag
// area of its axis: an x label below it, a y label above or below its
// panel's margin (`yMarginAt`); a point in a panel's plot area is the
// panel's.
export function labelAt(clientX, clientY, gd, meta) {
  const full = gd._fullLayout;
  if (!meta || !full) return null;
  const origin = gd.getBoundingClientRect();
  let hit = null;
  for (const panel of meta.panels) {
    const area = panelArea(full, panel);
    if (!area) continue;
    const onPage = {
      left: origin.left + area.left,
      top: origin.top + area.top,
      right: origin.left + area.right,
      bottom: origin.top + area.bottom,
    };
    if (inArea(onPage, clientX, clientY)) return null;
    for (const [axis, id, index] of [
      ["x", panel.xaxis, panel.x],
      ["y", panel.yaxis, panel.y],
    ]) {
      if (hit) break;
      for (const text of gd.querySelectorAll(`.${id}tick text`)) {
        if (inArea(text.getBoundingClientRect(), clientX, clientY)) {
          hit = { axis, index };
          break;
        }
      }
    }
  }
  return hit;
}
