// The settings of the axis columns kept while the page is open, and the
// axes' right-click menu and double click.
import {
  axisKind,
  decorationUpdate,
  dialogKind,
  emptySettings,
  hasAngle,
  isEmpty,
  openAxisDialog,
} from "./axisdialog.js";
import { axisAt, labelAt, yMarginAt } from "./axishit.js";
import { AxisDirections, ascending, oriented } from "./axisdirection.js";
import { axisKey } from "./axiskey.js";
import { openAxisMenu } from "./axismenu.js";
import { AxisScales } from "./axisscale.js";
import { sameOrder, sameRange } from "./ranges.js";
import { linearRange, plotlyRange } from "./temporal.js";

// Returns the drawing settings of the axes (`AxisControls.settings`) of the
// dialog's settings and the angles (Maps by column and by role and column)
// and the log and reversed columns (`{x, y}` of Sets), as JSON values sorted.
function axisSettings(dialog, angles, logs, reversed) {
  const sorted = (map) => [...map].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const columns = (sets) => ({ x: [...sets.x].sort(), y: [...sets.y].sort() });
  return {
    dialog: structuredClone(sorted(dialog)),
    angles: sorted(angles),
    logs: columns(logs),
    reversed: columns(reversed),
  };
}

// Returns the drawing settings of the axes `state` changed by `edit`, which
// gets them as `{dialog, angles, logs, reversed}` of Maps and Sets.
function editAxisSettings(state, edit) {
  const parts = {
    dialog: new Map(structuredClone(state.dialog)),
    angles: new Map(state.angles),
    logs: { x: new Set(state.logs.x), y: new Set(state.logs.y) },
    reversed: { x: new Set(state.reversed.x), y: new Set(state.reversed.y) },
  };
  edit(parts);
  return axisSettings(parts.dialog, parts.angles, parts.logs, parts.reversed);
}

// The settings of the axis columns kept while the page is open: the dialog's
// ticks, labels and reference lines, the angle of the tick labels, the log
// scale and the direction; and the axes' right-click menu and double click.
export class AxisControls {
  // The settings of the axis columns with a dialog (`axisdialog.js`: numeric
  // and temporal), by column name: their ticks, the format of their labels
  // and reference lines, kept for every graph that draws the column on such
  // an axis (a duration's on a linear one). The range set
  // in the dialog is a view, as a zoom's: going back to the overview drops it.
  #settings = new Map();
  // The angle of the major tick labels of each x and y column (`hasAngle`:
  // linear numeric and categorical axes), in degrees, by role and column: a
  // column on both x and y has one of each. Every panel of the role's
  // column draws it; it stays through zooms and graphs until the page
  // reloads. A column without one has plotly's automatic labels.
  #angles = new Map();
  // The last left press on an axis with a dialog (`attach`), for a double click.
  #press = null;
  // The scale of each x and y column while the input is open (`axisscale.js`).
  scales = new AxisScales();
  // The direction of each x and y column while the input is open (`axisdirection.js`).
  directions = new AxisDirections();
  settingsOf = (column) => this.#settings.get(column);
  angleOf = (role, column) => this.#angles.get(`${role}:${column}`) ?? null;

  // `current()` is the meta drawn (or null); `relayoutOwn(update)` relayouts
  // the figure as the page's own; `plotted()` tells whether a graph is
  // plotted, `replot()` plots it again (`plot()`'s result); `followMargin(grow)`
  // measures the margin again; `openPlotMenu(event)` opens the plot's menu;
  // `changed(edit)` is called after the dialog's settings, an angle or a
  // direction changed, which are drawn without a plot: `edit(state)` returns
  // the axes' drawing settings `state` (`settings`) with that change alone.
  // `marginTargets` are the elements of the axes' left margin outside the
  // plot (`hit`): the gap between the y zone and the plot area is the
  // builder's, the stage's or the scroller's.
  constructor({
    gd,
    builderRoot,
    yZone,
    sticky,
    marginTargets,
    current,
    hideHover,
    relayoutOwn,
    plotted,
    replot,
    followMargin,
    openPlotMenu,
    changed = () => {},
  }) {
    this.gd = gd;
    this.builderRoot = builderRoot;
    this.yZone = yZone;
    this.sticky = sticky;
    this.marginTargets = marginTargets;
    this.current = current;
    this.hideHover = hideHover;
    this.relayoutOwn = relayoutOwn;
    this.plotted = plotted;
    this.replot = replot;
    this.followMargin = followMargin;
    this.openPlotMenu = openPlotMenu;
    this.changed = changed;
  }

