// The dialog of the join (docs/spec.md, "横の結合"): it reads the table to
// join (`POST /api/join/source`), takes the kind and, for a join by keys,
// the pairs of keys picked from the columns of both tables, the columns to
// add (all, maybe but those named like the input's, or those picked), and
// joins (`POST /api/join`). The page (app.js) opens it from the window's
// `Data → 結合…` or Ctrl+J, and takes the answer of a join.
// A refused read or join tells the server's reason in the dialog, which
// stays open; Esc and キャンセル close it without joining, but not while it
// joins. It starts empty each time it opens: the table the server read stays
// there until the next read.
import { castRows, castsText } from "./casts.js";
import { plainEnter } from "./keys.js";
import { errorText } from "./notice.js";
import { placeUnder } from "./popup.js";

const SEARCH_DELAY_MS = 150;

// Told by Ctrl+J after the join (`app.js`).
export const JOIN_ONCE = "結合は 1 回だけです。やり直すには File → New で開き直してください。";

// The paths of the field: one a line, without the blank lines and the
// spaces around them.
export function parsePaths(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

// The table read, under the paths: its files, rows and columns.
export function sourceText(found) {
  return `${found.files.toLocaleString()} ファイル・${found.rows.toLocaleString()} 行・${found.columns.toLocaleString()} 列`;
}

// The toast of a join of `kind` that answered `answer` (`{added, rows,
// matched, skipped}`): the columns added, by keys the share of the input's
// rows that matched, to one decimal, and the columns left out by name.
export function joinedText(answer, kind) {
  let text = `${answer.added.length.toLocaleString()} 列を結合しました。`;
  if (kind === "key") {
    const share = answer.rows > 0 ? (answer.matched / answer.rows) * 100 : 0;
    text += `元の表の ${share.toFixed(1)}% の行が結合できました。`;
  }
  const skipped = answer.skipped?.length ?? 0;
  if (skipped > 0) text += `元の表と同じ名前の ${skipped.toLocaleString()} 列は足しませんでした。`;
  return text;
}

// Whether `結合` may be pressed: a table read; by keys, both columns of
// every pair picked (`keys` of `{left, right}`, null while not picked); and,
// for the columns picked (`columns` of the names, null while not picked;
// null for all the columns), at least one, each picked.
export function joinReady(read, kind, keys, columns = null) {
  if (!read) return false;
  if (columns !== null && (columns.length === 0 || columns.includes(null))) return false;
  if (kind === "rows") return true;
  return keys.length > 0 && keys.every((key) => key.left !== null && key.right !== null);
}

function element(tag, className, text) {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text !== undefined) made.textContent = text;
  return made;
}

function button(className, text, onClick) {
  const made = element("button", className, text);
  made.type = "button";
  made.addEventListener("click", onClick);
  return made;
}

// Posts `body` as JSON to `url`; resolves to `{ok, status, text}`, with the
// error's message as the text when the request did not reach the server.
async function post(url, body) {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { ok: response.ok, status: response.status, text: await response.text() };
  } catch (error) {
    return { ok: false, status: undefined, text: error?.message ?? String(error) };
  }
}

// A field of a column's name with the search of the columns (`url`, `GET`
// with `q`, as the column list searches): only a name picked from the
// candidates is taken (`value`); text typed stays unconfirmed (null) until
// one is picked. `onPick(name)` is called when one is, `onEdit()` when the
// text is typed.
export class ColumnField {
  constructor(url, placeholder, { onPick = () => {}, onEdit = () => {} } = {}) {
    this.url = url;
    this.value = null;
    this.onPick = onPick;
    this.onEdit = onEdit;
    this.list = null;
    this.active = -1;
    this.timer = null;
    // Generation of the latest search, so that an older answer is dropped.
    this.generation = 0;
    const input = element("input", "join-key-input");
    Object.assign(input, { type: "text", placeholder, spellcheck: false, autocomplete: "off" });
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    this.input = input;
    input.addEventListener("input", () => {
      this.value = null;
      input.classList.remove("confirmed");
      this.onEdit();
      this.searchSoon();
    });
    input.addEventListener("focus", () => this.search());
    input.addEventListener("blur", () => this.close());
    input.addEventListener("keydown", (event) => this.key(event));
  }

