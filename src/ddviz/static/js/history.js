// The history of the drawing settings committed, for undo and redo
// (docs/spec.md, "undo/redo"). Pure: the page captures and applies the
// settings (`app.js`), this keeps the steps and the position among them.

// The most steps kept: past it, the oldest go.
export const MAX_STEPS = 50;

// Returns `value` as a JSON text with the keys of its objects sorted, and a
// `Map` as the array of its `[key, value]` entries sorted by key (a `Set` as
// its values sorted): settings that differ only in the order of their keys
// or entries give the same text.
export function settingsKey(value) {
  return JSON.stringify(canonical(value));
}

function canonical(value) {
  if (value instanceof Map) {
    return [...value].map(([k, v]) => [canonical(k), canonical(v)]).sort((a, b) => compare(a[0], b[0]));
  }
  if (value instanceof Set) return [...value].map(canonical).sort(compare);
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object") {
    // No prototype: a key "__proto__" (a column or level name) is a key.
    const out = Object.create(null);
    for (const key of Object.keys(value).sort()) {
      if (value[key] !== undefined) out[key] = canonical(value[key]);
    }
    return out;
  }
  return value;
}

function compare(a, b) {
  const x = JSON.stringify(a);
  const y = JSON.stringify(b);
  return x < y ? -1 : x > y ? 1 : 0;
}

export class SettingsHistory {
  constructor(max = MAX_STEPS) {
    this.max = max;
    // The steps, oldest first: `{settings, key}`.
    this.steps = [];
    // The step of the settings shown, or -1 before the first.
    this.index = -1;
  }

  // Adds `settings` as a step after the one shown, dropping the steps of
  // redo, unless they are the settings of the step shown (`settingsKey`).
  // Returns whether a step was added.
  push(settings) {
    const key = settingsKey(settings);
    if (this.index >= 0 && this.steps[this.index].key === key) return false;
    this.steps.splice(this.index + 1);
    this.steps.push({ settings: structuredClone(settings), key });
    if (this.steps.length > this.max) this.steps.splice(0, this.steps.length - this.max);
    this.index = this.steps.length - 1;
    return true;
  }

  get canUndo() {
    return this.index > 0;
  }

  get canRedo() {
    return this.index < this.steps.length - 1;
  }

  // Returns the step undo goes to (`{index, settings}`), or null.
  undoTarget() {
    return this.canUndo ? this.target(this.index - 1) : null;
  }

  // Returns the step redo goes to (`{index, settings}`), or null.
  redoTarget() {
    return this.canRedo ? this.target(this.index + 1) : null;
  }

  target(index) {
    return { index, settings: structuredClone(this.steps[index].settings) };
  }

  // Makes the step `index` the one shown, once its settings are committed.
  moveTo(index) {
    if (index < 0 || index >= this.steps.length) return;
    this.index = index;
  }
}
