// Drop zones of the graph builder, laid out around the figure: Group X
// above the figure, Y left of it, Group Y right of it, X below it, Wrap in
// the corner right of Group X and above Group Y, and Symbol above Color
// beside it. They are outside the scrolled figure and name its axes. The
// zones edit the graph (`ddviz.server.encoding.Encoding`):
// - A column dropped on a zone takes that role, replacing the column there.
// - On X and Y, which hold several columns (the n-th axes), the zone is
//   split along its axis into a region per column. A column dropped in the
//   first INSERT_SHARE of the n-th region goes in before the n-th column,
//   in its last INSERT_SHARE after it, and in between it replaces it. X
//   runs left to right and Y top to bottom, as the panels of the axis
//   columns do. With two columns or more, each chip stands at the middle of
//   its region. The regions are the drawn axes of the columns where the
//   page gives them (`setAxes`): each axis's range, the gaps between them
//   split at their middle; a drop before the first goes in first, one past
//   the last goes in last. Else (one column, no drawn axes, or a direction
//   that scrolls) the zone is split into equal regions.
// - A placed column (a chip) dragged to another zone moves there; when that
//   zone holds a column, the two swap roles.
// - A chip's × button, or dropping it on the column list or outside every
//   zone, removes it.
// - Every role takes numeric and categorical columns alike: a categorical
//   column on X or Y is drawn in a band per level.
// - Wrap and the facets replace each other: a column placed on Wrap removes
//   those of Group X and Group Y, and one placed on either removes Wrap's.
//   Wrap is refused while X or Y has an n-th axis, and an n-th axis while
//   Wrap has a column.
// While dragging, a tip says what a drop would do, a line marks where a
// column would go in, and an outline marks the chip it would replace.
// An edit is a candidate until the page commits it (its graph is drawn, or
// needs no figure): a failed plot rolls the zones back to the last committed
// state, with the state the page derives from them (`related`), and without
// calling `onChange` again.

// Roles that hold a list of columns (the n-th axes after the first).
const AXES = ["x", "y"];
const LABELS = { x: "X", y: "Y", col: "Group X", row: "Group Y", wrap: "Wrap", color: "Color", symbol: "Symbol" };
// Roles that wrap replaces.
const FACETS = ["row", "col"];
// The part of an axis column's region, at either end along the axis, where
// a drop goes in beside the column instead of replacing it. A part of the
// region, not of the chip: the regions split the whole zone, so the bands
// do not depend on how wide the column names are.
const INSERT_SHARE = 0.25;
// Words for before and after a chip on each axis.
const SIDES = { x: ["左", "右"], y: ["上", "下"] };
// Pixels kept between two chips spread over their regions, and between a
// chip and the zone's edge (its border and padding).
const CHIP_GAP = 4;
const ZONE_INSET = 4;

// The column being dragged: `{name, numeric, temporal, placed}` from the
// column list, where `placed()` is called when a drop takes it, or
// `{name, numeric, temporal, from, index}` for a chip. A dragover cannot read
// the drag's data.
let dragged = null;

export function beginDrag(column) {
  dragged = column;
}

export function endDrag() {
  dragged = null;
}

// The column being dragged, for drop targets outside the builder (the filter pane).
export function draggedColumn() {
  return dragged;
}

// Returns `count` equal regions (`[start, end]` each) of a zone from
// `start` to `end` along its axis.
function equalRegions(count, start, end) {
  const size = (end - start) / count;
  return Array.from({ length: count }, (_, i) => [start + i * size, start + (i + 1) * size]);
}

// Returns the regions of axes drawn at `spans` (`[start, end]` each, in
// order along the axis): each axis's span, with the gap to the next split
// at its middle. They touch: the end of one is the start of the next.
function axisRegions(spans) {
  return spans.map(([start, end], i) => [
    i === 0 ? start : (spans[i - 1][1] + start) / 2,
    i === spans.length - 1 ? end : (end + spans[i + 1][0]) / 2,
  ]);
}

// Returns what a drop at `at` along the axis does over `regions` (touching,
// in order): one in the first INSERT_SHARE of the n-th region goes in at n,
// one in its last INSERT_SHARE goes in at n + 1, and one in between (both
// bounds included) replaces the column at n. One before the first region
// goes in first, one past the last goes in last. The end of a region and
// the start of the next go in at the same place.
function locate(regions, at) {
  if (at < regions[0][0]) return { index: 0, insert: true };
  if (at > regions.at(-1)[1]) return { index: regions.length, insert: true };
  const index = regions.findIndex(([, end]) => at <= end);
  const [start, end] = regions[index];
  const part = end > start ? (at - start) / (end - start) : 0.5;
  if (part < INSERT_SHARE) return { index, insert: true };
  if (part > 1 - INSERT_SHARE) return { index: index + 1, insert: true };
  return { index, insert: false };
}