  set disabled(on) {
    this.input.disabled = on;
    if (on) this.close();
  }

  // Takes `name` as picked (null empties the field).
  set(name) {
    this.value = name;
    this.input.value = name ?? "";
    this.input.classList.toggle("confirmed", name !== null);
  }

  pick(name) {
    this.set(name);
    this.close();
    this.onPick(name);
  }

  searchSoon() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.search(), SEARCH_DELAY_MS);
  }

  async search() {
    clearTimeout(this.timer);
    const mine = ++this.generation;
    let columns = null;
    try {
      // The column of the name typed comes first: the limit of the list
      // never leaves it out.
      const query = new URLSearchParams({ q: this.input.value, exact: this.input.value });
      const response = await fetch(`${this.url}?${query}`);
      if (response.ok) columns = (await response.json()).columns;
    } catch (error) {
      console.error(error);
    }
    if (mine !== this.generation || document.activeElement !== this.input) return;
    if (columns === null) this.close();
    else this.show(columns);
  }

  // Lists `columns` under the field, in the dialog (the top layer).
  show(columns) {
    if (this.list === null) {
      this.list = element("div", "join-candidates");
      this.list.setAttribute("role", "listbox");
      this.input.closest("dialog").append(this.list);
      this.input.setAttribute("aria-expanded", "true");
    }
    const items = columns.map((column) => {
      const item = element("div", "join-candidate", column.name);
      item.setAttribute("role", "option");
      item.dataset.name = column.name;
      item.title = `${column.name}（${column.dtype}）`;
      // The press keeps the focus in the field, which a blur would close.
      item.addEventListener("mousedown", (event) => event.preventDefault());
      item.addEventListener("click", () => this.pick(column.name));
      return item;
    });
    if (!items.length) items.push(element("div", "join-candidate-none", "該当する列はありません"));
    this.list.replaceChildren(...items);
    this.list.style.minWidth = `${this.input.offsetWidth}px`;
    this.active = -1;
    placeUnder(this.list, this.input);
  }

  close() {
    clearTimeout(this.timer);
    this.generation++;
    if (this.list === null) return;
    this.list.remove();
    this.list = null;
    this.active = -1;
    this.input.setAttribute("aria-expanded", "false");
  }

  // The arrows move among the candidates, Enter picks, Esc closes the list
  // (the dialog stays), Tab leaves.
  key(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (this.list === null) {
        this.search();
        return;
      }
      const options = [...this.list.querySelectorAll(".join-candidate")];
      if (!options.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      this.active = (this.active + step + options.length) % options.length;
      options.forEach((option, i) => option.classList.toggle("active", i === this.active));
      options[this.active].scrollIntoView({ block: "nearest" });
    } else if (plainEnter(event)) {
      event.preventDefault();
      const option = this.list?.querySelectorAll(".join-candidate")[this.active];
      if (option) this.pick(option.dataset.name);
    } else if (event.key === "Escape" && !event.isComposing && this.list !== null) {
      event.preventDefault();
      event.stopPropagation();
      this.close();
    } else if (event.key === "Tab") {
      this.close();
    }
  }
}

