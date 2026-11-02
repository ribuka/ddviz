// Row-level hover over the image layers: the server looks up the row of the
// pixel under the cursor, and this module draws a plotly-like label.
import { boxAt } from "./boxes.js";
import { seriesColors, valueColor } from "./colorscale.js";
import { formatTemporal, linearRange } from "./temporal.js";

const HOVER_DISTANCE = 20;

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

// Returns a hover value as text: a datetime, date or time column's
// (`kind`) as such (`temporal.js`), a number to 6 digits.
function formatValue(value, kind = null) {
  const temporal = formatTemporal(kind, value);
  if (temporal !== null) return temporal;
  if (typeof value === "number" && !Number.isInteger(value)) {
    return value.toPrecision(6);
  }
  return String(value);
}

// Returns the name of a series in the hover label: its color level and its
// overlay level, those that have names. A gradient's single color has none.
function seriesName(meta, s) {
  const shapes = meta.color.shapes;
  const names = [];
  // Without a color column the one series has no name (the server sends "None").
  if (meta.color.column !== null && meta.color.kind !== "gradient") {
    names.push(meta.series[Math.floor(s / shapes)]);
  }
  if (meta.overlay) names.push(meta.overlay.levels[s % shapes]);
  return names.join(", ");
}

// Puts the label right of the cursor, or left of it where the right has no
// room, and keeps it inside the plot (a label wider than the room left of
// the cursor, of long names, would start left of the plot).
function placeLabel(label, gd, cx, cy) {
  const width = label.offsetWidth;
  const flip = cx + 12 + width > gd.clientWidth;
  const left = flip ? cx - 12 - width : cx + 12;
  label.style.left = `${Math.max(0, left)}px`;
  label.style.top = `${Math.max(0, cy - label.offsetHeight / 2)}px`;
}

// Returns where the cursor is: its panel, its position in bins, and the
// screen pixels per bin, or null away from every panel.
function locate(gd, meta, event) {
  const rect = gd.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  const full = gd._fullLayout;
  for (let panel = 0; panel < meta.panels.length; panel++) {
    const { xaxis, yaxis, x: xi, y: yj } = meta.panels[panel];
    const xa = full[axisKey(xaxis)];
    const ya = full[axisKey(yaxis)];
    const lx = px - xa._offset;
    const ly = py - ya._offset;
    if (lx < -HOVER_DISTANCE || lx > xa._length + HOVER_DISTANCE) continue;
    if (ly < -HOVER_DISTANCE || ly > ya._length + HOVER_DISTANCE) continue;
    const x = xa.p2l(lx);
    const y = ya.p2l(ly);
    const [xr0, xr1] = linearRange(xa);
    const [yr0, yr1] = linearRange(ya);
    const x0 = meta.x_ranges[xi][0];
    const y0 = meta.y_ranges[yj][0];
    const dxBin = (meta.x_ranges[xi][1] - x0) / meta.grid.width;
    const dyBin = (meta.y_ranges[yj][1] - y0) / meta.grid.height;
    return {
      panel,
      xa,
      ya,
      x0,
      y0,
      fx: (x - x0) / dxBin,
      fy: (y - y0) / dyBin,
      sx: xa._length / ((xr1 - xr0) / dxBin),
      sy: ya._length / ((yr1 - yr0) / dyBin),
      dxBin,
      dyBin,
    };
  }
  return null;
}

