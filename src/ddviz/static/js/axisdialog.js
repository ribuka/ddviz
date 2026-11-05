// The settings of a numeric axis, opened by a double click on its tick
// labels: its range, the interval of its ticks, how many minor ticks split
// each interval, and reference lines across its panels. The panels of one
// axis column share its axis (`matches`), so the settings are kept by
// column and drawn on every panel of the column (`decorate`); the range is
// the view of the column, which is aggregated again as a zoom is.

// The look of a new reference line, and the dashes offered.
export const LINE_COLOR = "#000000";
export const LINE_DASH = "dash";
const DASHES = [
  ["solid", "実線"],
  ["dash", "破線"],
  ["dot", "点線"],
];
const LINE_WIDTH = 1.5;
// Most minor ticks a tick interval is split into.
const MAX_MINOR = 100;

// Returns the empty settings of a column: automatic ticks, no reference lines.
export function emptySettings() {
  return { dtick: null, minor: null, lines: [] };
}

// Reads a number typed in a field: `{value}`, `{value: null}` for an empty
// field when `optional`, or `{error}`.
function readNumber(text, optional = false) {
  const trimmed = text.trim();
  if (trimmed === "") return optional ? { value: null } : { error: "数値を入れてください" };
  const value = Number(trimmed);
  return Number.isFinite(value) ? { value } : { error: "数値を入れてください" };
}

// Checks the fields of the dialog (texts as typed) and returns the settings
// and range they make, `{range, dtick, minor}`, or the reason of each field
// that is wrong (`{errors: {field: text}}`).
export function readFields({ min, max, dtick, minor }) {
  const errors = {};
  const lo = readNumber(min);
  const hi = readNumber(max);
  if (lo.error) errors.min = lo.error;
  if (hi.error) errors.max = hi.error;
  if (!lo.error && !hi.error && lo.value >= hi.value) errors.max = "最小値より大きくしてください";
  const step = readNumber(dtick, true);
  if (step.error) errors.dtick = step.error;
  else if (step.value !== null && step.value <= 0) errors.dtick = "0 より大きくしてください";
  const parts = readNumber(minor, true);
  if (parts.error) errors.minor = parts.error;
  else if (parts.value !== null) {
    if (!Number.isInteger(parts.value) || parts.value < 2 || parts.value > MAX_MINOR) {
      errors.minor = `2〜${MAX_MINOR} の整数にしてください`;
    } else if (step.value === null && !errors.dtick) {
      errors.minor = "間隔を入れたときだけ使えます";
    }
  }
  if (Object.keys(errors).length) return { errors };
  return { range: [lo.value, hi.value], dtick: step.value, minor: parts.value };
}

// Returns the plotly attributes of an axis with `settings`: linear ticks
// every `dtick` from 0 and minor grid lines splitting each interval, or
// plotly's automatic ticks (null removes what an earlier setting set).
export function tickAttributes(settings) {
  const { dtick, minor } = settings ?? emptySettings();
  if (dtick === null) return { tickmode: null, tick0: null, dtick: null, minor: null };
  return {
    tickmode: "linear",
    tick0: 0,
    dtick,
    minor: minor === null ? null : { dtick: dtick / minor, showgrid: true },
  };
}

// Returns the plotly shapes of the reference lines of every numeric axis
// column of a result (`meta`): a vertical line across each panel of an x
// column, a horizontal one across each panel of a y column.
function lineShapes(meta, settingsOf) {
  const shapes = [];
  for (const panel of meta.panels) {
    const across = [
      [meta.x_numeric[panel.x] && settingsOf(meta.x_columns[panel.x]), panel.xaxis, panel.yaxis, "x"],
      [meta.y_numeric[panel.y] && settingsOf(meta.y_columns[panel.y]), panel.yaxis, panel.xaxis, "y"],
    ];
    for (const [settings, along, other, axis] of across) {
      for (const line of settings?.lines ?? []) {
        const [ref, otherRef] = axis === "x" ? ["xref", "yref"] : ["yref", "xref"];
        const [at0, at1, span0, span1] = axis === "x" ? ["x0", "x1", "y0", "y1"] : ["y0", "y1", "x0", "x1"];
        shapes.push({
          type: "line",
          layer: "above",
          [ref]: along,
          [otherRef]: `${other} domain`,
          [at0]: line.value,
          [at1]: line.value,
          [span0]: 0,
          [span1]: 1,
          line: { color: line.color, dash: line.dash, width: LINE_WIDTH },
        });
      }
    }
  }
  return shapes;
}

