// The menu of a listed column (a right click on its row in the column list):
// add the column to the filter pane or to a role of the graph builder,
// without dragging it there. Ten items, always in this order; one that
// cannot be done stays in its place, disabled, with the reason as its tip.
// Overwrite on X or Y replaces the axis there when there is one; with two
// or more, it opens a submenu of the axes in their order (`1. name`), and
// the one picked is replaced in its place. Append puts the column after the
// last axis (first on an empty one). The other roles hold one column, which
// is replaced without asking. The builder checks the placement again when
// an item is picked (`Builder.menuPlace`). A click outside, Escape, or an
// item picked closes the menu; so does a search that no longer lists the
// column (`closeColumnMenuIfGone`).

const ITEMS = [
  ["filter", null, "Add to Local filter"],
  ["x", "overwrite", "Add to Xaxis (Overwrite)"],
  ["x", "append", "Add to Xaxis (Append)"],
  ["y", "overwrite", "Add to Yaxis (Overwrite)"],
  ["y", "append", "Add to Yaxis (Append)"],
  ["symbol", "set", "Add to Symbol"],
  ["color", "set", "Add to Color"],
  ["col", "set", "Add to GroupX"],
  ["row", "set", "Add to GroupY"],
  ["wrap", "set", "Add to Wrap"],
];
const PLACED = "既に配置済み";

// The open menu and its submenu, and the name of its column; null when closed.
let open = null;
let sub = null;
let target = null;

export function closeColumnMenu() {
  closeSub();
  open?.remove();
  open = null;
  target = null;
}

function closeSub() {
  sub?.remove();
  sub = null;
}

// Closes the menu when its column is not among `names` (the columns listed).
export function closeColumnMenuIfGone(names) {
  if (target !== null && !names.includes(target)) closeColumnMenu();
}

window.addEventListener("pointerdown", (event) => {
  if (open && !open.contains(event.target) && !sub?.contains(event.target)) closeColumnMenu();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeColumnMenu();
});

// Opens the menu of `column` (`{name, numeric, temporal, placed}`, where
// `placed()` is called when it is placed) at the pointer of `event`.
// `builder` is the graph builder, `filters` the filter pane.
export function openColumnMenu(event, column, builder, filters) {
  closeColumnMenu();
  const menu = document.createElement("div");
  menu.className = "scale-menu column-menu";
  for (const [role, mode, text] of ITEMS) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scale-menu-item";
    row.dataset.role = role;
    if (mode) row.dataset.mode = mode;
    row.textContent = text;
    menu.append(row);
    if (role === "filter") {
      const reasons = filters.has(column.name) ? [PLACED] : [];
      disable(row, reasons);
      row.addEventListener("pointerenter", closeSub);
      row.addEventListener("click", () => {
        closeColumnMenu();
        if (filters.has(column.name)) return;
        filters.add(column);
        column.placed?.();
      });
      continue;
    }
    disable(row, builder.menuRefusals(role, mode, column.name));
    if (row.disabled) {
      row.addEventListener("pointerenter", closeSub);
      continue;
    }
    const axes = mode === "overwrite" ? builder.placed(role) : [];
    if (axes.length > 1) {
      row.classList.add("has-sub");
      const show = () => {
        if (sub?.dataset.role === role) return;
        closeSub();
        sub = axisMenu(row, role, axes, (index) => {
          closeColumnMenu();
          builder.menuPlace(role, mode, column, index);
        });
      };
      row.addEventListener("pointerenter", show);
      row.addEventListener("click", show);
    } else {
      row.addEventListener("pointerenter", closeSub);
      row.addEventListener("click", () => {
        closeColumnMenu();
        builder.menuPlace(role, mode, column, 0);
      });
    }
  }
  document.body.append(menu);
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(event.clientX, innerWidth - rect.width - 4))}px`;
  menu.style.top = `${Math.max(4, Math.min(event.clientY, innerHeight - rect.height - 4))}px`;
  open = menu;
  target = column.name;
}

// Disables `row` when there are `reasons` it cannot be done, shown as its tip.
function disable(row, reasons) {
  row.disabled = reasons.length > 0;
  row.title = reasons.join("、");
}

// Opens the submenu of `role`'s axes (`names`, in their order) beside
// `row`; `pick` gets the index of the axis picked.
function axisMenu(row, role, names, pick) {
  const menu = document.createElement("div");
  menu.className = "scale-menu column-submenu";
  menu.dataset.role = role;
  names.forEach((name, index) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "scale-menu-item";
    item.textContent = `${index + 1}. ${name}`;
    item.addEventListener("click", () => pick(index));
    menu.append(item);
  });
  document.body.append(menu);
  const box = row.getBoundingClientRect();
  const rect = menu.getBoundingClientRect();
  const { innerWidth, innerHeight } = window;
  // Beside the menu on the right, or on the left without room.
  const left = box.right + rect.width + 4 <= innerWidth ? box.right : box.left - rect.width;
  menu.style.left = `${Math.max(4, left)}px`;
  menu.style.top = `${Math.max(4, Math.min(box.top - 4, innerHeight - rect.height - 4))}px`;
  return menu;
}
