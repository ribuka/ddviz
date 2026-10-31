// The menu of a numeric color column's scale, opened by a right click on its
// color bar or legend title: draw it as a gradient or cut it into intervals
// (by the width of the values or by the number of rows), pick the color set,
// and reverse the scale's direction. A gradient's legend has no markers, so
// its menu also has the size of the points (shapemenu.js).
import { COLOR_SETS, scale } from "./colorscale.js";
import { SIZE_HEADING, SIZES } from "./shapemenu.js";

// Numbers of intervals offered (`ddviz.server.plan.COLOR_BINS`).
const COUNTS = [2, 3, 5, 10];
const BY = [
  ["values", "値の幅で等分"],
  ["rows", "行数で等分"],
];

// How to cut, kept while a gradient is drawn so that a count picked later
// cuts that way.
let preferredBy = "values";

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

// Opens the menu at a right click; the counts and the way to cut are two
// lists, so that each count shows once. `bins` is the current cutting ({n, by})
// or null for a gradient. `onBins` gets the cutting picked (null for a
// gradient); `onScale` runs after a new color set or direction. For a
// gradient, `size` is the size of the markers and `onSize` gets the size
// picked.
export function openScaleMenu(event, bins, onBins, onScale, size, onSize) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu";
  const item = (text, checked, run) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scale-menu-item";
    row.classList.toggle("checked", checked);
    row.textContent = text;
    row.addEventListener("click", () => {
      close();
      run();
    });
    menu.append(row);
  };
  const heading = (text) => {
    const head = document.createElement("div");
    head.className = "scale-menu-heading";
    head.textContent = text;
    menu.append(head);
  };
  const by = bins?.by ?? preferredBy;
  item("連続（グラデーション）", bins === null, () => bins !== null && onBins(null));
  heading("区間に分ける");
  for (const n of COUNTS) {
    const on = bins?.n === n;
    item(`${n} 個`, on, () => !on && onBins({ n, by }));
  }
  heading("分け方");
  for (const [key, text] of BY) {
    item(text, by === key, () => {
      if (by === key) return;
      preferredBy = key;
      // A gradient keeps the choice for a count picked later.
      if (bins) onBins({ n: bins.n, by: key });
    });
  }
  heading("色");
  for (const [key, set] of Object.entries(COLOR_SETS)) {
    item(set.label, scale.set === key, () => {
      if (scale.set === key) return;
      scale.set = key;
      onScale();
    });
  }
  item("向きを反転", scale.reverse, () => {
    scale.reverse = !scale.reverse;
    onScale();
  });
  if (bins === null) {
    heading(SIZE_HEADING);
    for (const pick of SIZES) {
      item(`${pick} px`, pick === size, () => pick !== size && onSize(pick));
    }
  }
  document.body.append(menu);
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(event.clientX, innerWidth - rect.width - 4)}px`;
  menu.style.top = `${Math.min(event.clientY, innerHeight - rect.height - 4)}px`;
  open = menu;
}
