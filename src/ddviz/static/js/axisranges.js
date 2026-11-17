// Which axis ranges the page keeps when the filter or the graph changes
// (Issue #228): the lock of the continuous axes' ranges, and the axes set by
// hand (a zoom, a pan or the range of the axis dialog). An axis not kept
// takes the automatic range of the filter (the result's `x_auto`, `y_auto`:
// `ddviz.compute.aggregate.Aggregation.x_auto`).
import { axisKey } from "./axiskey.js";
import { axisCoordinates, sameRange } from "./ranges.js";

// Whether the axis column `index` of `role` of a result is continuous: not
// categorical, nor the one band of a figure without x. The lock acts on
// these only.
export function isContinuous(meta, role, index) {
  const column = meta[`${role}_columns`][index];
  return !(role === "x" && meta.one_band) && !meta.axis_levels?.[column];
}

// Whether a result has a continuous axis: the lock is of no use without one.
export function hasContinuous(meta) {
  return ["x", "y"].some((role) => meta[`${role}_columns`].some((_, i) => isContinuous(meta, role, i)));
}

// Whether a result colors by a numeric column: a gradient or intervals,
// whose color scale (the range, or the breaks: `meta.color.scale`) the
// lock keeps too (Issue #264).
export function hasNumericColor(meta) {
  return ["gradient", "bins"].includes(meta.color?.kind);
}

// Whether the lock is of use for a result: with a continuous axis or a
// numeric color.
export function lockable(meta) {
  return hasContinuous(meta) || hasNumericColor(meta);
}

// Returns the key of an axis column of a result: its role, its column and
// what its coordinates mean (`axisCoordinates`). The same column moved to
// the other role, or on a log axis instead of a linear one, is another axis.
export function axisId(meta, role, index) {
  return JSON.stringify([role, meta[`${role}_columns`][index], axisCoordinates(meta, role, index)]);
}

// Returns the automatic ranges of a result (`{x, y}`, one per axis column).
export function autoRanges(meta) {
  return { x: meta.x_auto, y: meta.y_auto };
}

// Returns the role and index of the axis column of each plotly axis key of
// a result's panels ("xaxis3" -> {role: "x", index}).
export function axisColumns(meta) {
  const out = new Map();
  for (const panel of meta.panels) {
    out.set(axisKey(panel.xaxis), { role: "x", index: panel.x });
    out.set(axisKey(panel.yaxis), { role: "y", index: panel.y });
  }
  return out;
}

// Returns the axis columns whose range a `plotly_relayout` event of a
// result's figure set (its `xaxis2.range[0]` or `yaxis.range` keys).
export function movedAxes(meta, event) {
  const columns = axisColumns(meta);
  const moved = [];
  const seen = new Set();
  for (const key of Object.keys(event)) {
    const match = /^([xy]axis\d*)\.range/.exec(key);
    const axis = match && columns.get(match[1]);
    if (!axis || seen.has(`${axis.role}${axis.index}`)) continue;
    seen.add(`${axis.role}${axis.index}`);
    moved.push(axis);
  }
  return moved;
}

export class AxisRanges {
  constructor() {
    // The lock: the continuous axes keep their shown ranges.
    this.frozen = false;
    // The axes set by hand (`axisId`), which keep their ranges with the lock off.
    this.manual = new Set();
  }

  // Marks an axis column of a result as set by hand.
  setByHand(meta, role, index) {
    this.manual.add(axisId(meta, role, index));
  }

  // Whether an axis column of a result was set by hand.
  byHand(meta, role, index) {
    return this.manual.has(axisId(meta, role, index));
  }

  // Whether an axis column of a result keeps its shown range through a new
  // filter or graph: set by hand, or continuous under the lock.
  holds(meta, role, index) {
    return this.byHand(meta, role, index) || (this.frozen && isContinuous(meta, role, index));
  }

