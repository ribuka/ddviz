// Row-level hover over the image layers: the server looks up the row of the
// pixel under the cursor, and this module draws a plotly-like label.
import { seriesOrder } from "./legend.js";

const HOVER_DISTANCE = 20;

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

function formatValue(value) {
  if (typeof value === "number" && !Number.isInteger(value)) {
    return value.toPrecision(6);
  }
  return String(value);
}

// Returns where the cursor is: its panel, its position in bins, and the
// screen pixels per bin, or null away from every panel.
function locate(gd, meta, event) {
  const rect = gd.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  const full = gd._fullLayout;
  const dxBin = (meta.x_range[1] - meta.x_range[0]) / meta.grid.width;
  const dyBin = (meta.y_range[1] - meta.y_range[0]) / meta.grid.height;
  for (let panel = 0; panel < meta.panels.length; panel++) {
    const xa = full[axisKey(meta.panels[panel].xaxis)];
    const ya = full[axisKey(meta.panels[panel].yaxis)];
    const lx = px - xa._offset;
    const ly = py - ya._offset;
    if (lx < -HOVER_DISTANCE || lx > xa._length + HOVER_DISTANCE) continue;
    if (ly < -HOVER_DISTANCE || ly > ya._length + HOVER_DISTANCE) continue;
    const x = xa.p2l(lx);
    const y = ya.p2l(ly);
    return {
      panel,
      xa,
      ya,
      fx: (x - meta.x_range[0]) / dxBin,
      fy: (y - meta.y_range[0]) / dyBin,
      sx: xa._length / ((xa.range[1] - xa.range[0]) / dxBin),
      sy: ya._length / ((ya.range[1] - ya.range[0]) / dyBin),
      dxBin,
      dyBin,
    };
  }
  return null;
}

// Attaches the hover to the plot element once; `getMeta` returns the meta of
// the result whose images are drawn (the overview or a zoomed view). Only one
// lookup is in flight; moves during it collapse into the latest one.
export function attachHover(gd, getMeta, onTiming) {
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
    const order = seriesOrder(gd, meta.series.length);
    const query = new URLSearchParams({
      task: meta.task,
      panel: at.panel,
      fx: at.fx,
      fy: at.fy,
      sx: at.sx,
      sy: at.sy,
      order: order.join(","),
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
    const cx = at.xa._offset + at.xa.l2p(meta.x_range[0] + (hit.bx + 0.5) * at.dxBin);
    const cy = at.ya._offset + at.ya.l2p(meta.y_range[0] + (hit.by + 0.5) * at.dyBin);
    const lines = Object.entries(hit.values).map(([k, v]) => `${k}: ${formatValue(v)}`);
    lines.push(`行番号: ${hit.row}`);
    lines.push(`このピクセル: ${hit.pixel_count} 行（${meta.series[hit.series]}: ${hit.count} 行）`);
    label.textContent = lines.join("\n");
    label.style.background = meta.colors[hit.series];
    label.hidden = false;
    ring.hidden = false;
    ring.style.left = `${cx}px`;
    ring.style.top = `${cy}px`;
    const width = label.offsetWidth;
    const flip = cx + 12 + width > gd.clientWidth;
    label.style.left = `${flip ? cx - 12 - width : cx + 12}px`;
    label.style.top = `${cy - label.offsetHeight / 2}px`;
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
