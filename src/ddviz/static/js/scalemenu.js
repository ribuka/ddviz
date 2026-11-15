// The menu of a numeric color column's scale, opened by a right click on its
// color bar or legend title: draw it as a gradient or cut it into intervals
// (by the width of the values or by the number of rows), pick the color set,
// and reverse the scale's direction. It also has the size of the points
// (shapemenu.js): a gradient's legend has no markers, and the markers of the
// intervals open this menu. The number of intervals is typed, an integer from
// 2 to `plot.max_levels`; it is a draft until Enter or the apply button, and
// closing the menu any other way drops it (as wrapmenu.js).
import { COLOR_SETS, scale } from "./colorscale.js";
import { plainEnter } from "./keys.js";
import { menuHeading, menuItem, placeAt, Popup } from "./popup.js";
import { SIZE_HEADING, SIZES } from "./shapemenu.js";

// The fewest intervals (`ddviz.server.plotoptions.COLOR_BINS_MIN`).
export const COLOR_BINS_MIN = 2;
export const NO_LIMIT_NOTE = "区間数の上限を取得できません";
export const LOW_LIMIT_NOTE = "区間に分けるには plot.max_levels を 2 以上にしてください";
const BY = [
  ["values", "値の幅で等分"],
  ["rows", "行数で等分"],
];

// How to cut, kept while a gradient is drawn so that a count picked later
// cuts that way.
let preferredBy = "values";

const popup = new Popup();

// The most intervals taken under `maxLevels` (`plot.max_levels`): JavaScript's
// integers are exact up to `Number.MAX_SAFE_INTEGER`.
function topOf(maxLevels) {
  return Math.min(maxLevels, Number.MAX_SAFE_INTEGER);
}

export function colorBinsError(maxLevels) {
  return `${COLOR_BINS_MIN} 以上 ${topOf(maxLevels)} 以下の整数を入力してください`;
}

// The number of intervals of the text, or null when it is not an integer from
// `COLOR_BINS_MIN` to `maxLevels`: ASCII digits only (leading zeros allowed)
// between blanks, so no sign, decimal point or exponent.
export function parseColorBins(text, maxLevels) {
  const digits = text.trim();
  if (!/^[0-9]+$/.test(digits)) return null;
  const n = Number(digits);
  return n >= COLOR_BINS_MIN && n <= topOf(maxLevels) ? n : null;
}

// The form of the number of intervals. `n` is the number applied (null for a
// gradient); `maxLevels` the limit, or null before the page has it (the
// form is then off, as with a limit under 2). `onApply` gets a valid number.
function countForm(n, maxLevels, onApply) {
  const form = document.createElement("form");
  form.className = "scale-menu-count";
  form.noValidate = true;
  const input = document.createElement("input");
  input.type = "text";
  input.inputMode = "numeric";
  input.id = "color-bins-input";
  input.className = "scale-menu-count-input";
  input.autocomplete = "off";
  input.value = n === null ? "" : String(n);
  const label = document.createElement("label");
  label.htmlFor = input.id;
  label.textContent = "区間数";
  const apply = document.createElement("button");
  apply.type = "submit";
  apply.className = "scale-menu-count-apply";
  apply.textContent = "適用";
  const error = document.createElement("div");
  error.className = "scale-menu-count-error";
  error.setAttribute("role", "alert");
  error.hidden = true;
  const field = document.createElement("div");
  field.className = "scale-menu-count-field";
  field.append(label, input, apply);
  form.append(field, error);

  const note = maxLevels === null ? NO_LIMIT_NOTE : maxLevels < COLOR_BINS_MIN ? LOW_LIMIT_NOTE : null;
  if (note) {
    input.disabled = true;
    apply.disabled = true;
    error.textContent = note;
    error.className = "scale-menu-count-note";
    error.removeAttribute("role");
    error.hidden = false;
  }
  input.addEventListener("input", () => {
    if (!note) error.hidden = true;
  });
  const submit = () => {
    if (note) return;
    const value = parseColorBins(input.value, maxLevels);
    if (value === null) {
      error.textContent = colorBinsError(maxLevels);
      error.hidden = false;
      // The error makes the menu taller: keep it in the window.
      const menu = form.closest(".scale-menu");
      if (menu) {
        const { left, top } = menu.getBoundingClientRect();
        placeAt(menu, left, top);
      }
      input.focus();
      return;
    }
    onApply(value);
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });
  input.addEventListener("keydown", (event) => {
    if (!plainEnter(event)) return;
    event.preventDefault();
    submit();
  });
  return form;
}

// Opens the menu at a right click; the number of intervals and the way to cut
// are apart, so that the number is typed once. `bins` is the current cutting
// ({n, by}) or null for a gradient. `onBins` gets the cutting picked (null for
// a gradient), only when it changes; `onScale` runs after a new color set or
// direction. `size` is the size of the markers and `onSize` gets the size
// picked. `maxLevels` is `plot.max_levels`, or null while the page does not
// have it.
export function openScaleMenu(event, bins, onBins, onScale, size, onSize, maxLevels) {
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
  menu.append(
    countForm(bins?.n ?? null, maxLevels, (n) => {
      popup.close();
      if (n !== bins?.n || by !== bins?.by) onBins({ n, by });
    }),
  );
  heading("分け方");
  for (const [key, text] of BY) {
    item(text, by === key, () => {
      if (by === key) return;
      preferredBy = key;
      // A gradient keeps the choice for a number applied later.
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