  // Puts every axis back to the automatic ranges (Reset axes), or the axis
  // column `index` of `role` only. The lock stays as it is.
  reset(meta = null, role = null, index = null) {
    if (meta && role) this.manual.delete(axisId(meta, role, index));
    else this.manual.clear();
  }

  // Turns the lock on or off. Off, no continuous axis keeps its range:
  // those set by hand go back to the automatic ranges too; the categorical
  // axes of result `meta` set by hand keep theirs, the lock being none of
  // theirs. Without `meta` (no figure), every axis set by hand is forgotten.
  setFrozen(on, meta = null) {
    this.frozen = on;
    if (on) return;
    if (!meta) {
      this.manual.clear();
      return;
    }
    for (const role of ["x", "y"]) {
      meta[`${role}_columns`].forEach((_, i) => {
        if (isContinuous(meta, role, i)) this.manual.delete(axisId(meta, role, i));
      });
    }
  }


  // Forgets the axes set by hand that a new result `meta` does not have,
  // so that a column taken off and put back, moved or put on another scale
  // starts over its automatic range.
  keepOf(meta) {
    const ids = new Set(["x", "y"].flatMap((role) => meta[`${role}_columns`].map((_, i) => axisId(meta, role, i))));
    for (const id of [...this.manual]) if (!ids.has(id)) this.manual.delete(id);
  }

  // Returns the ranges to aggregate for a new filter, from the ranges shown
  // (`shownRanges`) of result `meta`: the shown range of each axis kept
  // (`holds`), null for one to take the automatic range of the filter.
  filterRanges(meta, shown) {
    const pick = (role) => shown[role].map((range, i) => (this.holds(meta, role, i) ? range : null));
    return { x: pick("x"), y: pick("y") };
  }

  // Returns the view of a new result `meta` of an edit of the graph that
  // keeps the shown ranges (`shown`) of the drawn result `old`: an axis
  // column keeps its range while it stays in its role on the same
  // coordinates and is kept (`holds`); any other has its new automatic
  // range. Null when no range differs from the new automatic ones.
  carried(old, shown, meta) {
    const ranges = { x: [], y: [] };
    let zoomed = false;
    for (const role of ["x", "y"]) {
      meta[`${role}_columns`].forEach((column, i) => {
        const whole = meta[`${role}_ranges`][i];
        const j = old[`${role}_columns`].indexOf(column);
        const range = j < 0 ? null : shown[role][j];
        const keeps =
          range &&
          axisCoordinates(old, role, j) === axisCoordinates(meta, role, i) &&
          this.holds(old, role, j) &&
          !sameRange(range, whole);
        ranges[role].push(keeps ? range : whole);
        zoomed ||= Boolean(keeps);
      });
    }
    return zoomed ? { ranges, zoomed, box: null } : null;
  }

  // Returns the color scale that a view or an overview of result `meta`
  // keeps (`color_scale` of `/api/view` and `/api/overview`): that drawn,
  // under the lock; null for that of the filter.
  colorScale(meta) {
    return (this.frozen && meta?.color?.scale) || null;
  }

  // Returns the color scale that an edit of the graph keeps from the drawn
  // result `old` (`color_scale` of `/api/plot`): that drawn, under the lock,
  // while the color stays the same column of the same kind, cut the same
  // way (`bins`: `{n, by}`, null for a gradient); null for that of the
  // new graph's filter.
  carriedColorScale(old, column, bins) {
    if (!this.frozen || !old || !hasNumericColor(old) || old.color.column !== column) return null;
    const kind = bins ? "bins" : "gradient";
    if (old.color.kind !== kind) return null;
    if (bins && (old.color.bins?.n !== bins.n || old.color.bins?.by !== bins.by)) return null;
    return old.color.scale ?? null;
  }

  // The state, to go back to when a change of it fails (`restore`).
  snapshot() {
    return { frozen: this.frozen, manual: new Set(this.manual) };
  }

  restore(state) {
    this.frozen = state.frozen;
    this.manual = new Set(state.manual);
  }
}