// Returns `layout` (a figure's layout for `meta`) with the ticks and
// reference lines of the settings of its numeric axis columns
// (`settingsOf(column)`, or undefined for none).
export function decorate(layout, meta, settingsOf) {
  const out = { ...layout };
  for (const panel of meta.panels) {
    for (const [axis, index, columns, numeric] of [
      [panel.xaxis, panel.x, meta.x_columns, meta.x_numeric],
      [panel.yaxis, panel.y, meta.y_columns, meta.y_numeric],
    ]) {
      const settings = numeric[index] ? settingsOf(columns[index]) : undefined;
      if (!settings || settings.dtick === null) continue;
      const key = axis.replace(/^([xy])/, "$1axis");
      out[key] = { ...out[key], ...withoutNulls(tickAttributes(settings)) };
    }
  }
  const shapes = lineShapes(meta, settingsOf);
  if (shapes.length) out.shapes = shapes;
  return out;
}

// Returns the relayout that draws `settingsOf` on the drawn figure of `meta`:
// the tick attributes of every axis of its numeric columns, and the shapes.
export function decorationUpdate(meta, settingsOf) {
  const update = { shapes: lineShapes(meta, settingsOf) };
  for (const panel of meta.panels) {
    for (const [axis, index, columns, numeric] of [
      [panel.xaxis, panel.x, meta.x_columns, meta.x_numeric],
      [panel.yaxis, panel.y, meta.y_columns, meta.y_numeric],
    ]) {
      if (!numeric[index]) continue;
      const key = axis.replace(/^([xy])/, "$1axis");
      for (const [name, value] of Object.entries(tickAttributes(settingsOf(columns[index])))) {
        update[`${key}.${name}`] = value;
      }
    }
  }
  return update;
}

function withoutNulls(attributes) {
  return Object.fromEntries(Object.entries(attributes).filter(([, value]) => value !== null));
}

// plotly's drag areas of the axes (`ewdrag` along x, `nsdrag` along y, and
// their ends), each in the group of its subplot (`x2y2`).
const AXIS_DRAGS = { ewdrag: "x", wdrag: "x", edrag: "x", nsdrag: "y", sdrag: "y", ndrag: "y" };

// Returns the axis column (of any kind) under a pointer event on `gd`, the plot
// of the result `meta`, as `{axis: "x" | "y", index}` (of `x_columns` or
// `y_columns`), or null. Only the drag areas of the tick labels count,
// outside every panel: an axis's area reaches over the edge of a
// neighboring panel, whose double click resets the view.
export function axisAt(event, gd, meta) {
  const drag = event.target.closest?.(".draglayer rect.drag");
  if (!drag || !meta) return null;
  const axis = [...drag.classList].map((name) => AXIS_DRAGS[name]).find(Boolean);
  const subplot = drag.parentElement?.getAttribute("class")?.match(/^(x\d*)(y\d*)$/);
  if (!axis || !subplot) return null;
  const full = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  for (const panel of meta.panels) {
    const xa = full[panel.xaxis.replace(/^x/, "xaxis")];
    const ya = full[panel.yaxis.replace(/^y/, "yaxis")];
    if (!xa || !ya) continue;
    const inside =
      px >= xa._offset && px <= xa._offset + xa._length && py >= ya._offset && py <= ya._offset + ya._length;
    if (inside) return null;
  }
  const id = axis === "x" ? subplot[1] : subplot[2];
  const panel = meta.panels.find((p) => (axis === "x" ? p.xaxis : p.yaxis) === id);
  if (!panel) return null;
  const index = axis === "x" ? panel.x : panel.y;
  return { axis, index };
}

// Writes a number into a field, as the shortest text that reads back the
// same number: a rounded one could make the range of a deep zoom empty, or
// change the settings when they are applied again.
function numberText(value) {
  return value === null || value === undefined ? "" : String(value);
}

let open = null;