// The section `足す列` of the dialog (`element`): all the columns of the
// joined table, but those named like the input's when checked, or those
// picked, one a line. `onChange()` is called at every change of the choice.
export class AddedColumns {
  constructor(onChange) {
    this.onChange = onChange;
    this.picked = false;
    this.rows = [];
    this.element = element("section", "join-section join-added");
    const modes = element("div", "join-added-modes");
    this.modeInputs = [];
    for (const [value, text] of [
      ["all", "すべての列"],
      ["picked", "選んだ列だけ"],
    ]) {
      const label = element("label", "join-added-mode");
      const radio = element("input");
      Object.assign(radio, { type: "radio", name: "join-added", value });
      radio.addEventListener("change", () => {
        if (!radio.checked) return;
        this.picked = value === "picked";
        this.onChange();
      });
      this.modeInputs.push(radio);
      label.append(radio, ` ${text}`);
      modes.append(label);
    }
    this.skipLabel = element("label", "join-skip-label");
    this.skip = element("input", "join-skip");
    this.skip.type = "checkbox";
    this.skip.addEventListener("change", () => this.onChange());
    this.skipLabel.append(this.skip, " 元の表と同じ名前の列は足さない");
    this.list = element("div", "join-added-columns");
    this.addButton = button("join-add-column", "+ 列を足す", () => {
      const row = this.addRow();
      this.onChange();
      row.field.input.focus();
    });
    this.element.append(element("h3", "", "足す列"), modes, this.skipLabel, this.list, this.addButton);
    this.reset();
  }

  // Back to all the columns, unchecked, with one empty line of a column.
  reset() {
    this.close();
    this.picked = false;
    for (const radio of this.modeInputs) radio.checked = radio.value === "all";
    this.skip.checked = false;
    this.rows = [];
    this.list.replaceChildren();
    this.addRow();
  }

  // Adds a line of a column, empty, at the end. Returns it.
  addRow() {
    const row = {};
    row.field = new ColumnField("/api/join/columns", "結合する表の列", {
      onPick: () => this.onChange(),
      onEdit: () => this.onChange(),
    });
    row.remove = button("join-remove-column", "×", () => {
      row.field.close();
      this.rows = this.rows.filter((other) => other !== row);
      row.element.remove();
      this.onChange();
    });
    row.remove.title = "この列を外す";
    row.remove.setAttribute("aria-label", "この列を外す");
    row.element = element("div", "join-added-column");
    row.element.append(row.field.input, row.remove);
    this.rows.push(row);
    this.list.append(row.element);
    return row;
  }

  // Closes the candidates of every field.
  close() {
    for (const row of this.rows) row.field.close();
  }

  // Shows the check for all the columns, the lines for those picked, and
  // disables them all while `off`.
  show(off) {
    for (const radio of this.modeInputs) radio.disabled = off;
    this.skip.disabled = off;
    this.skipLabel.hidden = this.picked;
    this.list.hidden = !this.picked;
    this.addButton.hidden = !this.picked;
    for (const row of this.rows) {
      row.field.disabled = off;
      row.remove.disabled = off || this.rows.length === 1;
    }
    this.addButton.disabled = off;
  }

  // The columns picked, in the order of the lines (null while one is not
  // picked), or null for all the columns.
  columns() {
    return this.picked ? this.rows.map((row) => row.field.value) : null;
  }

  // What `POST /api/join` takes of the choice: `{columns, same_names}`.
  body() {
    const columns = this.columns();
    return { columns, same_names: columns === null && this.skip.checked ? "skip" : "rename" };
  }
}

// The join dialog in `dialog` (an empty `<dialog>`). `choose(kind)`, given
// in the window only, asks for the table with the OS dialog (`"files"` or
// `"folder"`) and resolves to its paths or null; `joined(answer, kind)` takes
// the answer of a join, once the dialog is closed; `answered()` is called at
// every answer of `POST /api/join`, joined or refused: the conversions of
// the keys it ran are over.
export class JoinDialog {
  constructor(dialog, { choose = null, joined, answered = () => {} }) {
    this.dialog = dialog;
    this.choose = choose;
    this.joined = joined;
    this.answered = answered;
    this.kind = "key";
    this.rows = [];
    // Whether the table is read, being read, or being joined.
    this.read = false;
    this.reading = false;
    this.busy = false;
    // Raised at each open, close and read: an older answer is dropped.
    this.generation = 0;
    // The paths and `recursive` read or being read (`sourceKey`).
    this.readKey = null;
    this.build();
    dialog.addEventListener("cancel", (event) => {
      if (this.busy) event.preventDefault();
    });
    dialog.addEventListener(
      "keydown",
      (event) => {
        if (this.busy && event.key === "Escape") event.preventDefault();
      },
      true,
    );
    dialog.addEventListener("close", () => {
      this.generation++;
      for (const row of this.rows) for (const field of [row.left, row.right]) field.close();
      this.added.close();
    });
  }