  // Returns the settings of the axis columns as JSON values, for the drawing
  // settings of undo and redo (`history.js`): the dialog's and the angles by
  // column, and the log and reversed columns of each role.
  settings() {
    return axisSettings(this.#settings, this.#angles, this.scales.logs, this.directions.reversed);
  }

  // Sets the settings of the axis columns from `state` (`settings`), without
  // drawing them: the plot of the graph does.
  applySettings(state) {
    this.#settings = new Map(structuredClone(state.dialog));
    this.#angles = new Map(state.angles);
    this.scales.clear();
    this.directions.clear();
    for (const axis of ["x", "y"]) {
      for (const column of state.logs[axis]) this.scales.set(axis, column, true);
      for (const column of state.reversed[axis]) this.directions.set(axis, column, true);
    }
  }

  // The angle drawn on the axis column `index` of `role` of `meta`, or null.
  angleOn(meta, role, index) {
    return hasAngle(meta, role, index) ? this.angleOf(role, meta[`${role}_columns`][index]) : null;
  }

  // Returns `layout` with the axis ranges (ascending) given the direction of
  // their columns (`axisdirection.js`).
  orientedLayout(layout, meta) {
    const out = { ...layout };
    for (const [id, reversed] of Object.entries(this.directions.byAxis(meta))) {
      const key = axisKey(id);
      if (out[key]?.range) out[key] = { ...out[key], range: oriented(out[key].range, reversed) };
    }
    return out;
  }

  // Returns the axis column whose tick labels are under a pointer event, of
  // any kind, as `{axis, index}` (with `strip: true` in a strip of a grid that
  // scrolls), or null (`under`). A y axis also takes
  // its whole left margin, from the y zone's right edge (the zone keeps its
  // chips and drops) to the plot area of the leftmost panel at that height:
  // in a grid that scrolls, the left strip and the gap left of it
  // (`sticky.js`), which the strip shows the leftmost panels' labels of
  // whatever the scroll; otherwise the figure's margin and the gap
  // (`yMarginAt`). Other UI over the margin (the mode bar, the table) keeps
  // its own.
  hit(event) {
    const { clientX, clientY, target } = event;
    const gd = this.gd;
    const current = this.current();
    const open = gd.contains(target) ? !target.closest(".modebar") : this.marginTargets.includes(target);
    if (!open) return null;
    const from = this.yZone.getBoundingClientRect().right;
    const strip = this.sticky.axisAt(clientX, clientY, from);
    if (strip) return { axis: strip.axis, index: strip.axis === "x" ? strip.panel.x : strip.panel.y, strip: true };
    if (this.sticky.shown) return axisAt(event, gd, current);
    return (
      axisAt(event, gd, current) ??
      yMarginAt(clientX, clientY, gd, current, from) ??
      labelAt(clientX, clientY, gd, current)
    );
  }

  // Returns the axis column with a dialog (`dialogKind`) whose tick labels are under a pointer
  // event, as `{axis, index}`, or null: in the strips of a grid that scrolls
  // (`sticky.js`), which let the pointer through to the panels, or on plotly's
  // own labels.
  under(event) {
    const hit = this.hit(event);
    return hit && dialogKind(this.current(), hit.axis, hit.index) ? hit : null;
  }

  // Opens the menu of the axis column `hit` (`hit()`) of the result drawn.
  openMenuOf(event, { axis, index }) {
    const meta = this.current();
    const column = meta[`${axis}_columns`][index];
    openAxisMenu(event, {
      axis,
      column,
      log: meta[`${axis}_log`][index],
      loggable: meta[`${axis}_loggable`][index],
      onLog: (log) => this.setLog(meta, axis, column, log),
      reversed: this.directions.isReversed(axis, column),
      onReverse: (reversed) => this.setReversed(axis, column, reversed),
    });
  }

  // Opens the dialog of the axis column `index` of `axis` ("x" or "y") of the drawn result.
  open({ axis, index }) {
    const current = this.current();
    const column = current[`${axis}_columns`][index];
    const full = this.gd._fullLayout[axisKey(current[`${axis}_axes`][index])];
    openAxisDialog({
      title: `${axis.toUpperCase()} 軸: ${column}`,
      kind: dialogKind(current, axis, index),
      range: ascending(linearRange(full)),
      settings: this.settingsOf(column) ?? emptySettings(),
      // plotly's interval of the ticks drawn, for the unit of a temporal one.
      drawn: full.dtick,
      angle: this.angleOf(axis, column),
      onApply: (settings, picked, angle) => this.apply(axis, column, settings, picked, angle),
    });
  }

  // Keeps the settings of an axis column and draws them, with the range
  // `picked` when it differs from the shown one: the view is aggregated
  // again, as after a zoom. The drawn result may have changed since the
  // dialog opened: the range goes to the column's axis, if it still has a
  // dialog (`axisKind`), in linear units (milliseconds on a date axis).
  // The angle of the labels (null for plotly's own; undefined from a dialog
  // without one) is the column's in that role. A categorical axis has no
  // settings nor range (null): only its angle changes.
  async apply(axis, column, settings, picked, angle) {
    if (settings) {
      if (isEmpty(settings)) this.#settings.delete(column);
      else this.#settings.set(column, settings);
    }
    if (angle === null) this.#angles.delete(`${axis}:${column}`);
    else if (angle !== undefined) this.#angles.set(`${axis}:${column}`, angle);
    this.changed((state) =>
      editAxisSettings(state, ({ dialog, angles }) => {
        if (settings) {
          if (isEmpty(settings)) dialog.delete(column);
          else dialog.set(column, structuredClone(settings));
        }
        if (angle === null) angles.delete(`${axis}:${column}`);
        else if (angle !== undefined) angles.set(`${axis}:${column}`, angle);
      }),
    );
    const gd = this.gd;
    if (!this.current() || !gd._fullLayout) return;
    const meta = this.current();
    await this.relayoutOwn(decorationUpdate(meta, this.settingsOf, this.angleOf));
    if (meta !== this.current()) return;
    const index = meta[`${axis}_columns`].indexOf(column);
    const key = index < 0 || !axisKind(meta, axis, index) ? null : axisKey(meta[`${axis}_axes`][index]);
    const full = key && gd._fullLayout[key];
    if (!full || !picked || sameRange(ascending(linearRange(full)), picked)) {
      // The ticks' labels changed at the same range.
      this.followMargin(false);
      return;
    }
    // A new range is a view (`onRelayout`), which measures the margin.
    const range = oriented(picked, this.directions.isReversed(axis, column));
    await Plotly.relayout(gd, { [`${key}.range`]: plotlyRange(full, range) });
  }

  // Reverses the axes of a column, or puts them back, on the result drawn: only
  // their direction changes, at the shown range. Nothing is aggregated or
  // asked of the server, and the selection stays, unless the labels need
  // another left margin (`followMargin`).
  async setReversed(axis, column, reversed) {
    this.directions.set(axis, column, reversed);
    this.changed((state) =>
      editAxisSettings(state, ({ reversed: columns }) => {
        if (reversed) columns[axis].add(column);
        else columns[axis].delete(column);
      }),
    );
    const gd = this.gd;
    if (!this.current() || !gd._fullLayout) return;
    const meta = this.current();
    const update = {};
    meta.panels.forEach((panel) => {
      if (meta[`${axis}_columns`][panel[axis]] !== column) return;
      const key = axisKey(panel[`${axis}axis`]);
      const full = gd._fullLayout[key];
      if (!full) return;
      const range = oriented(linearRange(full), reversed);
      if (!sameOrder(linearRange(full), range)) update[`${key}.range`] = plotlyRange(full, range);
    });
    if (!Object.keys(update).length) return;
    this.hideHover();
    await this.relayoutOwn(update);
    if (meta === this.current()) this.followMargin(false);
  }

  // Puts an axis column of the drawn result `meta` on a log or a linear axis:
  // the graph is plotted again, with the column's axis over its whole range
  // (its coordinates changed) and the other columns' axes at their shown
  // ranges (`carriedView`). A refusal (no positive value) keeps the drawn
  // plot, its selection and the scale.
  async setLog(meta, axis, column, log) {
    if (meta !== this.current() || !this.plotted()) return;
    this.scales.set(axis, column, log);
    if ((await this.replot()) === "refused") this.scales.set(axis, column, !log);
  }

  // Listens to the right clicks on the axes, which open their menu, and to
  // the double clicks on the axes with a dialog, which open it.
  attach() {
    const { gd, builderRoot } = this;
    gd.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      if (!gd._fullLayout || event.target.closest(".modebar")) return;
      this.hideHover();
      // On the tick labels of an axis, the menu of its column (`axismenu.js`).
      const hit = this.current() && this.hit(event);
      if (hit) {
        this.openMenuOf(event, hit);
        return;
      }
      this.openPlotMenu(event);
    });
    // The left margin of the y axes reaches out of the plot, over the gap
    // between the plot area and the y zone (`hit`): a right click there
    // opens the axis's menu too. One on the plot is the handler's above.
    builderRoot.addEventListener("contextmenu", (event) => {
      if (gd.contains(event.target)) return;
      const hit = this.current() && gd._fullLayout && this.hit(event);
      if (!hit) return;
      event.preventDefault();
      this.hideHover();
      this.openMenuOf(event, hit);
    });
    // A double click on the tick labels of an axis with a dialog (`dialogKind`) opens it
    // instead of plotly's autorange of that axis. plotly counts the presses
    // itself, within its `doubleClickDelay`, so the second press does not reach
    // it. The wait here is plotly's own, read on each press, so that every pair
    // plotly would count as a double click opens the dialog, whatever plotly's
    // version or config. The presses are taken on the builder, before plotly's
    // handlers, as the axes' left margin reaches out of the plot (`hit`).
    builderRoot.addEventListener(
      "mousedown",
      (event) => {
        if (event.button !== 0) return;
        const hit = this.current() && gd._fullLayout ? this.under(event) : null;
        const last = this.#press;
        this.#press = null;
        if (!hit) return;
        // The strips let the pointer through to the plot area below: plotly
        // would take the first press as one on the plot, which clears a Box
        // Select's selection. A press on a strip's numeric axis is the axis's.
        if (hit.strip) event.stopPropagation();
        const near = last && Math.hypot(event.clientX - last.x, event.clientY - last.y) <= 4;
        if (near && last.axis === hit.axis && last.index === hit.index && event.timeStamp - last.time < gd._context.doubleClickDelay) {
          event.stopPropagation();
          event.preventDefault();
          this.hideHover();
          this.open(hit);
          return;
        }
        this.#press = { ...hit, x: event.clientX, y: event.clientY, time: event.timeStamp };
      },
      { capture: true },
    );
  }
}