export class Builder {
  // `root` holds the zones (`[data-role]`); `columnList` takes chips dropped
  // to remove them; `onChange` gets the graph after each edit. `related`
  // (`{save, load}`) saves and loads the page's state derived from the
  // graph, which a snapshot keeps beside it.
  constructor(root, columnList, onChange, related = null) {
    this.zones = [...root.querySelectorAll(".zone[data-role]")];
    this.onChange = onChange;
    this.related = related;
    this.encoding = { x: [], y: [], color: null, symbol: null, row: null, col: null, wrap: null, elements: ["points"] };
    // Whether each placed column is numeric, for the filter pane a chip is dragged to.
    this.numeric = new Map();
    // The temporal kind of each placed column (`ddviz.shared.temporal.KINDS`), or null.
    this.temporal = new Map();
    this.tip = document.getElementById("drop-tip");
    this.line = document.getElementById("drop-line");
    // The drawn axes of a role's columns (`setAxes`): none yet.
    this.axes = () => null;
    for (const zone of this.zones) this.attachZone(zone);
    // A chip dropped on the column list or outside every zone is removed.
    for (const target of [columnList, document]) {
      target.addEventListener("dragover", (event) => {
        if (!dragged?.from) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        this.showTip(`${LABELS[dragged.from]} から外す`);
      });
      target.addEventListener("drop", (event) => {
        if (!dragged?.from) return;
        event.preventDefault();
        event.stopPropagation();
        const { from, index } = dragged;
        this.endDrag();
        this.remove(from, index);
      });
    }
    document.addEventListener("dragend", () => this.endDrag());
    // Counts the edits, so that a snapshot tells whether an edit came after it.
    this.edits = 0;
    this.render();
    this.committed = this.snapshot();
  }

  // Returns the graph, the kinds of its columns and the related state as
  // they are now.
  snapshot() {
    return {
      encoding: structuredClone(this.encoding),
      numeric: new Map(this.numeric),
      temporal: new Map(this.temporal),
      related: this.related?.save() ?? null,
      edits: this.edits,
    };
  }

  // Makes `state` (a snapshot; by default the state now) the one a rollback
  // goes back to.
  commit(state = this.snapshot()) {
    this.committed = state;
  }

  // Whether an edit came after the committed state: it is still a candidate.
  uncommitted() {
    return this.edits !== this.committed.edits;
  }

  // Goes back to the committed state, the related state too, without
  // telling `onChange`: nothing is plotted again.
  rollback() {
    const { encoding, numeric, temporal, related } = this.committed;
    this.encoding = structuredClone(encoding);
    this.numeric = new Map(numeric);
    this.temporal = new Map(temporal);
    if (related !== null) this.related?.load(related);
    // The committed state again, under a new count: an older snapshot of
    // the same count is not taken for it.
    this.edits += 1;
    this.committed = { ...this.committed, edits: this.edits };
    this.render();
  }

  endDrag() {
    endDrag();
    this.showTip(null);
    this.mark(null, null);
    for (const zone of this.zones) zone.classList.remove("over");
  }

  // Marks where a drop on `zone` goes: a line where the column goes in, or
  // an outline around the chip it replaces; nothing for a null action.
  mark(zone, action) {
    for (const chip of document.querySelectorAll(".chip.target")) chip.classList.remove("target");
    this.line.hidden = true;
    if (!zone || !action || action.refused) return;
    const chips = [...zone.querySelectorAll(".chip")];
    if (!action.insert) {
      chips[action.index]?.classList.add("target");
      return;
    }
    if (!chips.length) return;
    const role = zone.dataset.role;
    const box = zone.getBoundingClientRect();
    const spans = chips.map((chip) => this.span(role, chip.getBoundingClientRect()));
    const at =
      action.index === 0
        ? spans[0][0] - 3
        : action.index === spans.length
          ? spans.at(-1)[1] + 3
          : (spans[action.index - 1][1] + spans[action.index][0]) / 2;
    const style = this.line.style;
    if (role === "x") {
      Object.assign(style, { left: `${at - 1}px`, top: `${box.top + 2}px`, width: "2px", height: `${box.height - 4}px` });
    } else {
      Object.assign(style, { left: `${box.left + 2}px`, top: `${at - 1}px`, width: `${box.width - 4}px`, height: "2px" });
    }
    this.line.hidden = false;
  }

  // Returns the start and end of a box along an axis role: x runs left to
  // right on the screen, y top to bottom.
  span(role, rect) {
    return role === "x" ? [rect.left, rect.right] : [rect.top, rect.bottom];
  }

  showTip(text) {
    this.tip.textContent = text ?? "";
    this.tip.hidden = !text;
  }

  // Returns the columns of a role as a list.
  placed(role) {
    const value = this.encoding[role];
    if (AXES.includes(role)) return value;
    return value === null ? [] : [value];
  }

