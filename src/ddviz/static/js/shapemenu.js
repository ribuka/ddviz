// The menus of the size of the markers (`ddviz.server.plan.SHAPE_SIZES`):
// of every series, opened by a right click on the points' element icon
// (elements.js), on a color item's marker of the legend (legend.js) or, for
// a gradient, from its scale's menu (scalemenu.js); of one overlay level's
// shapes, opened by a right click on that level's marker in the overlay's
// legend. Picking the size of every series drops the sizes of single levels.

export const SIZES = [3, 5, 7, 9, 11, 15];
export const SIZE_HEADING = "点の大きさ（全系列）";

// Heading of the menu of an overlay level's shapes.
export function levelHeading(level) {
  return `形「${level}」の大きさ`;
}

let open = null;

function close() {
  open?.remove();
  open = null;
}

window.addEventListener("pointerdown", (event) => {
  if (open && !open.contains(event.target)) close();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") close();
});

// Opens the menu at a right click, under `heading`. `size` is the current
// size; `onPick` gets the size picked.
export function openShapeMenu(event, heading, size, onPick) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu shape-menu";
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = heading;
  menu.append(head);
  for (const pick of SIZES) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scale-menu-item";
    row.classList.toggle("checked", pick === size);
    row.textContent = `${pick} px`;
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
