// "Copy graph image" of the plot's menu (plotmenu.js): every panel of the
// drawn figure, scrolled out of sight or not, with its axis names, ticks,
// facet labels and the legend, as one PNG on a white background copied to
// the clipboard (`docs/spec.md`, "グラフ画像のコピー").
//
// - The state is taken at the click (`captureScene`): plotly's figure, the
//   series layers (painted at once on the output's canvas, from the images
//   drawn), the box selection's outline and the legend's entries. A result
//   that comes meanwhile changes nothing of the image, and the page's
//   figure, scroll and legend are left as they are.
// - plotly draws the axes again in a container of its own off the page
//   (`Plotly.toImage`), with the tick labels and facet labels that a grid
//   that scrolls keeps in the page's strips (sticky.js) at the edges of the
//   whole grid. The layers lie between its two SVG layers, as on screen.
// - The logical size is in CSS px, 96 to the inch; the PNG has
//   `ceil(W * dpi / 96)` × `ceil(H * dpi / 96)` pixels whatever the device
//   pixel ratio, and a pHYs of `dpi` (pngdpi.js). The points are the images
//   aggregated for the screen, scaled: no aggregation for the DPI.
// - The clipboard gets a ClipboardItem whose PNG is a promise made at the
//   click, so that the click's user activation is not spent before the
//   image is made. An image too large fails before any canvas is made.
import { axisKey } from "./axiskey.js";
import { plotlyText } from "./bandticks.js";
import { paintLayers } from "./layers.js";
import { drawLegend, fitText, legendLayout } from "./legendimage.js";
import { withDpi } from "./pngdpi.js";

// Most pixels of a side and of the whole PNG. Past them, a canvas may fail
// to be made or take gigabytes; the copy fails before it allocates.
export const MAX_SIDE = 32767;
export const MAX_AREA = 64_000_000;
// CSS px of an inch.
export const CSS_DPI = 96;
// Room in CSS px around the image, of a band of axis names and between the
// figure and the legend.
export const PAD = 16;
export const NAME_BAND = 22;
export const LEGEND_GAP = 16;
const NAME_SIZE = 13;
const WHITE = "#fff";
// The tick label color of a grid that scrolls (`ddviz.server.figure.HIDDEN_LABELS`).
const HIDDEN = "rgba(0,0,0,0)";

// A failure whose message the toast shows as the reason.
export class CopyError extends Error {}

// Returns the PNG's size in pixels for a logical size (CSS px) at `dpi`.
export function outputSize(width, height, dpi) {
  return { width: Math.ceil((width * dpi) / CSS_DPI), height: Math.ceil((height * dpi) / CSS_DPI) };
}

// Returns why a PNG of `size` at `dpi` is too large to make, or null.
export function sizeError({ width, height }, dpi) {
  if (width <= MAX_SIDE && height <= MAX_SIDE && width * height <= MAX_AREA) return null;
  const advice =
    dpi === CSS_DPI
      ? "パネル数を減らしてください"
      : "config/settings.toml の plot.image_copy.dpi を 96 に変更して再起動するか、パネル数を減らしてください";
  return (
    `画像が大きすぎます（${width} × ${height} px、${dpi} DPI。上限は辺 ${MAX_SIDE} px、` +
    `面積 ${MAX_AREA.toLocaleString("en-US")} px）。${advice}`
  );
}

// Takes what the image shows, now: `gd` (plotly's plot), `meta` (the drawn
// result's), `layers` (the series layers, layers.js) and `legend`
// (legend.js). Returns the scene: the figure for plotly, the selection's
// outline, the axis names and Wrap's name, the legend's entries and
// `paint(ctx, base)`, which paints the layers; call it before anything
// the page draws next can close their images.
export function captureScene({ gd, meta, layers, legend }) {
  const full = gd._fullLayout;
  const selection = gd.querySelector(".selectionlayer");
  return {
    width: full.width,
    height: full.height,
    figure: outputFigure(gd, meta),
    selection: selection ? new XMLSerializer().serializeToString(selection) : null,
    names: axisNames(full, meta),
    wrap: meta.wrap_column,
    font: { family: full.font.family, color: full.font.color },
    entries: legend.entries(),
    paint: (ctx, base) => paintLayers(ctx, full, base, layers),
  };
}

// Returns plotly's figure of the image: the page's, on white, with the
// tick labels a grid that scrolls hides and its facet labels (sticky.js),
// without the selection (`selection` of the scene, drawn above the layers).
function outputFigure(gd, meta) {
  const layout = JSON.parse(JSON.stringify(gd.layout));
  const data = JSON.parse(JSON.stringify(gd.data));
  layout.paper_bgcolor = WHITE;
  delete layout.selections;
  for (const [key, axis] of Object.entries(layout)) {
    if (/^[xy]axis\d*$/.test(key) && axis?.tickfont?.color === HIDDEN) delete axis.tickfont.color;
  }
  if (meta.scroll) {
    const labels = meta.facet_labels.map((label) => ({
      ...label,
      text: plotlyText(label.text),
      ...(label.hovertext === undefined ? {} : { hovertext: plotlyText(label.hovertext) }),
    }));
    layout.annotations = [...(layout.annotations ?? []), ...labels];
  }
  return { data, layout };
}