// Attaches the hover to the plot element once; `getMeta` returns the meta of
// the result whose images are drawn (the overview or a zoomed view). Only one
// lookup is in flight; moves during it collapse into the latest one.
export function attachHover(gd, getMeta, legend, onTiming) {
  const label = document.getElementById("hover-label");
  const ring = document.getElementById("hover-ring");
  let queued = null;
  let busy = false;

  function hide() {
    label.hidden = true;
    ring.hidden = true;
  }

  async function show(event) {
    const meta = getMeta();
    if (!meta) return;
    const at = locate(gd, meta, event);
    if (!at) {
      hide();
      return;
    }
    // The series drawn invisible (inactive at opacity 0) are not found.
    const hidden = legend.hidden();
    const box = boxAt(meta, at.panel, at.x0 + at.fx * at.dxBin, at.y0 + at.fy * at.dyBin, hidden);
    if (box) {
      showBox(meta, at.panel, box, event);
      return;
    }
    const order = legend.order(meta.grid.n_series);
    const query = new URLSearchParams({
      task: meta.task,
      panel: at.panel,
      fx: at.fx,
      fy: at.fy,
      sx: at.sx,
      sy: at.sy,
      order: order.join(","),
      hidden: [...hidden].join(","),
    });
    const started = performance.now();
    const response = await fetch(`/api/hover?${query}`);
    const body = await response.json();
    onTiming?.(performance.now() - started);
    const hit = body.hit;
    if (!hit || meta !== getMeta()) {
      hide();
      return;
    }
    const cx = at.xa._offset + at.xa.l2p(at.x0 + (hit.bx + 0.5) * at.dxBin);
    const cy = at.ya._offset + at.ya.l2p(at.y0 + (hit.by + 0.5) * at.dyBin);
    // Of the axis columns, the panel's own x and y show: the row may lack the others.
    const panel = meta.panels[at.panel];
    const own = new Set([meta.x_columns[panel.x], meta.y_columns[panel.y]]);
    const others = new Set([...meta.x_columns, ...meta.y_columns].filter((c) => !own.has(c)));
    const lines = Object.entries(hit.values)
      .filter(([k]) => !others.has(k))
      .map(([k, v]) => `${k}: ${formatValue(v, meta.temporal[k])}`);
    lines.push(`行番号: ${hit.row}`);
    const series = seriesName(meta, hit.series);
    const ofSeries = series === "" ? "" : `（${series}: ${hit.count} 行）`;
    lines.push(`このピクセル: ${hit.pixel_count} 行${ofSeries}`);
    label.textContent = lines.join("\n");
    const column = meta.color.column;
    label.style.background =
      meta.color.kind === "gradient" && typeof hit.values[column] === "number"
        ? valueColor(meta, hit.values[column])
        : seriesColors(meta)[hit.series];
    label.hidden = false;
    ring.hidden = false;
    ring.style.left = `${cx}px`;
    ring.style.top = `${cy}px`;
    placeLabel(label, gd, cx, cy);
  }

  // Shows the numbers of a box plot beside the cursor: no lookup, the meta
  // holds them.
  function showBox(meta, p, box, event) {
    const [level, series, n, low, q1, median, q3, high] = box;
    const x = meta.x_columns[meta.panels[p].x];
    const kind = meta.temporal[meta.y_columns[meta.panels[p].y]];
    // The one band is no column of the data.
    const lines = meta.one_band ? [] : [`${x}: ${meta.axis_levels[x][level]}`];
    const shapes = meta.color.shapes;
    if (meta.color.column !== null && meta.color.kind !== "gradient") {
      lines.push(`${meta.color.column}: ${meta.series[Math.floor(series / shapes)]}`);
    }
    if (meta.overlay) lines.push(`${meta.overlay.column}: ${meta.overlay.levels[series % shapes]}`);
    lines.push(
      `ひげの上端: ${formatValue(high, kind)}`,
      `75%: ${formatValue(q3, kind)}`,
      `50%: ${formatValue(median, kind)}`,
      `25%: ${formatValue(q1, kind)}`,
      `ひげの下端: ${formatValue(low, kind)}`,
      `行数: ${n.toLocaleString()}`,
    );
    label.textContent = lines.join("\n");
    label.style.background = meta.color.kind === "gradient" ? "#444" : seriesColors(meta)[series];
    label.hidden = false;
    ring.hidden = true;
    const rect = gd.getBoundingClientRect();
    const cx = event.clientX - rect.left;
    const cy = event.clientY - rect.top;
    placeLabel(label, gd, cx, cy);
  }

  async function pump() {
    busy = true;
    while (queued) {
      const event = queued;
      queued = null;
      try {
        await show(event);
      } catch (error) {
        console.error(error);
      }
    }
    busy = false;
  }

  gd.addEventListener("mousemove", (event) => {
    if (event.buttons) {
      hide();
      return;
    }
    queued = event;
    if (!busy) pump();
  });
  gd.addEventListener("mouseleave", () => {
    queued = null;
    hide();
  });
  return hide;
}
