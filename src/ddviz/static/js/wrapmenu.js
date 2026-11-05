// The form of the wrapped panels to a row, opened by a right click on the
// Wrap zone (its chip or the room around it) while it holds a column:
// "自動（n）" lays them out closest to square (`wrap_cols: null`), "指定"
// sets a positive integer. The choice and the number are a draft until Enter
// or the apply button; Escape, a click outside the form or another right
// click drop the draft. The form closes and stays in the window as the
// right-click menus do (scalemenu.js).

// The largest number taken: JavaScript's integers are exact up to it.
export const WRAP_COLS_MAX = Number.MAX_SAFE_INTEGER;
export const WRAP_COLS_ERROR = `1 以上 ${WRAP_COLS_MAX} 以下の整数を入力してください`;

let open = null;

export function closeWrapMenu() {
  open?.form.remove();
  open = null;
}

window.addEventListener("pointerdown", (event) => {
  if (open && !open.form.contains(event.target)) closeWrapMenu();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeWrapMenu();
});

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
  if (open) open.autoLabel.textContent = autoText(auto);
}

// Opens the form at a right click. `cols` is the number set (null for
// automatic), `auto` as `setWrapAuto`; `onApply` gets the number applied
// (null for automatic), whether or not it changed.
export function openWrapMenu(event, cols, auto, onApply) {
  closeWrapMenu();
  const form = document.createElement("form");
  form.className = "scale-menu wrap-menu";
  form.noValidate = true;
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = "1 行のパネル数";
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
  form.append(head, automatic.label, manual.label, field, error, apply);

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
    if (event.key !== "Enter" || event.target === apply) return;
    event.preventDefault();
    submit();
  });

  document.body.append(form);
  const { innerWidth, innerHeight } = window;
  const rect = form.getBoundingClientRect();
  form.style.left = `${Math.max(4, Math.min(event.clientX, innerWidth - rect.width - 4))}px`;
  form.style.top = `${Math.max(4, Math.min(event.clientY, innerHeight - rect.height - 4))}px`;
  open = { form, autoLabel: automatic.span };
  (cols === null ? automatic.radio : input).focus();
}
