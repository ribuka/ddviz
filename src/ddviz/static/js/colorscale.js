// The color scale of a numeric color column. A gradient's image holds grays
// (1 to 255 over the column's range, 0 where empty) that the page maps to the
// scale's colors; the intervals of a binned column (`meta.color.kind` "bins")
// take colors spread over the scale, tinted onto their masks. A new color set
// or direction only recolors the decoded images: no aggregation runs.
//
// The levels of a categorical color column (`meta.color.kind` "levels") come
// in the palette's colors (`ddviz.shared.palette`); the user may pick another
// color for a level (`picked`), tinted onto its masks the same way.
//
// The missing level (`MISSING`, names.js), last of the color levels of any
// kind, is gray (`MISSING_COLOR`) or the color picked for it; its images are
// masks even for a gradient, and neither the scale nor its direction colors
// them.
import { MISSING, MISSING_COLOR, hasMissing } from "./names.js";

// Color sets as evenly spaced stops, from the low end to the high end.
export const COLOR_SETS = {
  viridis: {
    label: "Viridis",
    stops: ["#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c", "#28ae80", "#5ec962", "#addc30", "#fde725"],
  },
  plasma: {
    label: "Plasma",
    stops: ["#0d0887", "#4c02a1", "#7e03a8", "#a92395", "#cc4778", "#e56b5d", "#f89540", "#fdc527", "#f0f921"],
  },
  bluered: {
    label: "青–白–赤",
    stops: ["#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f7f7f7", "#fddbc7", "#f4a582", "#d6604d", "#b2182b"],
  },
};

// The page's choice of color set and direction, kept across plots.
export const scale = { set: "viridis", reverse: false };

function rgb(hex) {
  return [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));
}

// Returns the color at `t` in [0, 1] of the scale, as [r, g, b].
export function colorAt(t) {
  const stops = COLOR_SETS[scale.set].stops;
  const u = Math.min(Math.max(scale.reverse ? 1 - t : t, 0), 1) * (stops.length - 1);
  const i = Math.min(Math.floor(u), stops.length - 2);
  const a = rgb(stops[i]);
  const b = rgb(stops[i + 1]);
  return a.map((v, k) => Math.round(v + (b[k] - v) * (u - i)));
}

export function cssColor(t) {
  return `rgb(${colorAt(t).join(",")})`;
}

// Returns the colors of `n` intervals, spread over the scale.
export function intervalColors(n) {
  return [...Array(n).keys()].map((i) => cssColor(n === 1 ? 0.5 : i / (n - 1)));
}

// Counts the changes of the colors (scale, direction or picked colors), so
// that images decoded meanwhile in the old colors are decoded again.
let colorsVersion = 0;

export function colorsChanged() {
  colorsVersion++;
}

export function colorsNow() {
  return colorsVersion;
}

// Colors the user picked for the levels of the color column `column`, by
// level name; kept while the graphs color by that column.
const picked = { column: undefined, colors: new Map() };

// Keeps the picked colors for a result colored by `column` (null for a single
// color), or drops them for another column.
export function keepPicked(column) {
  if (picked.column === column) return;
  picked.column = column;
  picked.colors.clear();
}

// Picks the color of a color level (its name), or the palette's again (null).
export function pickColor(level, color) {
  if (color === null) picked.colors.delete(level);
  else picked.colors.set(level, color);
}

// Returns the color picked for color level `i` of a result, or undefined.
// Only the levels of a categorical column and the missing level take one.
function pickedColor(meta, i) {
  if (meta.color.column !== picked.column) return undefined;
  if (meta.color.kind !== "levels" && meta.series[i] !== MISSING) return undefined;
  return picked.colors.get(meta.series[i]);
}

// Returns whether color level `i` of a result is the missing level.
export function isMissingLevel(meta, i) {
  return meta.series[i] === MISSING;
}

// Returns the colors of the color levels of a result (`meta.series`): the
// intervals spread over the scale, the missing level gray or picked. A
// gradient's own level has no color (null).
export function levelColors(meta) {
  const missing = hasMissing(meta.series);
  const missingColor = () => pickedColor(meta, meta.series.length - 1) ?? MISSING_COLOR;
  if (meta.color.kind === "bins") {
    const colors = intervalColors(meta.series.length - (missing ? 1 : 0));
    return missing ? [...colors, missingColor()] : colors;
  }
  if (meta.color.kind === "gradient") return meta.series.map((name) => (name === MISSING ? missingColor() : null));
  return meta.series.map((_, i) => pickedColor(meta, i) ?? meta.colors[i * meta.color.shapes]);
}

// Returns the colors the series of a result are drawn in: series `s` is
// color level `s // shapes` with overlay level `s % shapes`. A gradient's
// series of its own level have none (null).
export function seriesColors(meta) {
  if (meta.color.kind === "levels" && !tinted(meta)) return meta.colors;
  const levels = levelColors(meta);
  return [...Array(meta.grid.n_series).keys()].map((s) => levels[Math.floor(s / meta.color.shapes)]);
}

// Whether the masks of a result are tinted on the page: the intervals of a
// numeric column, or levels with a picked color. Otherwise they come in their
// colors.
function tinted(meta) {
  if (meta.color.kind === "bins") return true;
  return meta.series.some((_, i) => pickedColor(meta, i) !== undefined);
}

// Returns the color of a value of a gradient's column.
export function valueColor(meta, value) {
  const [lo, hi] = meta.color.range;
  return cssColor(hi > lo ? (value - lo) / (hi - lo) : 0.5);
}

// Maps the grays of a gradient's decoded image to the scale's colors.
async function paintGradient(bitmap) {
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0);
  const image = ctx.getImageData(0, 0, bitmap.width, bitmap.height);
  const lut = new Uint8ClampedArray(256 * 3);
  for (let g = 1; g < 256; g++) lut.set(colorAt((g - 1) / 254), g * 3);
  const px = image.data;
  for (let i = 0; i < px.length; i += 4) {
    if (px[i + 3] === 0) continue;
    const g = px[i] * 3;
    px[i] = lut[g];
    px[i + 1] = lut[g + 1];
    px[i + 2] = lut[g + 2];
  }
  ctx.putImageData(image, 0, 0);
  return canvas.transferToImageBitmap();
}

// Fills a series' mask with a color.
function tint(bitmap, color) {
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0);
  ctx.globalCompositeOperation = "source-in";
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, bitmap.width, bitmap.height);
  return canvas.transferToImageBitmap();
}

// Decodes the PNGs of a result or layer, one per series, in the colors of
// result `meta` (colored the same way).
export async function decode(blobs, meta) {
  if (meta.color.kind === "gradient") {
    const colors = seriesColors(meta);
    return Promise.all(
      blobs.map(async (blob, i) => {
        if (!blob) return null;
        if (colors[i] !== null) {
          // The missing level's mask, in its own color.
          const mask = await createImageBitmap(blob);
          const painted = tint(mask, colors[i]);
          mask.close();
          return painted;
        }
        // The grays must reach the canvas as they are.
        const raw = await createImageBitmap(blob, { colorSpaceConversion: "none", premultiplyAlpha: "none" });
        const painted = await paintGradient(raw);
        raw.close();
        return painted;
      }),
    );
  }
  const colors = tinted(meta) ? seriesColors(meta) : null;
  return Promise.all(
    blobs.map(async (blob, i) => {
      if (!blob) return null;
      const mask = await createImageBitmap(blob);
      if (!colors) return mask;
      const painted = tint(mask, colors[i]);
      mask.close();
      return painted;
    }),
  );
}
