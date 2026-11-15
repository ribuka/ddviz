// The menu of a numeric color column's scale, opened by a right click on its
// color bar or legend title: draw it as a gradient or cut it into intervals
// (by the width of the values or by the number of rows), pick the color set,
// and reverse the scale's direction. It also has the size of the points
// (shapemenu.js): a gradient's legend has no markers, and the markers of the
// intervals open this menu.
import { COLOR_SETS, scale } from "./colorscale.js";
import { menuHeading, menuItem, Popup } from "./popup.js";
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

const popup = new Popup();

// Opens the menu at a right click; the counts and the way to cut are two
// lists, so that each count shows once. `bins` is the current cutting ({n, by})
// or null for a gradient. `onBins` gets the cutting picked (null for a
// gradient); `onScale` runs after a new color set or direction. `size` is
// the size of the markers and `onSize` gets the size picked.
export function openScaleMenu(event, bins, onBins, onScale, size, onSize) {
  const menu = document.createElement("div");
  menu.className = "scale-menu";
  const item = (text, checked, run) => {
    const pick = () => {
      popup.close();
      run();
    };
    menu.append(menuItem(text, pick, { checked }));
  };
  const heading = (text) => menu.append(menuHeading(text));
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
  heading(SIZE_HEADING);
  for (const pick of SIZES) {
    item(`${pick} px`, pick === size, () => pick !== size && onSize(pick));
  }
  popup.open(menu, event);
}
