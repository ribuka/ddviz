// The form of the wrapped panels to a row, opened by a right click on the
// Wrap zone (its chip or the room around it) while it holds a column:
// "自動（n）" lays them out closest to square (`wrap_cols: null`), "指定"
// sets a positive integer. The choice and the number are a draft until Enter
// or the apply button; Escape, a click outside the form or another right
// click drop the draft. The form closes and stays in the window as the
// right-click menus do (scalemenu.js).
//
// Above them, the checkbox "Show null rows" draws the rows whose wrap value
// is null or NaN as a panel of their own (`ddviz.shared.missing`), as the
// item of the other zones' menu (zonemenu.js); toggling it takes effect at
// once, the form staying open and the draft of the number kept; a plot
// that fails turns it back (`setWrapNullRows`).
//
// At the bottom, under a separator, the item "Stash" of the other zones'
// menu (zonemenu.js) stashes the wrap column or takes the stash off and
// closes the form; Enter on it does that, not apply the number. A number
// applied while the column is stashed is kept for when the stash is taken
// off.
import { plainEnter } from "./keys.js";
import { menuHeading, menuSeparator, Popup } from "./popup.js";
import { checkedItem, STASH_TEXT } from "./zonemenu.js";

// The largest number taken: JavaScript's integers are exact up to it.
export const WRAP_COLS_MAX = Number.MAX_SAFE_INTEGER;
export const WRAP_COLS_ERROR = `1 以上 ${WRAP_COLS_MAX} 以下の整数を入力してください`;

// The label of "自動（n）" and the checkbox "Show null rows" in the open
// form, or null when closed.
let autoLabel = null;
let nullRowsBox = null;
const popup = new Popup({
  onClose: () => {
    autoLabel = null;
    nullRowsBox = null;
  },
});

export function closeWrapMenu() {
  popup.close();
}

// The number of the text, or null when it is not an integer from 1 to
// `WRAP_COLS_MAX`: ASCII digits only (leading zeros allowed) between blanks,
// so no sign, decimal point or exponent.
export function parseWrapCols(text) {
  const digits = text.trim();
  if (!/^[0-9]+$/.test(digits)) return null;
  const n = Number(digits);
  return n >= 1 && n <= WRAP_COLS_MAX ? n : null;
}

function autoText(auto) {
  return auto === null ? "自動" : `自動（${auto}）`;
}

// Shows `auto`, the number to a row of the latest result (null without one
// for the wrap column), in an open form.
export function setWrapAuto(auto) {
  if (autoLabel) autoLabel.textContent = autoText(auto);
}

// Shows the setting "Show null rows" in an open form: a failed plot turns it
// back.
export function setWrapNullRows(checked) {
  if (nullRowsBox) nullRowsBox.checked = checked;
}

// Opens the form at a right click. `cols` is the number set (null for
// automatic), `auto` as `setWrapAuto`; `onApply` gets the number applied
// (null for automatic), whether or not it changed. `stashed` tells whether
// the column is stashed, and `onStash()` runs when "Stash" is picked.
// `showNullRows` is the checkbox's state, and `onNullRows(checked)` runs
// when it is toggled.
export function openWrapMenu(event, cols, auto, onApply, { stashed, onStash, showNullRows, onNullRows }) { // noqa: PLR0915
  const form = document.createElement("form");
  form.className = "scale-menu wrap-menu";
  form.noValidate = true;
  const choice = (text) => {
    const label = document.createElement("label");
    label.className = "wrap-menu-choice";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "wrap-cols-mode";
    const span = document.createElement("span");
    span.textContent = text;
    label.append(radio, span);
    return { label, radio, span };
  };
  const automatic = choice(autoText(auto));
  const manual = choice("指定");
  const input = document.createElement("input");
  input.type = "text";
  input.inputMode = "numeric";
  input.id = "wrap-cols-input";
  input.className = "wrap-menu-input";
  input.autocomplete = "off";
  const inputLabel = document.createElement("label");
  inputLabel.htmlFor = input.id;
  inputLabel.className = "wrap-menu-input-label";
  inputLabel.textContent = "パネル数";
  const field = document.createElement("div");
  field.className = "wrap-menu-field";
  field.append(inputLabel, input);
  const error = document.createElement("div");
  error.className = "wrap-menu-error";
  error.setAttribute("role", "alert");
  error.hidden = true;
  const apply = document.createElement("button");
  apply.type = "submit";
  apply.className = "wrap-menu-apply";
  apply.textContent = "適用";
  const nullRows = document.createElement("label");
  nullRows.className = "wrap-menu-null-rows";
  const nullBox = document.createElement("input");
  nullBox.type = "checkbox";
  nullBox.checked = showNullRows;
  nullBox.addEventListener("change", () => onNullRows(nullBox.checked));
  const nullText = document.createElement("span");
  nullText.textContent = "Show null rows";
  nullRows.append(nullBox, nullText);
  const stash = checkedItem("stash", STASH_TEXT, stashed, onStash, closeWrapMenu);
  stash.classList.add("wrap-menu-stash");
  const separator = menuSeparator();
  separator.classList.add("wrap-menu-separator");
  form.append(nullRows, menuHeading("1 行のパネル数"), automatic.label, manual.label, field, error, apply, separator, stash);

  const showMode = (isManual) => {
    input.disabled = !isManual;
    if (!isManual) input.value = "";
    error.hidden = true;
  };
  automatic.radio.checked = cols === null;
  manual.radio.checked = cols !== null;
  input.value = cols === null ? "" : String(cols);
  input.disabled = cols === null;
  automatic.radio.addEventListener("change", () => showMode(false));
  manual.radio.addEventListener("change", () => {
    showMode(true);
    input.focus();
  });
  input.addEventListener("input", () => {
    error.hidden = true;
  });

  const submit = () => {
    let value = null;
    if (manual.radio.checked) {
      value = parseWrapCols(input.value);
      if (value === null) {
        error.textContent = WRAP_COLS_ERROR;
        error.hidden = false;
        input.focus();
        return;
      }
    }
    closeWrapMenu();
    onApply(value);
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });
  // Enter applies from the choices too, not only from the text field.
  form.addEventListener("keydown", (event) => {
    // On the apply button and on "Stash", Enter clicks them.
    if (!plainEnter(event) || event.target === apply || event.target === stash) return;
    event.preventDefault();
    submit();
  });

  popup.open(form, event);
  autoLabel = automatic.span;
  nullRowsBox = nullBox;
  (cols === null ? automatic.radio : input).focus();
}