  get isOpen() {
    return this.dialog.open;
  }

  open() {
    this.reset();
    this.dialog.showModal();
    this.paths.focus();
  }

  // Fills the dialog with its sections, in order.
  build() {
    const dialog = this.dialog;
    dialog.classList.add("join-dialog");
    dialog.setAttribute("aria-label", "結合");
    const title = element("h2", "join-title", "結合");
    this.added = new AddedColumns(() => this.update());
    const sections = [this.buildSource(), this.buildKinds(), this.buildKeys(), this.added.element];
    dialog.replaceChildren(title, ...sections, ...this.buildEnd());
  }

  // The section of the table to join: its paths, the choice of its
  // subfolders, `読む`, and what was read. Returns the section.
  buildSource() {
    const source = element("section", "join-section join-source");
    this.paths = element("textarea", "join-paths");
    Object.assign(this.paths, { rows: 3, spellcheck: false, placeholder: "Parquet のファイルかフォルダのパス（1 行に 1 つ）" });
    this.paths.addEventListener("input", () => this.sourceEdited());
    const controls = element("div", "join-source-controls");
    this.chooseButtons = [];
    if (this.choose !== null) {
      for (const [kind, text] of [
        ["files", "ファイル…"],
        ["folder", "フォルダ…"],
      ]) {
        const chooser = button(`join-choose join-choose-${kind}`, text, () => this.chooseSource(kind));
        this.chooseButtons.push(chooser);
        controls.append(chooser);
      }
    }
    const recursiveLabel = element("label", "join-recursive-label");
    this.recursive = element("input", "join-recursive");
    this.recursive.type = "checkbox";
    this.recursive.addEventListener("change", () => this.sourceEdited());
    recursiveLabel.append(this.recursive, " フォルダのサブフォルダの Parquet も読む");
    this.readButton = button("join-read", "読む", () => this.readSource());
    controls.append(recursiveLabel, this.readButton);
    this.sourceResult = element("div", "join-source-result");
    this.sourceResult.setAttribute("role", "status");
    this.casts = element("div", "join-casts");
    this.casts.hidden = true;
    this.castsText = element("p", "join-casts-text");
    const castsList = element("div", "casts-list");
    const table = element("table");
    const head = element("thead");
    const headRow = element("tr");
    for (const text of ["列", "ファイルでの型", "読む型"]) headRow.append(element("th", "", text));
    head.append(headRow);
    this.castsBody = element("tbody");
    table.append(head, this.castsBody);
    castsList.append(table);
    this.casts.append(this.castsText, castsList);
    source.append(element("h3", "", "結合するデータ"), this.paths, controls, this.sourceResult, this.casts);
    return source;
  }

  // The section of the kind of the join. Returns the section.
  buildKinds() {
    const kinds = element("section", "join-section join-kinds");
    kinds.append(element("h3", "", "種類"));
    this.kindInputs = [];
    for (const [kind, text] of [
      ["key", "キーで結合"],
      ["rows", "行の順で並べる"],
    ]) {
      const label = element("label", "join-kind");
      const radio = element("input");
      Object.assign(radio, { type: "radio", name: "join-kind", value: kind });
      radio.addEventListener("change", () => {
        if (!radio.checked) return;
        this.kind = kind;
        this.update();
      });
      this.kindInputs.push(radio);
      label.append(radio, ` ${text}`);
      kinds.append(label);
    }
    return kinds;
  }

