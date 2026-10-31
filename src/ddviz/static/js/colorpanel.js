// The panel that picks the color of a color level, opened as a submenu of the
// menu of the legend's markers (shapemenu.js): swatches in a grid whose
// columns are hues and whose rows are lightnesses (the hues, then lighter
// and darker ones, then grays from white to black), a native picker for any
// other color, and the palette's color again.

// The hues of the first row: the palette's colors (`ddviz.shared.palette.DEFAULT_COLORS`).
const HUES = [
  "#1f77b4",
  "#ff7f0e",
  "#2ca02c",
  "#d62728",
  "#9467bd",
  "#8c564b",
  "#e377c2",
  "#7f7f7f",
  "#bcbd22",
  "#17becf",
];
// Rows under the hues: a share of white (> 0) or of black (< 0) mixed in.
const SHADES = [0.75, 0.5, 0.25, -0.25, -0.5];

function rgb(hex) {
  return [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));
}

function hex(values) {
  return `#${values.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
}

// Mixes a color with white (`share` > 0) or black (`share` < 0).
function shade(color, share) {
  const to = share > 0 ? 255 : 0;
  const t = Math.abs(share);
  return hex(rgb(color).map((v) => v + (to - v) * t));
}

// The rows of swatches, as colors `#rrggbb`.
export const SWATCHES = [
  HUES,
  ...SHADES.map((share) => HUES.map((color) => shade(color, share))),
  HUES.map((_, i) => hex([255, 255, 255].map((v) => v * (1 - i / (HUES.length - 1))))),
];

// Returns the panel. `current` is the level's color (`#rrggbb`); `onPick`
// gets the color picked, or null for the palette's color again.
export function colorPanel(current, onPick) {
  const panel = document.createElement("div");
  panel.className = "scale-menu color-panel";
  const grid = document.createElement("div");
  grid.className = "color-grid";
  grid.style.gridTemplateColumns = `repeat(${HUES.length}, auto)`;
  for (const color of SWATCHES.flat()) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "color-cell";
    cell.classList.toggle("current", color === current.toLowerCase());
    cell.style.background = color;
    cell.title = color;
    cell.addEventListener("click", () => onPick(color));
    grid.append(cell);
  }
  const input = document.createElement("input");
  input.type = "color";
  input.className = "color-input";
  input.value = current;
  input.addEventListener("change", () => onPick(input.value));
  const other = document.createElement("button");
  other.type = "button";
  other.className = "scale-menu-item";
  other.textContent = "その他の色…";
  other.addEventListener("click", () => input.click());
  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "scale-menu-item";
  reset.textContent = "既定の色に戻す";
  reset.addEventListener("click", () => onPick(null));
  panel.append(grid, other, input, reset);
  return panel;
}