  // Returns what a drop of the dragged column on `zone` at `event` does:
  // `{index, insert}` (go in at `index` of the role's columns, or replace
  // the column there) and its description, or `{refused}`.
  action(zone, event) {
    const role = zone.dataset.role;
    const column = dragged;
    if (role === "wrap" && AXES.some((axis) => this.placed(axis).length - (column.from === axis ? 1 : 0) > 1)) {
      return { refused: "第 n 軸があると Wrap に置けない" };
    }
    const placed = this.placed(role);
    const label = LABELS[role];
    let index = 0;
    let insert = false;
    if (AXES.includes(role) && placed.length > 0) {
      ({ index, insert } = this.position(zone, event));
    }
    if (insert && this.encoding.wrap !== null && column.from !== "wrap" && column.from !== role) {
      return { refused: "Wrap に列があると第 n 軸を置けない" };
    }
    if (insert) {
      // Where the column ends up once a chip of this role has left its place.
      const moved = column.from === role;
      const final = moved && index > column.index ? index - 1 : index;
      if (moved && final === column.index) return { refused: "同じ場所" };
      const others = moved ? placed.filter((_, i) => i !== column.index) : placed;
      const [before, after] = SIDES[role];
      const where = final < others.length ? `${others[final]} の${before}` : `${others.at(-1)} の${after}`;
      return { index, insert, text: `${label} の ${where}に第 ${final + 1} 軸として挿入` };
    }
    const target = placed[index];
    if (column.from === role && index === column.index) return { refused: "同じ場所" };
    let text;
    if (target === undefined) {
      text = `${label} に置く`;
    } else if (column.from === role) {
      text = `${label} の ${target} と順番を入れ替える`;
    } else if (column.from) {
      text = `${label} の ${target} と入れ替える`;
    } else {
      text = `${label} の ${target} を置き換える`;
    }
    return { index, insert, text: text + this.replacedNote(role, column.from) };
  }

  // Returns what a drop at the pointer on an axis zone does (`locate` over
  // the zone's regions): go in at `index`, or replace the column at `index`.
  position(zone, event) {
    const role = zone.dataset.role;
    const at = role === "x" ? event.clientX : event.clientY;
    return locate(this.regions(zone).regions, at);
  }

  // Sets where the columns of X and Y are drawn: `axes(role)` returns the
  // span (`[start, end]` in client coordinates along the axis) of each of
  // the role's columns, in their order, or null when the drawn figure does
  // not give them (no figure, a figure of other columns, or a direction that
  // scrolls). Call `layout` when they change.
  setAxes(axes) {
    this.axes = axes;
    this.layout();
  }

  // Returns the regions of an axis zone's columns (`{regions, spans}`):
  // those of the drawn axes, with their spans, for two columns or more when
  // the page gives them; else equal regions of the zone, without spans.
  regions(zone) {
    const role = zone.dataset.role;
    const count = this.placed(role).length;
    const spans = count > 1 ? this.axes(role) : null;
    if (spans?.length === count) return { regions: axisRegions(spans), spans };
    const [start, end] = this.span(role, zone.getBoundingClientRect());
    return { regions: equalRegions(count, start, end), spans: null };
  }

  // Puts each chip of X and Y, when they hold two columns or more, at the
  // middle of its region (of its drawn axis's span when there is one),
  // within the region and the zone; a long name is cut to fit. One chip is
  // centered by the zone's flex layout.
  layout() {
    for (const zone of this.zones) {
      const role = zone.dataset.role;
      if (!AXES.includes(role)) continue;
      const chips = [...zone.querySelectorAll(".chip")];
      const spread = chips.length > 1;
      zone.classList.toggle("spread", spread);
      if (!spread) continue;
      const box = zone.getBoundingClientRect();
      const [zoneStart, zoneEnd] = this.span(role, box);
      const { regions, spans } = this.regions(zone);
      chips.forEach((chip, i) => {
        const start = Math.max(regions[i][0] + (i > 0 ? CHIP_GAP / 2 : 0), zoneStart + ZONE_INSET);
        const end = Math.min(regions[i][1] - (i < chips.length - 1 ? CHIP_GAP / 2 : 0), zoneEnd - ZONE_INSET);
        chip.style.maxInlineSize = `${Math.max(end - start, 0)}px`;
        const size = role === "x" ? chip.offsetWidth : chip.offsetHeight;
        const middle = spans ? (spans[i][0] + spans[i][1]) / 2 : (regions[i][0] + regions[i][1]) / 2;
        // Its start in client coordinates, within the room left for it.
        const from = Math.min(Math.max(middle - size / 2, start), Math.max(end - size, start));
        if (role === "x") {
          chip.style.left = `${from - box.left - zone.clientLeft}px`;
        } else {
          // The rotated zone (app.css) turns its box upside down.
          chip.style.top = `${box.height - size - (from - box.top) - zone.clientTop}px`;
        }
      });
    }
  }