// Opens the dialog of an axis column. `title` heads it ("X 軸: x"), `range`
// is the range shown, `settings` the column's (`emptySettings` for none).
// `onApply(settings, range)` draws them, on OK (which closes the dialog) and
// on Apply (which keeps it open); Cancel and Esc close it, keeping what was
// applied.
export function openAxisDialog({ title, range, settings, onApply }) {
  open?.close();
  const dialog = document.createElement("dialog");
  dialog.className = "axis-dialog";
  const head = document.createElement("h2");
  head.className = "axis-dialog-title";
  head.textContent = title;
  dialog.append(head);

  const errors = new Map();
  const field = (section, label, value, name, placeholder = "") => {
    const row = document.createElement("label");
    row.className = "axis-dialog-field";
    const text = document.createElement("span");
    text.className = "axis-dialog-label";
    text.textContent = label;
    const input = document.createElement("input");
    Object.assign(input, { type: "text", inputMode: "decimal", value, placeholder, name });
    input.spellcheck = false;
    const error = document.createElement("span");
    error.className = "axis-dialog-error";
    errors.set(name, error);
    row.append(text, input, error);
    section.append(row);
    return input;
  };
  const section = (heading) => {
    const box = document.createElement("section");
    box.className = "axis-dialog-section";
    const h = document.createElement("h3");
    h.textContent = heading;
    box.append(h);
    dialog.append(box);
    return box;
  };

  const rangeBox = section("範囲");
  const min = field(rangeBox, "最小値", numberText(range[0]), "min");
  const max = field(rangeBox, "最大値", numberText(range[1]), "max");
  const ticksBox = section("目盛り");
  const dtick = field(ticksBox, "間隔", numberText(settings.dtick), "dtick", "自動");
  const minor = field(ticksBox, "補助目盛りの数", numberText(settings.minor), "minor", "なし");
  minor.inputMode = "numeric";
  minor.title = "主目盛りの 1 間隔を何分割するか。間隔を入れたときだけ使える";

  const linesBox = section("参照線");
  const value = field(linesBox, "値", "", "line");
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "追加";
  value.parentElement.insertBefore(add, errors.get("line"));
  const list = document.createElement("div");
  list.className = "axis-dialog-lines";
  linesBox.append(list);
  let lines = settings.lines.map((line) => ({ ...line }));

  const renderLines = () => {
    list.replaceChildren(
      ...lines.map((line, i) => {
        const row = document.createElement("div");
        row.className = "axis-dialog-line";
        const at = document.createElement("span");
        at.className = "axis-dialog-line-value";
        at.textContent = numberText(line.value);
        const color = document.createElement("input");
        Object.assign(color, { type: "color", value: line.color, title: "色" });
        color.addEventListener("input", () => {
          line.color = color.value;
        });
        const dash = document.createElement("select");
        dash.title = "線の種類";
        for (const [key, text] of DASHES) dash.append(new Option(text, key, false, key === line.dash));
        dash.addEventListener("change", () => {
          line.dash = dash.value;
        });
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "削除";
        remove.addEventListener("click", () => {
          lines = lines.filter((_, j) => j !== i);
          renderLines();
        });
        row.append(at, color, dash, remove);
        return row;
      }),
    );
    list.hidden = !lines.length;
  };
  renderLines();

  const addLine = () => {
    const read = readNumber(value.value);
    errors.get("line").textContent = read.error ?? "";
    if (read.error) return;
    lines = [...lines, { value: read.value, color: LINE_COLOR, dash: LINE_DASH }];
    value.value = "";
    renderLines();
  };
  add.addEventListener("click", addLine);
  value.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    addLine();
  });

  // Applies the fields, or shows why not; returns whether they were applied.
  const apply = () => {
    const read = readFields({ min: min.value, max: max.value, dtick: dtick.value, minor: minor.value });
    for (const name of ["min", "max", "dtick", "minor"]) {
      errors.get(name).textContent = read.errors?.[name] ?? "";
    }
    if (read.errors) return false;
    onApply({ dtick: read.dtick, minor: read.minor, lines: lines.map((line) => ({ ...line })) }, read.range);
    return true;
  };

  const buttons = document.createElement("div");
  buttons.className = "axis-dialog-buttons";
  const button = (text, run) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = text;
    b.addEventListener("click", run);
    buttons.append(b);
    return b;
  };
  button("OK", () => {
    if (apply()) dialog.close();
  }).classList.add("primary");
  button("キャンセル", () => dialog.close());
  button("適用", apply);
  dialog.append(buttons);

  // Enter in a field of the range or ticks is OK; Esc is Cancel (the dialog's own).
  for (const input of [min, max, dtick, minor]) {
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      if (apply()) dialog.close();
    });
  }
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (open === dialog) open = null;
  });
  document.body.append(dialog);
  open = dialog;
  dialog.showModal();
  min.focus();
  min.select();
  return dialog;
}
