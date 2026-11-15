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
import { menuItem, Popup } from "./popup.js";

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
// The narrowest a submenu of long names is cut to beside the menu; with
// less room on both sides, it takes the window's width over the menu.
const SUBMENU_MIN_WIDTH = 120;

// The submenu of the open menu, and the name of its column; null when closed.
let sub = null;
let target = null;

function closeSub() {
  sub?.remove();
  sub = null;
}

const popup = new Popup({
  onClose: () => {
    closeSub();
    target = null;
  },
  inside: () => [sub],
});

export function closeColumnMenu() {
  popup.close();
}

// Closes the menu when its column is not among `names` (the columns listed).
export function closeColumnMenuIfGone(names) {
  if (target !== null && !names.includes(target)) closeColumnMenu();
}

// Opens the menu of `column` (`{name, numeric, temporal, placed}`, where
// `placed()` is called when it is placed) at the pointer of `event`.
// `builder` is the graph builder, `filters` the filter pane.
export function openColumnMenu(event, column, builder, filters) {
  const menu = document.createElement("div");
  menu.className = "scale-menu column-menu";
  for (const [role, mode, text] of ITEMS) {
    const filter = role === "filter";
    let reasons;
    if (filter) reasons = filters.has(column.name) ? [PLACED] : [];
    else reasons = builder.menuRefusals(role, mode, column.name);
    const axes = !filter && reasons.length === 0 && mode === "overwrite" ? builder.placed(role) : [];
    // On hover, the item closes the submenu, or opens its own.
    let hover = closeSub;
    let pick;
    if (filter) {
      pick = () => {
        closeColumnMenu();
        if (filters.has(column.name)) return;
        filters.add(column);
        column.placed?.();
      };
    } else if (axes.length > 1) {
      hover = () => {
        if (sub?.dataset.role === role) return;
        closeSub();
        sub = axisMenu(row, role, axes, (index) => {
          closeColumnMenu();
          builder.menuPlace(role, mode, column, index);
        });
      };
      pick = hover;
    } else {
      pick = () => {
        closeColumnMenu();
        builder.menuPlace(role, mode, column, 0);
      };
    }
    // An item that cannot be done is disabled, with the reasons as its tip.
    const row = menuItem(text, pick, { disabled: reasons.length > 0 });
    row.title = reasons.join("、");
    row.dataset.role = role;
    if (mode) row.dataset.mode = mode;
    if (axes.length > 1) row.classList.add("has-sub");
    row.addEventListener("pointerenter", hover);
    menu.append(row);
  }
  popup.open(menu, event);
  target = column.name;
}

// Opens the submenu of `role`'s axes (`names`, in their order) beside
// `row`; `pick` gets the index of the axis picked.
function axisMenu(row, role, names, pick) {
  const menu = document.createElement("div");
  menu.className = "scale-menu column-submenu";
  menu.dataset.role = role;
  names.forEach((name, index) => {
    menu.append(menuItem(`${index + 1}. ${name}`, () => pick(index)));
  });
  document.body.append(menu);
  const box = row.getBoundingClientRect();
  const { innerWidth, innerHeight } = window;
  const width = menu.getBoundingClientRect().width;
  // The room beside the menu on the right and on the left.
  const right = innerWidth - box.right - 4;
  const leftRoom = box.left - 4;
  let left;
  if (width <= right) {
    left = box.right;
  } else if (width <= leftRoom) {
    left = box.left - width;
  } else {
    // Long names: the submenu takes the wider side and wraps them; with
    // little room on both sides, the window's width, over the menu.
    const room = Math.max(right, leftRoom);
    const cap = room >= SUBMENU_MIN_WIDTH ? room : innerWidth - 8;
    menu.style.maxWidth = `${cap}px`;
    menu.style.minWidth = `${Math.min(cap, SUBMENU_MIN_WIDTH)}px`;
    const capped = menu.getBoundingClientRect().width;
    left = room < SUBMENU_MIN_WIDTH ? 4 : right >= leftRoom ? box.right : box.left - capped;
  }
  const height = menu.getBoundingClientRect().height;
  menu.style.left = `${Math.max(4, left)}px`;
  menu.style.top = `${Math.max(4, Math.min(box.top - 4, innerHeight - height - 4))}px`;
  return menu;
}
