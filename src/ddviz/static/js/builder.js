// Drop zones of the graph builder, laid out around the figure: Group X
// above the figure, Y left of it, Group Y right of it, X below it, Wrap in
// the corner right of Group X and above Group Y, and Color and Overlay
// beside it. They are outside the scrolled figure and name its axes. The
// zones edit the graph (`ddviz.server.encoding.Encoding`):
// - A column dropped on a zone takes that role, replacing the column there.
// - On X and Y, which hold several columns (the n-th axes), a column dropped
//   on the leading quarter of a chip goes in before it, on the trailing
//   quarter after it, and on its middle replaces it; dropped between chips
//   or beside them, it goes in there. X runs left to right and Y top to
//   bottom, as the panels of the axis columns do.
// - A placed column (a chip) dragged to another zone moves there; when that
//   zone holds a column, the two swap roles.
// - A chip's × button, or dropping it on the column list or outside every
//   zone, removes it.
// - Wrap and the facets replace each other: a column placed on Wrap removes
//   those of Group X and Group Y, and one placed on either removes Wrap's.
//   Wrap is refused while X or Y has an n-th axis, and an n-th axis while
//   Wrap has a column.
// While dragging, a tip says what a drop would do, a line marks where a
// column would go in, and an outline marks the chip it would replace.

// Roles that hold a list of columns (the n-th axes after the first).
const AXES = ["x", "y"];
const LABELS = { x: "X", y: "Y", col: "Group X", row: "Group Y", wrap: "Wrap", color: "Color", overlay: "Overlay" };
// Roles that wrap replaces.
const FACETS = ["row", "col"];
// Roles placed but not drawn yet.
const UNDRAWN_NOTE = "（まだ描かない）";
// Part of a chip at each end, along its axis, where a drop goes in beside
// it instead of replacing it.
const INSERT_EDGE = 0.25;
// Words for before and after a chip on each axis.
const SIDES = { x: ["左", "右"], y: ["上", "下"] };

// The column being dragged: `{name, numeric}` from the column list, plus
// `from` and `index` for a chip. A dragover cannot read the drag's data.
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

export class Builder {
  // `root` holds the zones (`[data-role]`); `columnList` takes chips dropped
  // to remove them; `onChange` gets the graph after each edit. `extras` maps
  // a role to an element shown after its chips while it has a column.
  constructor(root, columnList, onChange, extras = {}) {
    this.zones = [...root.querySelectorAll(".zone[data-role]")];
    this.onChange = onChange;
    this.extras = extras;
    this.encoding = { x: [], y: [], color: null, overlay: null, row: null, col: null, wrap: null };
    // Whether each placed column is numeric, for moves between roles.
    this.numeric = new Map();
    this.tip = document.getElementById("drop-tip");
    this.line = document.getElementById("drop-line");
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
    if (AXES.includes(role) && !column.numeric) {
      return { refused: `${LABELS[role]} には数値の列だけを置ける` };
    }
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
      text = this.canTake(column.from, target)
        ? `${label} の ${target} と入れ替える`
        : `${label} の ${target} を置き換える（${target} は ${LABELS[column.from]} に置けないので外す）`;
    } else {
      text = `${label} の ${target} を置き換える`;
    }
    return { index, insert, text: text + this.replacedNote(role, column.from) };
  }

  // Returns where on an axis zone's chips the pointer is: in the middle of
  // the chip at `index` (replace it), or the place `index` to go in at.
  position(zone, event) {
    const role = zone.dataset.role;
    const at = role === "x" ? event.clientX : event.clientY;
    const spans = [...zone.querySelectorAll(".chip")].map((chip) => this.span(role, chip.getBoundingClientRect()));
    for (const [i, [start, end]] of spans.entries()) {
      if (at < start || at > end) continue;
      const part = (at - start) / (end - start);
      if (part < INSERT_EDGE) return { index: i, insert: true };
      if (part > 1 - INSERT_EDGE) return { index: i + 1, insert: true };
      return { index: i, insert: false };
    }
    return { index: spans.filter(([start, end]) => (start + end) / 2 < at).length, insert: true };
  }

  // Returns what a drop on `role` removes besides, as Wrap and the facets
  // replace each other; "" for nothing.
  replacedNote(role, from) {
    const others = role === "wrap" ? FACETS : FACETS.includes(role) ? ["wrap"] : [];
    const removed = others.filter((r) => r !== from && this.encoding[r] !== null);
    if (!removed.length) return "";
    return `（${removed.map((r) => LABELS[r]).join(" と ")} の列を外す）`;
  }

  // Whether `column` (a placed one) may take `role`.
  canTake(role, column) {
    return !AXES.includes(role) || this.numeric.get(column);
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
      if (!action.refused) this.place(zone.dataset.role, column, action);
    });
  }

  // Places `column` on `role` as `action` says, swapping with a chip's role.
  // Within one role, a chip goes in at its new place or swaps with the
  // chip it replaces.
  place(role, column, { index, insert }) {
    this.numeric.set(column.name, column.numeric);
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
      if (displaced !== undefined && this.canTake(column.from, displaced)) source[column.index] = displaced;
      else source.splice(column.index, 1);
      this.setRole(column.from, source);
    }
    if (role === "wrap") for (const facet of FACETS) this.encoding[facet] = null;
    if (FACETS.includes(role)) this.encoding.wrap = null;
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
      label.textContent = LABELS[role] + (role === "overlay" ? UNDRAWN_NOTE : "");
      const extra = placed.length && this.extras[role] ? [this.extras[role]] : [];
      zone.replaceChildren(label, ...chips, ...extra);
      zone.classList.toggle("filled", placed.length > 0);
    }
  }

  chip(role, name, index) {
    const chip = document.createElement("span");
    const undrawn = role === "overlay";
    chip.className = "chip" + (undrawn ? " undrawn" : "");
    chip.draggable = true;
    chip.title = (undrawn ? `${name}${UNDRAWN_NOTE}。` : `${name}。`) + "ドラッグで別の役割へ移す。× か、枠の外に落とすと外す";
    const text = document.createElement("span");
    text.className = "chip-name";
    text.textContent = name;
    const close = document.createElement("button");
    close.className = "chip-remove";
    close.type = "button";
    close.textContent = "×";
    close.title = "外す";
    close.addEventListener("click", () => this.remove(role, index));
    chip.append(text, close);
    chip.addEventListener("dragstart", (event) => {
      event.stopPropagation();
      beginDrag({ name, numeric: this.numeric.get(name), from: role, index });
      event.dataTransfer.setData("text/plain", name);
      event.dataTransfer.effectAllowed = "move";
    });
    return chip;
  }
}