  // The section of the pairs of keys. Returns the section.
  buildKeys() {
    this.keysSection = element("section", "join-section join-keys-section");
    this.keyList = element("div", "join-keys");
    this.addButton = button("join-add-key", "+ キーを足す", () => {
      const row = this.addRow();
      this.update();
      row.left.input.focus();
    });
    const keysHead = element("div", "join-keys-head");
    keysHead.append(element("span", "", "元の表の列"), element("span", ""), element("span", "", "結合する表の列"));
    this.keysSection.append(element("h3", "", "キー"), keysHead, this.keyList, this.addButton);
    return this.keysSection;
  }

  // The field of the error and the buttons. Returns both.
  buildEnd() {
    this.error = element("div", "join-error");
    this.error.setAttribute("role", "alert");
    const buttons = element("div", "join-buttons");
    this.busyText = element("span", "join-busy", "結合しています…");
    this.cancelButton = button("join-cancel", "キャンセル", () => this.dialog.close());
    this.joinButton = button("join-run primary", "結合", () => this.join());
    buttons.append(this.busyText, this.cancelButton, this.joinButton);
    return [this.error, buttons];
  }

  // Empties every field, as each open starts.
  reset() {
    this.generation++;
    this.paths.value = "";
    this.recursive.checked = false;
    this.read = false;
    this.reading = false;
    this.readKey = null;
    this.busy = false;
    this.showSource("", false);
    this.casts.hidden = true;
    this.kind = "key";
    for (const radio of this.kindInputs) radio.checked = radio.value === "key";
    this.resetPicks();
    this.error.textContent = "";
    this.update();
  }

  // The paths and `recursive` in the fields, as a read sends them.
  sourceKey() {
    return JSON.stringify([parsePaths(this.paths.value), this.recursive.checked]);
  }

  // The paths or `recursive` edited: once they differ from those read or
  // being read, the table read is not theirs. Its keys and columns to add go
  // and `結合` waits
  // for another `読む`; the answer of a read in flight is dropped.
  sourceEdited() {
    if ((this.read || this.reading) && this.sourceKey() !== this.readKey) {
      this.generation++;
      this.read = false;
      this.reading = false;
      this.readKey = null;
      this.resetPicks();
      this.showSource("", false);
      this.casts.hidden = true;
    }
    this.update();
  }

  // Empties the keys and the columns to add, as a table read anew starts.
  resetPicks() {
    for (const row of this.rows) for (const field of [row.left, row.right]) field.close();
    this.rows = [];
    this.keyList.replaceChildren();
    this.addRow();
    this.added.reset();
  }

  // Adds a pair of keys, empty, at the end.
  addRow() {
    const row = {};
    row.left = new ColumnField("/api/columns", "元の表の列", {
      onPick: (name) => {
        this.update();
        this.fillSame(row, name);
      },
      onEdit: () => this.update(),
    });
    row.right = new ColumnField("/api/join/columns", "結合する表の列", {
      onPick: () => this.update(),
      onEdit: () => this.update(),
    });
    row.remove = button("join-remove-key", "×", () => {
      row.left.close();
      row.right.close();
      this.rows = this.rows.filter((other) => other !== row);
      row.element.remove();
      this.update();
    });
    row.remove.title = "このキーを外す";
    row.remove.setAttribute("aria-label", "このキーを外す");
    row.element = element("div", "join-key");
    row.element.append(row.left.input, element("span", "join-key-equals", "="), row.right.input, row.remove);
    this.rows.push(row);
    this.keyList.append(row.element);
    return row;
  }

  // Puts the column of the same name in the joined table's field of `row`,
  // once `name` is picked on the left, when that field is empty and the
  // joined table has such a column.
  async fillSame(row, name) {
    const right = row.right;
    const empty = () => right.value === null && right.input.value === "";
    if (!empty()) return;
    const mine = this.generation;
    let columns = [];
    try {
      const response = await fetch(`/api/join/columns?${new URLSearchParams({ q: name, exact: name })}`);
      if (response.ok) columns = (await response.json()).columns;
    } catch (error) {
      console.error(error);
    }
    if (mine !== this.generation || !this.rows.includes(row) || row.left.value !== name || !empty()) return;
    if (columns.some((column) => column.name === name)) {
      right.set(name);
      this.update();
    }
  }

