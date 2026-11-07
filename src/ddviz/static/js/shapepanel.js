// The panel that picks the shape of a symbol level, opened as a submenu of
// the menu of the symbol legend's markers (shapemenu.js): the shapes a level
// can take (`meta.symbol.choices`, in the order of
// `ddviz.shared.shapes.SHAPES`) drawn in the figure's pixels, the outlines in
// the first row and the filled ones in the second, and the shape of the
// level's place again.

// Color of the shapes in the symbol's legend and in the panel.
export const SHAPE_COLOR = "#444";
// Shapes to a row: the 7 outlines, then the 5 filled ones under them.
const COLUMNS = 7;

// Draws a marker shape (a kernel of `meta.symbol`, rows from the top) a
// pixel per cell.
export function shapeCanvas(kernel) {
  const canvas = document.createElement("canvas");
  canvas.width = kernel.length;
  canvas.height = kernel.length;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = SHAPE_COLOR;
  kernel.forEach((row, y) => {
    row.forEach((on, x) => {
      if (on) ctx.fillRect(x, y, 1, 1);
    });
  });
  return canvas;
}

// Returns the panel. `current` is the level's shape (a name of
// `ddviz.shared.shapes.SHAPES`), `choices` the shapes ({name, kernel});
// `onPick` gets the shape picked, or null for the shape of the level's place
// again.
export function shapePanel(current, choices, onPick) {
  const panel = document.createElement("div");
  panel.className = "scale-menu shape-panel";
  const grid = document.createElement("div");
  grid.className = "shape-grid";
  grid.style.gridTemplateColumns = `repeat(${COLUMNS}, auto)`;
  for (const { name, kernel } of choices) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "shape-cell";
    cell.classList.toggle("current", name === current);
    cell.dataset.shape = name;
    cell.title = name;
    cell.append(shapeCanvas(kernel));
    cell.addEventListener("click", () => onPick(name));
    grid.append(cell);
  }
  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "scale-menu-item";
  reset.textContent = "既定の形に戻す";
  reset.addEventListener("click", () => onPick(null));
  panel.append(grid, reset);
  return panel;
}