// Returns the axis names: an x column's under the panel columns it spans,
// a y column's left of the panel rows, each `{role, text, from, to}` (the
// span in the figure's px along the axis).
export function axisNames(full, meta) {
  const names = [];
  const count = meta.panels.length;
  const spans = { x: [], y: [] };
  meta.panels.forEach((panel, p) => {
    if (p + meta.ncol >= count && !meta.one_band) {
      const xa = full[axisKey(panel.xaxis)];
      if (xa) spans.x.push({ index: panel.x, from: xa._offset, to: xa._offset + xa._length });
    }
    if (p % meta.ncol === 0) {
      const ya = full[axisKey(panel.yaxis)];
      if (ya) spans.y.push({ index: panel.y, from: ya._offset, to: ya._offset + ya._length });
    }
  });
  for (const role of ["x", "y"]) {
    const columns = role === "x" ? meta.x_columns : meta.y_columns;
    const runs = [];
    for (const span of spans[role].sort((a, b) => a.from - b.from)) {
      const last = runs.at(-1);
      if (last && last.index === span.index) last.to = span.to;
      else runs.push({ ...span });
    }
    for (const run of runs) names.push({ role, text: columns[run.index], from: run.from, to: run.to });
  }
  return names;
}

// Returns the layout of the image in CSS px: its size, the figure's top
// left, the legend's (with its rows, legendimage.js) and the names' places.
// `ctx` measures the text.
export function sceneLayout(scene, ctx) {
  const legend = legendLayout(ctx, scene.entries);
  const top = PAD + (scene.wrap ? NAME_BAND : 0);
  const figure = { x: PAD + NAME_BAND, y: top };
  const right = figure.x + scene.width;
  const legendAt = { x: right + LEGEND_GAP, y: top };
  const width = (legend.width ? legendAt.x + legend.width : right) + PAD;
  const height = Math.max(figure.y + scene.height + NAME_BAND, legendAt.y + legend.height) + PAD;
  return { width, height, figure, legend: { ...legend, ...legendAt } };
}

// Paints what the click took at once on `ctx` (the output's canvas, at
// `scale` output px per CSS px): the layers, the axis names and the legend.
export function paintNow(ctx, scene, layout, scale) {
  const { figure } = layout;
  scene.paint(ctx, new DOMMatrix([scale, 0, 0, scale, figure.x * scale, figure.y * scale]));
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.globalAlpha = 1;
  ctx.font = `${NAME_SIZE}px ${scene.font.family}`;
  ctx.fillStyle = scene.font.color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (const { role, text, from, to } of scene.names) {
    const shown = fitText(ctx, text, Math.max(to - from, 40));
    const middle = (from + to) / 2;
    if (role === "x") {
      ctx.fillText(shown, figure.x + middle, figure.y + scene.height + NAME_BAND / 2);
    } else {
      ctx.save();
      ctx.translate(PAD + NAME_BAND / 2, figure.y + middle);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(shown, 0, 0);
      ctx.restore();
    }
  }
  if (scene.wrap) {
    ctx.fillText(fitText(ctx, scene.wrap, scene.width), figure.x + scene.width / 2, PAD + NAME_BAND / 2);
  }
  drawLegend(ctx, layout.legend, layout.legend.x, layout.legend.y);
}

// Returns the PNG of the image: plotly's axes under and over what
// `paintNow` painted, on white, with a pHYs of `dpi`.
export async function finishImage(canvas, ctx, scene, layout, dpi, toImage) {
  const scale = dpi / CSS_DPI;
  const url = await toImage(scene.figure, { format: "svg", width: scene.width, height: scene.height });
  const [below, above] = splitSvg(svgText(url), scene.selection, scale);
  const at = [layout.figure.x * scale, layout.figure.y * scale, scene.width * scale, scene.height * scale];
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
  ctx.drawImage(await svgImage(above), ...at);
  ctx.globalCompositeOperation = "destination-over";
  ctx.drawImage(await svgImage(below), ...at);
  ctx.fillStyle = WHITE;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.globalCompositeOperation = "source-over";
  const png = await new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new CopyError("PNG にできませんでした"))), "image/png");
  });
  return new Blob([withDpi(new Uint8Array(await png.arrayBuffer()), dpi)], { type: "image/png" });
}

// Returns the SVG of plotly's data URL.
function svgText(url) {
  const comma = url.indexOf(",");
  const head = url.slice(0, comma);
  const body = url.slice(comma + 1);
  return head.endsWith(";base64") ? new TextDecoder().decode(Uint8Array.from(atob(body), (c) => c.charCodeAt(0))) : decodeURIComponent(body);
}