  showSource(text, failed) {
    this.sourceResult.textContent = text;
    this.sourceResult.classList.toggle("join-failed", failed);
  }

  // Enables what may be used now: nothing while it joins; the keys and the
  // columns to add once a table is read; `結合` once it may join
  // (`joinReady`).
  update() {
    const locked = this.busy;
    const keysOff = locked || !this.read;
    this.paths.disabled = locked;
    this.recursive.disabled = locked;
    for (const chooser of this.chooseButtons) chooser.disabled = locked || this.reading;
    this.readButton.disabled = locked || this.reading || parsePaths(this.paths.value).length === 0;
    for (const radio of this.kindInputs) radio.disabled = locked;
    this.keysSection.hidden = this.kind === "rows";
    for (const row of this.rows) {
      row.left.disabled = keysOff;
      row.right.disabled = keysOff;
      row.remove.disabled = keysOff || this.rows.length === 1;
    }
    this.addButton.disabled = keysOff;
    this.added.show(keysOff);
    this.cancelButton.disabled = locked;
    this.busyText.hidden = !locked;
    const keys = this.rows.map((row) => ({ left: row.left.value, right: row.right.value }));
    this.joinButton.disabled = locked || !joinReady(this.read, this.kind, keys, this.added.columns());
  }

  // Asks for the table with the OS dialog: the paths chosen replace the
  // field's and are read; a closed dialog changes nothing.
  async chooseSource(kind) {
    const mine = this.generation;
    let paths;
    try {
      paths = await this.choose(kind);
    } catch (error) {
      if (mine === this.generation) this.showSource(error?.message ?? String(error), true);
      return;
    }
    if (mine !== this.generation || !paths?.length) return;
    this.paths.value = paths.join("\n");
    this.readSource();
  }

  // Reads the table of the paths, in place of one read before; the keys and
  // the columns to add start again empty.
  async readSource() {
    const paths = parsePaths(this.paths.value);
    if (!paths.length || this.busy || this.reading) return;
    const mine = ++this.generation;
    this.readKey = this.sourceKey();
    this.reading = true;
    this.read = false;
    this.resetPicks();
    this.showSource("読んでいます…", false);
    this.casts.hidden = true;
    this.error.textContent = "";
    this.update();
    const answer = await post("/api/join/source", { paths, recursive: this.recursive.checked });
    if (mine !== this.generation) return;
    this.reading = false;
    if (answer.ok) {
      const found = JSON.parse(answer.text);
      this.read = true;
      this.showSource(sourceText(found), false);
      if (found.casts.length) {
        this.castsText.textContent = castsText(found.files, found.casts);
        this.castsBody.replaceChildren(...castRows(found.casts));
        this.casts.hidden = false;
      }
    } else {
      this.showSource(errorText(answer.text, answer.status), true);
    }
    this.update();
    // The focus left with the button disabled meanwhile.
    if (!this.dialog.contains(document.activeElement)) this.readButton.focus();
  }

  // Joins the table read: everything waits meanwhile; a refused join tells
  // why and the fields come back, a join closes the dialog.
  async join() {
    if (this.joinButton.disabled) return;
    const kind = this.kind;
    const keys = kind === "key" ? this.rows.map((row) => ({ left: row.left.value, right: row.right.value })) : [];
    this.busy = true;
    this.error.textContent = "";
    this.update();
    const answer = await post("/api/join", { kind, keys, ...this.added.body() });
    this.busy = false;
    this.answered();
    if (answer.ok) {
      this.dialog.close();
      this.joined(JSON.parse(answer.text), kind);
      return;
    }
    this.error.textContent = errorText(answer.text, answer.status);
    this.update();
    if (!this.dialog.contains(document.activeElement)) this.joinButton.focus();
  }
}
