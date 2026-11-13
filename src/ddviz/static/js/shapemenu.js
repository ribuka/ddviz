// The menus of the size of the markers (`ddviz.server.plan.SHAPE_SIZES`):
// of every series, opened by a right click on the points' element icon
// (elements.js), on a color item's marker of the legend (legend.js) or, for
// a gradient, from its scale's menu (scalemenu.js); of one symbol level's
// shapes, opened by a right click on that level's marker in the symbol's
// legend. Picking the size of every series drops the sizes of single levels.
//
// The menu of a color level's marker also picks the level's color, and that
// of a symbol level's marker the level's shape, each in a panel opened as
// a submenu (colorpanel.js, shapepanel.js).
import { colorPanel } from "./colorpanel.js";
import { shapeCanvas, shapePanel } from "./shapepanel.js";

export const SIZES = [3, 5, 7, 9, 11, 15];
export const SIZE_HEADING = "点の大きさ（全系列）";
// Widths of the lines joining the points (`ddviz.server.plan.LINE_WIDTHS`),
// in the menu of the lines' element icon, which this menu also is.
export const LINE_WIDTHS = [1, 2, 3, 4, 5];
export const LINE_HEADING = "線の太さ（全系列）";

// Heading of the menu of a symbol level's shapes.
export function levelHeading(level) {
  return `形「${level}」の大きさ`;
}

let open = null;
// The panel open beside the menu (of the color or the shape), or null.
let sub = null;

function closeSub() {
  sub?.remove();
  sub = null;
}

function close() {
  closeSub();
  open?.remove();
  open = null;
}

window.addEventListener("pointerdown", (event) => {
  if (open && !open.contains(event.target) && !sub?.contains(event.target)) close();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") close();
});

// Opens the menu at a right click, under `heading`. `size` is the current
// size; `onPick` gets the size picked. With `color` ({current, onPick}: the
// level's color and what gets the color picked, or null for the palette's),
// the menu first has the item that opens the color panel; with `shape`
// ({current, choices, onPick}: the level's shape, the shapes it can take as
// `meta.symbol.choices` and what gets the shape picked, or null for the
// shape of the level's place), the item that opens the shape panel.
// `sizes` lists the sizes to pick from: the widths of the lines
// (`LINE_WIDTHS`) in the menu of the lines' icon.
export function openShapeMenu(event, heading, size, onPick, { color = null, shape = null, sizes = SIZES } = {}) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu shape-menu";
  if (color) menu.append(colorItem(color), menuGap());
  if (shape) menu.append(shapeItem(shape), menuGap());
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = heading;
  menu.append(head);
  for (const pick of sizes) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scale-menu-item";
    row.classList.toggle("checked", pick === size);
    row.textContent = `${pick} px`;
    row.addEventListener("pointerenter", closeSub);
    row.addEventListener("click", () => {
      close();
      if (pick !== size) onPick(pick);
    });
    menu.append(row);
  }
  document.body.append(menu);
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(event.clientX, innerWidth - rect.width - 4))}px`;
  menu.style.top = `${Math.max(4, Math.min(event.clientY, innerHeight - rect.height - 4))}px`;
  open = menu;
}

function menuGap() {
  const gap = document.createElement("div");
  gap.className = "scale-menu-separator";
  return gap;
}

// The item that opens the color panel beside it, on hover or on a click.
function colorItem({ current, onPick }) {
  const swatch = document.createElement("span");
  swatch.className = "color-item-swatch";
  swatch.style.background = current;
  return subItem("color-item", swatch, "色", (pick) => colorPanel(current, pick), onPick);
}

// The item that opens the shape panel beside it, on hover or on a click.
function shapeItem({ current, choices, onPick }) {
  const swatch = document.createElement("span");
  swatch.className = "shape-item-swatch";
  const now = choices.find((choice) => choice.name === current);
  if (now) swatch.append(shapeCanvas(now.kernel));
  return subItem("shape-item", swatch, "形", (pick) => shapePanel(current, choices, pick), onPick);
}

// An item that opens a panel (`panel(pick)`, where `pick` closes the menu
// and passes the value picked to `onPick`) beside the menu.
function subItem(className, swatch, label, panel, onPick) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = `scale-menu-item has-sub ${className}`;
  row.append(swatch, label);
  const show = () => {
    if (sub) return;
    sub = panel((picked) => {
      close();
      onPick(picked);
    });
    document.body.append(sub);
    const item = row.getBoundingClientRect();
    const rect = sub.getBoundingClientRect();
    const { innerWidth, innerHeight } = window;
    // Beside the menu on the right, or on the left without room.
    const left = item.right + rect.width + 4 <= innerWidth ? item.right : item.left - rect.width;
    sub.style.left = `${Math.max(4, left)}px`;
    sub.style.top = `${Math.max(4, Math.min(item.top - 4, innerHeight - rect.height - 4))}px`;
  };
  row.addEventListener("pointerenter", show);
  row.addEventListener("click", show);
  return row;
}