// Splits plotly's SVG of a figure into what lies under the series layers
// (the paper, the panels and their axes) and over them (plotly's top layer:
// the annotations, with the page's selection outline `selection`), each
// sized `scale` times, as text.
export function splitSvg(text, selection, scale) {
  const parse = (t) => new DOMParser().parseFromString(t, "image/svg+xml").documentElement;
  const below = parse(text);
  if (below.nodeName !== "svg") throw new CopyError("軸を描けませんでした");
  const above = below.cloneNode(true);
  const kids = (svg) => [...svg.children];
  const defs = kids(below).flatMap((child, i) => (child.nodeName === "defs" ? [i] : []));
  // plotly's top layer starts at its own defs.
  const split = defs.length > 1 ? defs[1] : kids(below).length;
  kids(below).forEach((child, i) => i >= split && child.remove());
  kids(above).forEach((child, i) => i < split && child.nodeName !== "defs" && child.remove());
  if (selection) {
    const layer = parse(selection);
    for (const control of layer.querySelectorAll(".outline-controllers")) control.remove();
    // Its clip paths are the page's figure's, which plotly's copy names
    // otherwise; the box lies in its panel.
    for (const clipped of layer.querySelectorAll("[clip-path]")) clipped.removeAttribute("clip-path");
    above.append(above.ownerDocument.importNode(layer, true));
  }
  const out = new XMLSerializer();
  return [below, above].map((svg) => {
    const width = Number(svg.getAttribute("width"));
    const height = Number(svg.getAttribute("height"));
    if (!svg.getAttribute("viewBox")) svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", String(width * scale));
    svg.setAttribute("height", String(height * scale));
    return out.serializeToString(svg);
  });
}

// Returns the decoded image of an SVG; its object URL is freed.
async function svgImage(text) {
  const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return image;
  } catch {
    throw new CopyError("軸の画像を読めませんでした");
  } finally {
    URL.revokeObjectURL(url);
  }
}

// The copy of the plot's menu: at most one at a time. `capture()` returns
// what `captureScene` takes; `ready()` whether the figure is settled (no
// aggregation, drawing or selection pending); `dpi()` the setting, or null
// until it comes; `toasts` tells the outcome; `toImage` is plotly's.
export class PlotImageCopy {
  #running = false;

  constructor({ capture, ready, dpi, toasts, toImage = (...args) => window.Plotly.toImage(...args) }) {
    this.capture = capture;
    this.ready = ready;
    this.dpi = dpi;
    this.toasts = toasts;
    this.toImage = toImage;
  }

  // Whether a copy is running.
  get running() {
    return this.#running;
  }

  // Whether the menu's item is enabled.
  available() {
    return !this.#running && this.dpi() !== null && this.ready();
  }

  // Starts a copy, at the click of the menu's item (its user activation
  // writes the clipboard); returns its promise, which never rejects: the
  // outcome is a toast.
  copy() {
    if (!this.available()) return Promise.resolve(false);
    this.#running = true;
    let canvas = null;
    const done = (ok, error) => {
      if (canvas) {
        canvas.width = 0;
        canvas.height = 0;
      }
      this.#running = false;
      if (ok) this.toasts.show("グラフ画像をクリップボードにコピーしました", "success");
      else this.toasts.show(`グラフ画像をコピーできませんでした：${reason(error)}`);
      return ok;
    };
    let image;
    try {
      if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
        throw new CopyError("この環境はクリップボードへの画像の書き込みに対応していません");
      }
      const dpi = this.dpi();
      const scene = captureScene(this.capture());
      const layout = sceneLayout(scene, document.createElement("canvas").getContext("2d"));
      const size = outputSize(layout.width, layout.height, dpi);
      const tooLarge = sizeError(size, dpi);
      if (tooLarge) throw new CopyError(tooLarge);
      canvas = document.createElement("canvas");
      canvas.width = size.width;
      canvas.height = size.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new CopyError("描画用の canvas を作れませんでした");
      paintNow(ctx, scene, layout, dpi / CSS_DPI);
      image = finishImage(canvas, ctx, scene, layout, dpi, this.toImage);
    } catch (error) {
      return Promise.resolve(done(false, error));
    }
    // The image's own failure is the reason, not the clipboard's for it.
    image.catch(() => {});
    let written;
    try {
      written = navigator.clipboard.write([new ClipboardItem({ "image/png": image })]);
    } catch (error) {
      written = Promise.reject(error);
    }
    return Promise.allSettled([image, written]).then(([made, wrote]) => {
      if (made.status === "rejected") return done(false, made.reason);
      if (wrote.status === "rejected") return done(false, wrote.reason);
      return done(true);
    });
  }
}

// Returns the reason of a failure as the toast tells it.
function reason(error) {
  if (error instanceof CopyError) return error.message;
  if (error?.name === "NotAllowedError") return `クリップボードへの書き込みが許可されませんでした（${error.message}）`;
  return error?.message || String(error);
}