  // Returns what a drop on `role` removes besides, as Wrap and the facets
  // replace each other; "" for nothing.
  replacedNote(role, from) {
    const others = role === "wrap" ? FACETS : FACETS.includes(role) ? ["wrap"] : [];
    const removed = others.filter((r) => r !== from && this.encoding[r] !== null);
    if (!removed.length) return "";
    return `（${removed.map((r) => LABELS[r]).join(" と ")} の列を外す）`;
  }

  attachZone(zone) {
    zone.addEventListener("dragover", (event) => {
      if (!dragged) return;
      event.preventDefault();
      event.stopPropagation();
      const action = this.action(zone, event);
      zone.classList.toggle("over", !action.refused);
      event.dataTransfer.dropEffect = action.refused ? "none" : dragged.from ? "move" : "copy";
      this.showTip(action.refused ?? action.text);
      this.mark(zone, action);
    });
    zone.addEventListener("dragleave", (event) => {
      if (zone.contains(event.relatedTarget)) return;
      zone.classList.remove("over");
      this.mark(null, null);
    });
    zone.addEventListener("drop", (event) => {
      if (!dragged) return;
      event.preventDefault();
      event.stopPropagation();
      const action = this.action(zone, event);
      const column = dragged;
      this.endDrag();
      if (action.refused) return;
      this.place(zone.dataset.role, column, action);
      column.placed?.();
    });
  }

  // Places `column` on `role` as `action` says, swapping with a chip's role.
  // Within one role, a chip goes in at its new place or swaps with the
  // chip it replaces.
  place(role, column, { index, insert }) {
    this.numeric.set(column.name, column.numeric);
    this.temporal.set(column.name, column.temporal ?? null);
    const list = this.placed(role).slice();
    if (column.from === role) {
      if (insert) {
        list.splice(index, 0, column.name);
        list.splice(index > column.index ? column.index : column.index + 1, 1);
      } else {
        [list[index], list[column.index]] = [list[column.index], list[index]];
      }
      this.setRole(role, list);
      return this.changed();
    }
    const displaced = insert ? undefined : list[index];
    if (insert) list.splice(index, 0, column.name);
    else list[index] = column.name;
    this.setRole(role, list);
    if (column.from) {
      const source = this.placed(column.from).slice();
      if (displaced !== undefined) source[column.index] = displaced;
      else source.splice(column.index, 1);
      this.setRole(column.from, source);
    }
    if (role === "wrap") for (const facet of FACETS) this.encoding[facet] = null;
    if (FACETS.includes(role)) this.encoding.wrap = null;
    this.changed();
  }

  // Sets the elements drawn (`ddviz.server.encoding.ELEMENTS`), in their order.
  setElements(elements) {
    this.encoding.elements = elements;
    this.changed();
  }

  remove(role, index) {
    const list = this.placed(role).slice();
    list.splice(index, 1);
    this.setRole(role, list);
    this.changed();
  }

  setRole(role, list) {
    this.encoding[role] = AXES.includes(role) ? list : (list[0] ?? null);
  }

  changed() {
    this.edits += 1;
    this.render();
    this.onChange(structuredClone(this.encoding));
  }

  render() {
    for (const zone of this.zones) {
      const role = zone.dataset.role;
      const placed = this.placed(role);
      const chips = placed.map((name, index) => this.chip(role, name, index));
      const label = document.createElement("span");
      label.className = "zone-label";
      label.textContent = LABELS[role];
      zone.replaceChildren(label, ...chips);
      zone.classList.toggle("filled", placed.length > 0);
    }
    this.layout();
  }

  chip(role, name, index) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.draggable = true;
    chip.title = `${name}。ドラッグで別の役割へ移す。フィルタ欄に落とすとフィルタに加える（チップは残る）。× か、枠の外に落とすと外す`;
    const text = document.createElement("span");
    text.className = "chip-name";
    // A duration is drawn as seconds.
    text.textContent = this.temporal.get(name) === "duration" ? `${name} (s)` : name;
    const close = document.createElement("button");
    close.className = "chip-remove";
    close.type = "button";
    close.textContent = "×";
    close.title = "外す";
    close.addEventListener("click", () => this.remove(role, index));
    chip.append(text, close);
    chip.addEventListener("dragstart", (event) => {
      event.stopPropagation();
      beginDrag({ name, numeric: this.numeric.get(name), temporal: this.temporal.get(name), from: role, index });
      event.dataTransfer.setData("text/plain", name);
      // A move to a role or out of the builder; a copy to the filter pane, which keeps the chip.
      event.dataTransfer.effectAllowed = "copyMove";
    });
    return chip;
  }
}
