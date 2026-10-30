// The menu of the legend's markers, opened by a right click on a marker
// (legend.js) while the overlay draws shapes: the size of the shapes
// (`ddviz.server.plan.SHAPE_SIZES`). Options of each item, such as its color
// or shape, are to come here too.

const SIZES = [3, 5, 7, 9, 11, 15];
export const DEFAULT_SHAPE_SIZE = 7;

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

// Opens the menu at a right click. `size` is the current size; `onPick`
// gets the size picked.
export function openShapeMenu(event, size, onPick) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu shape-menu";
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = "形の大きさ（凡例全体）";
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
  menu.style.left = `${Math.min(event.clientX, innerWidth - rect.width - 4)}px`;
  menu.style.top = `${Math.min(event.clientY, innerHeight - rect.height - 4)}px`;
  open = menu;
}
