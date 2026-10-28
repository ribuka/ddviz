// Drop zones of the graph builder, laid out around the figure: Group X
// above the figure, Y left of it, Group Y right of it, X below it, and Color
// and Overlay beside it. They are outside the scrolled figure and name its
// axes. The zones edit the graph (`ddviz.encoding.Encoding`):
// - A column dropped on a zone takes that role, replacing the column there.
// - On X and Y, a column dropped beside the placed ones adds an n-th axis.
// - A placed column (a chip) dragged to another zone moves there; when that
//   zone holds a column, the two swap roles.
// - A chip's × button, or dropping it on the column list or outside every
//   zone, removes it.
// While dragging, a tip says what a drop would do.

// Roles that hold a list of columns (the n-th axes after the first).
const AXES = ["x", "y"];
const LABELS = { x: "X", y: "Y", col: "Group X", row: "Group Y", color: "Color", overlay: "Overlay" };
// Roles placed but not drawn yet.
const UNDRAWN_NOTE = "（まだ描かない）";

// The column being dragged: `{name, numeric}` from the column list, plus
// `from` and `index` for a chip. A dragover cannot read the drag's data.
let dragged = null;

export function beginDrag(column) {
  dragged = column;
}

export function endDrag() {
  dragged = null;
}

export class Builder {
  // `root` holds the zones (`[data-role]`); `columnList` takes chips dropped
  // to remove them; `onChange` gets the graph after each edit.
  constructor(root, columnList, onChange) {
    this.zones = [...root.querySelectorAll(".zone[data-role]")];
    this.onChange = onChange;
    this.encoding = { x: [], y: [], color: null, overlay: null, row: null, col: null };
    // Whether each placed column is numeric, for moves between roles.
    this.numeric = new Map();
    this.tip = document.getElementById("drop-tip");
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
    for (const zone of this.zones) zone.classList.remove("over");
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
  // `{index, add}` (replace the column at `index`, or add an n-th axis) and
  // its description, or `{refused}`.
  action(zone, event) {
    const role = zone.dataset.role;
    const column = dragged;
    if (AXES.includes(role) && !column.numeric) {
      return { refused: `${LABELS[role]} には数値の列だけを置ける` };
    }
    const placed = this.placed(role);
    const chips = [...zone.querySelectorAll(".chip")];
    let index = chips.findIndex((chip) => {
      const r = chip.getBoundingClientRect();
      return event.clientX >= r.left && event.clientX <= r.right && event.clientY >= r.top && event.clientY <= r.bottom;
    });
    const add = AXES.includes(role) && placed.length > 0 && index === -1;
    if (index === -1) index = add ? placed.length : 0;
    if (column.from === role) {
      if (add || index === column.index) return { refused: "同じ場所" };
    }
    const label = LABELS[role];
    const target = placed[index];
    let text;
    if (add) {
      text = `${label} に第 ${placed.length + 1} 軸として足す${UNDRAWN_NOTE}`;
    } else if (target === undefined) {
      text = `${label} に置く`;
    } else if (column.from && column.from !== role) {
      text = this.canTake(column.from, target)
        ? `${label} の ${target} と入れ替える`
        : `${label} の ${target} を置き換える（${target} は ${LABELS[column.from]} に置けないので外す）`;
    } else {
      text = `${label} の ${target} を置き換える`;
    }
    return { index, add, text };
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
    });
    zone.addEventListener("dragleave", (event) => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove("over");
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
  place(role, column, { index, add }) {
    this.numeric.set(column.name, column.numeric);
    const list = this.placed(role).slice();
    if (column.from === role) {
      list.splice(column.index, 1);
      list.splice(Math.min(index, list.length), 0, column.name);
      this.setRole(role, list);
      return this.changed();
    }
    const displaced = add ? undefined : list[index];
    if (add) list.push(column.name);
    else list[index] = column.name;
    this.setRole(role, list);
    if (column.from) {
      const source = this.placed(column.from).slice();
      if (displaced !== undefined && this.canTake(column.from, displaced)) source[column.index] = displaced;
      else source.splice(column.index, 1);
      this.setRole(column.from, source);
    }
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
      zone.replaceChildren(label, ...chips);
      zone.classList.toggle("filled", placed.length > 0);
    }
  }

  chip(role, name, index) {
    const chip = document.createElement("span");
    const undrawn = role === "overlay" || index > 0;
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
