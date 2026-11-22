// The dialog of the join (docs/spec.md, "横の結合"): it reads the table to
// join (`POST /api/join/source`), takes the kind and, for a join by keys,
// the pairs of keys picked from the columns of both tables, the columns to
// add (all, maybe but those named like the input's, or but those of the
// same values too, or those picked), and
// joins (`POST /api/join`). By keys, it joins only after a dry run of the
// keys (`確かめる`, `POST /api/join/check`), which tells the rows of both
// tables that match and the keys that match none, and lets the rows of both
// tables be saved with their state (`POST /api/plot-data/join-rows`, as the
// plot's data is saved: `saves.js`); a change of the keys or the kind drops
// it. A dry run or a join waits with `中止` (`POST /api/join/cancel`).
// The page (app.js) opens it from the window's `Data → 結合…` or Ctrl+J, and
// takes the answer of a join.
// A refused read or join tells the server's reason in the dialog, which
// stays open; Esc and キャンセル close it without joining, but not while it
// waits. It starts empty each time it opens: the table the server read stays
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

// The toast of a join of `kind` sent with `sameNames` (its `same_names`)
// that answered `answer` (`{added, rows, matched, skipped}`): the columns
// added, by keys the share of the input's rows that matched, to one decimal,
// and the columns left out by name, or by name and values.
export function joinedText(answer, kind, sameNames) {
  let text = `${answer.added.length.toLocaleString()} 列を結合しました。`;
  if (kind === "key") {
    const share = answer.rows > 0 ? (answer.matched / answer.rows) * 100 : 0;
    text += `元の表の ${share.toFixed(1)}% の行が結合できました。`;
  }
  const skipped = answer.skipped?.length ?? 0;
  if (skipped === 0) return text;
  const count = skipped.toLocaleString();
  if (sameNames === "skip_equal") return `${text}元の表と名前も中身も同じ ${count} 列は保持しませんでした。`;
  return `${text}元の表と同じ名前の ${count} 列は保持しませんでした。`;
}

// The overlay's text of a progress of the comparison of the columns named
// like the input's (`{done, total, column}`, stage `"compare"`).
export function comparingText(message) {
  return `同じ名前の列を比べています（${message.done + 1} / ${message.total}）：${message.column}`;
}

// The most sets of keys matching none a dry run lists per table
// (`ddviz.compute.joinsummary.UNMATCHED_EXAMPLES`).
export const UNMATCHED_EXAMPLES = 20;

// The share of `part` in `whole` after a count of `part` rows, as
// `joinedText` gives it: "（74.9%）"; nothing for no rows.
function shareText(part, whole) {
  return whole > 0 ? `（${((part / whole) * 100).toFixed(1)}%）` : "";
}

// The two lines of a dry run's answer (`{rows, matched, right_rows,
// right_matched}`): the rows of the input that join, and those of the joined
// table that match a row of the input.
export function checkText(answer) {
  const count = (n) => n.toLocaleString();
  return [
    `元の表：${count(answer.rows)} 行のうち ${count(answer.matched)} 行${shareText(answer.matched, answer.rows)}が結合できます。${count(answer.rows - answer.matched)} 行は結合できません。`,
    `結合する表：${count(answer.right_rows)} 行のうち ${count(answer.right_matched)} 行${shareText(answer.right_matched, answer.right_rows)}が元の表の行と一致します。${count(answer.right_rows - answer.right_matched)} 行は一致しません。`,
  ];
}

// The heading of the table of the sets of keys of `side` (`"left"`, the
// input, or `"right"`) that match none, of `sets` sets.
export function unmatchedHeading(side, sets) {
  const what = side === "left" ? "元の表で結合できなかったキー" : "結合する表で一致しなかったキー";
  return `${what}（${sets.toLocaleString()} 組。行の多い順に最大 ${UNMATCHED_EXAMPLES} 組）`;
}

// The cells of each row of that table (`{sets, top}` of the answer): the
// values of the set, null as "null", then its rows.
export function unmatchedRows(found) {
  return found.top.map((set) => [...set.values.map((value) => value ?? "null"), set.rows.toLocaleString()]);
}

// Whether the answer of a request (`post`) is that of one cancelled
// (`POST /api/join/cancel`): 409 `cancelled`.
export function wasCancelled(answer) {
  if (answer.status !== 409) return false;
  try {
    return JSON.parse(answer.text).detail === "cancelled";
  } catch {
    return false;
  }
}

// Whether `結合` may be pressed: a table read; by keys, both columns of
// every pair picked (`keys` of `{left, right}`, null while not picked) and a
// dry run of these keys (`checked`); and, for the columns picked (`columns`
// of the names, null while not picked; null for all the columns), at least
// one, each picked.
export function joinReady(read, kind, keys, columns = null, checked = false) {
  if (!read) return false;
  if (columns !== null && (columns.length === 0 || columns.includes(null))) return false;
  if (kind === "rows") return true;
  return checked && keysPicked(keys);
}

// Whether both columns of every pair of keys are picked.
function keysPicked(keys) {
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

// The section `保持する列` of the dialog (`element`): all the columns of the
// joined table, with those named like the input's left out when of the same
// values and kept renamed otherwise, or left out (the radios of `元の表と同じ
// 名前の列：`), or those picked, one a line. `onChange()` is called at every
// change of the choice.
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
    this.sameNames = element("div", "join-same-names");
    this.sameNames.append(element("span", "join-same-names-label", "元の表と同じ名前の列："));
    this.sameInputs = [];
    for (const [value, text] of [
      ["skip_equal", "中身が違えば保持"],
      ["skip", "保持しない"],
    ]) {
      const label = element("label", "join-same-name");
      const radio = element("input");
      Object.assign(radio, { type: "radio", name: "join-same-names", value });
      radio.addEventListener("change", () => this.onChange());
      this.sameInputs.push(radio);
      label.append(radio, ` ${text}`);
      this.sameNames.append(label);
    }
    this.list = element("div", "join-added-columns");
    this.addButton = button("join-add-column", "+ 列を足す", () => {
      const row = this.addRow();
      this.onChange();
      row.field.input.focus();
    });
    this.element.append(element("h3", "", "保持する列"), modes, this.sameNames, this.list, this.addButton);
    this.reset();
  }

  // Back to all the columns, those named like the input's kept when their
  // values differ, with one empty line of a column.
  reset() {
    this.close();
    this.picked = false;
    for (const radio of this.modeInputs) radio.checked = radio.value === "all";
    for (const radio of this.sameInputs) radio.checked = radio.value === "skip_equal";
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

  // Shows the radios of the same names for all the columns, the lines for
  // those picked, and disables them all while `off`.
  show(off) {
    for (const radio of [...this.modeInputs, ...this.sameInputs]) radio.disabled = off;
    this.sameNames.hidden = this.picked;
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
    const same = this.sameInputs.find((radio) => radio.checked).value;
    return { columns, same_names: columns === null ? same : null };
  }
}

// The join dialog in `dialog` (an empty `<dialog>`). `choose(kind)`, given
// in the window only, asks for the table with the OS dialog (`"files"` or
// `"folder"`) and resolves to its paths or null; `joined(answer, kind,
// sameNames)` takes the answer of a join and the `same_names` sent, once the
// dialog is closed; `answered()` is called at every answer of
// `POST /api/join/check` and `POST /api/join`, done, refused or cancelled:
// the conversions of the keys it ran are over. `saves` (`saves.js`) saves
// the rows of both tables; `toasts` (`notice.js`) are shown above the dialog
// while it is open.
export class JoinDialog {
  constructor(dialog, { choose = null, joined, answered = () => {}, saves, toasts }) {
    this.dialog = dialog;
    this.choose = choose;
    this.joined = joined;
    this.answered = answered;
    this.saves = saves;
    this.toasts = toasts;
    this.kind = "key";
    this.rows = [];
    // Whether the table is read or being read.
    this.read = false;
    this.reading = false;
    // What the dialog waits for: `"check"` (a dry run) or `"join"`, or null;
    // and whether its cancel was sent.
    this.waiting = null;
    this.cancelling = false;
    // The dry run of the keys in the fields: `{keys, answer}`, or null.
    this.checked = null;
    // Whether a save of the rows of both tables started here runs. It
    // outlives a close of the dialog.
    this.saving = false;
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

  // Whether a dry run or a join is waited for: the fields wait meanwhile.
  get busy() {
    return this.waiting !== null;
  }

  open() {
    this.reset();
    this.dialog.showModal();
    this.toasts?.over(this.dialog);
    this.paths.focus();
  }

  // Fills the dialog with its sections, in order.
  build() {
    const dialog = this.dialog;
    dialog.classList.add("join-dialog");
    dialog.setAttribute("aria-label", "結合");
    const title = element("h2", "join-title", "結合");
    this.added = new AddedColumns(() => this.update());
    const sections = [this.buildSource(), this.buildKinds(), this.buildKeys(), this.buildCheck(), this.added.element];
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
        this.clearCheck();
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
      this.keysEdited();
      row.left.input.focus();
    });
    const keysHead = element("div", "join-keys-head");
    keysHead.append(element("span", "", "元の表の列"), element("span", ""), element("span", "", "結合する表の列"));
    this.keysSection.append(element("h3", "", "キー"), keysHead, this.keyList, this.addButton);
    return this.keysSection;
  }

  // The section of the dry run: `確かめる`, what it found, and the save of
  // the rows of both tables. Returns the section.
  buildCheck() {
    this.checkSection = element("section", "join-section join-check");
    this.checkButton = button("join-check-run", "確かめる", () => this.check());
    this.checkResult = element("div", "join-check-result");
    this.checkResult.setAttribute("role", "status");
    const save = element("div", "join-rows-save");
    save.append(element("span", "join-rows-label", "行の一覧を保存："));
    this.rowsInputs = [];
    for (const [value, text] of [
      ["key", "Key columns"],
      ["all", "All columns"],
    ]) {
      const label = element("label", "join-rows-columns");
      const radio = element("input");
      Object.assign(radio, { type: "radio", name: "join-rows-columns", value });
      this.rowsInputs.push(radio);
      label.append(radio, ` ${text}`);
      save.append(label);
    }
    this.saveButtons = [
      ["csv", "CSV"],
      ["parquet", "Parquet"],
    ].map(([format, text]) => button(`join-rows-save-${format}`, text, () => this.saveRows(format)));
    save.append(...this.saveButtons);
    this.checkSection.append(this.checkButton, this.checkResult, save);
    return this.checkSection;
  }

  // The field of the error and the buttons. Returns both.
  buildEnd() {
    this.error = element("div", "join-error");
    this.error.setAttribute("role", "alert");
    const buttons = element("div", "join-buttons");
    this.busyText = element("span", "join-busy");
    this.abortButton = button("join-abort", "中止", () => this.abort());
    const wait = element("div", "join-wait");
    wait.append(this.busyText, this.abortButton);
    this.cancelButton = button("join-cancel", "キャンセル", () => this.dialog.close());
    this.joinButton = button("join-run primary", "結合", () => this.join());
    buttons.append(wait, this.cancelButton, this.joinButton);
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
    this.waiting = null;
    this.cancelling = false;
    this.showSource("", false);
    this.casts.hidden = true;
    this.kind = "key";
    for (const radio of this.kindInputs) radio.checked = radio.value === "key";
    for (const radio of this.rowsInputs) radio.checked = radio.value === "key";
    this.resetPicks();
    this.showError("");
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

  // Empties the keys, the dry run and the columns to add, as a table read
  // anew starts.
  resetPicks() {
    for (const row of this.rows) for (const field of [row.left, row.right]) field.close();
    this.rows = [];
    this.keyList.replaceChildren();
    this.addRow();
    this.added.reset();
    this.clearCheck();
  }

  // The pairs of keys in the fields (null for a column not picked).
  keys() {
    return this.rows.map((row) => ({ left: row.left.value, right: row.right.value }));
  }

  // A field of the keys changed, or a pair came or went: the dry run is not
  // theirs any more.
  keysEdited() {
    this.clearCheck();
    this.update();
  }

  // Drops the dry run and what it found.
  clearCheck() {
    this.checked = null;
    this.checkResult.replaceChildren();
    this.checkResult.hidden = true;
  }

  // Adds a pair of keys, empty, at the end.
  addRow() {
    const row = {};
    row.left = new ColumnField("/api/columns", "元の表の列", {
      onPick: (name) => {
        this.keysEdited();
        this.fillSame(row, name);
      },
      onEdit: () => this.keysEdited(),
    });
    row.right = new ColumnField("/api/join/columns", "結合する表の列", {
      onPick: () => this.keysEdited(),
      onEdit: () => this.keysEdited(),
    });
    row.remove = button("join-remove-key", "×", () => {
      row.left.close();
      row.right.close();
      this.rows = this.rows.filter((other) => other !== row);
      row.element.remove();
      this.keysEdited();
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
      this.keysEdited();
    }
  }

  showSource(text, failed) {
    this.sourceResult.textContent = text;
    this.sourceResult.classList.toggle("join-failed", failed);
  }

  // Tells in the field under the sections an error (red), or a notice.
  showError(text, notice = false) {
    this.error.textContent = text;
    this.error.classList.toggle("join-notice", notice);
  }

  // Shows what the dry run found: its two lines, and a table of the sets of
  // keys of each table matching none, when there are.
  showCheck() {
    const { keys, answer } = this.checked;
    const shown = checkText(answer).map((line) => element("p", "join-check-line", line));
    for (const side of ["left", "right"]) {
      const found = answer[`${side}_unmatched`];
      if (found.sets < 1) continue;
      shown.push(element("p", "join-unmatched-heading", unmatchedHeading(side, found.sets)));
      shown.push(unmatchedTable(side, [...keys.map((key) => key[side]), "行数"], unmatchedRows(found)));
    }
    this.checkResult.replaceChildren(...shown);
    this.checkResult.hidden = false;
  }

  // Enables what may be used now: nothing while it waits; the keys and the
  // columns to add once a table is read; `確かめる` once every key is
  // picked; the save of the rows and `結合` (`joinReady`) after a dry run,
  // but neither `確かめる` nor `結合` while a save started here runs.
  update() {
    const locked = this.busy;
    const keysOff = locked || !this.read;
    this.paths.disabled = locked;
    this.recursive.disabled = locked;
    for (const chooser of this.chooseButtons) chooser.disabled = locked || this.reading;
    this.readButton.disabled = locked || this.reading || parsePaths(this.paths.value).length === 0;
    for (const radio of this.kindInputs) radio.disabled = locked;
    this.keysSection.hidden = this.kind === "rows";
    this.checkSection.hidden = this.kind === "rows";
    for (const row of this.rows) {
      row.left.disabled = keysOff;
      row.right.disabled = keysOff;
      row.remove.disabled = keysOff || this.rows.length === 1;
    }
    this.addButton.disabled = keysOff;
    this.added.show(keysOff);
    const keys = this.keys();
    this.checkButton.disabled = keysOff || this.saving || !keysPicked(keys);
    // One save at a time, wherever it started (`saves.js`).
    const saveOff = locked || this.saving || this.checked === null || this.saves.running;
    for (const control of [...this.rowsInputs, ...this.saveButtons]) control.disabled = saveOff;
    this.cancelButton.disabled = locked;
    this.busyText.hidden = !locked;
    this.busyText.textContent = this.cancelling ? "中止しています…" : this.waiting === "check" ? "確かめています…" : "結合しています…";
    this.abortButton.hidden = !locked;
    this.abortButton.disabled = this.cancelling;
    const ready = joinReady(this.read, this.kind, keys, this.added.columns(), this.checked !== null);
    this.joinButton.disabled = locked || this.saving || !ready;
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
    this.showError("");
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
    this.refocus(this.readButton);
  }

  // Posts `body` to `url` with everything waiting for `waiting` (`"check"`
  // or `"join"`), `中止` shown; resolves to the answer once it came (`post`),
  // the conversions it ran over (`answered`).
  async wait(waiting, url, body) {
    this.waiting = waiting;
    this.cancelling = false;
    this.showError("");
    this.update();
    const answer = await post(url, body);
    this.waiting = null;
    this.cancelling = false;
    this.answered();
    return answer;
  }

  // A dry run or a join that did not join: cancelled, told so plainly, or
  // refused, told why in red; the fields come back.
  ended(answer, button) {
    if (wasCancelled(answer)) this.showError("中止しました。", true);
    else this.showError(errorText(answer.text, answer.status));
    this.update();
    this.refocus(button);
  }

  // Puts the focus on `button` when it left the dialog, as a button
  // disabled while it waited loses it.
  refocus(button) {
    if (!this.dialog.contains(document.activeElement)) button.focus();
  }

  // Tries the join by the keys without joining: what it found shows, and
  // `結合` and the save of the rows may follow.
  async check() {
    if (this.checkButton.disabled) return;
    const keys = this.keys();
    this.clearCheck();
    const answer = await this.wait("check", "/api/join/check", { keys });
    if (!answer.ok) {
      this.ended(answer, this.checkButton);
      return;
    }
    this.checked = { keys, answer: JSON.parse(answer.text) };
    this.showCheck();
    this.update();
    this.refocus(this.checkButton);
  }

  // Cancels the dry run or the join waited for; its answer then tells how
  // it ended. A cancel the server did not take may be sent again.
  async abort() {
    if (!this.busy || this.cancelling) return;
    this.cancelling = true;
    this.update();
    let ok = false;
    try {
      ok = (await fetch("/api/join/cancel", { method: "POST" })).ok;
    } catch (error) {
      console.error(error);
    }
    if (!ok && this.busy) {
      this.cancelling = false;
      this.update();
    }
  }

  // Saves the rows of both tables of the dry run as `format`
  // (`saves.js`), the columns of the radios; `確かめる` and `結合` wait
  // until it is written.
  async saveRows(format) {
    if (this.saveButtons[0].disabled) return;
    const columns = this.rowsInputs.find((radio) => radio.checked).value;
    this.saving = true;
    this.update();
    try {
      await this.saves.start(format, { url: "/api/plot-data/join-rows", fields: { columns } });
    } finally {
      this.saving = false;
      this.update();
    }
  }

  // Joins the table read: everything waits meanwhile; a refused or
  // cancelled join tells it and the fields come back, a join closes the
  // dialog.
  async join() {
    if (this.joinButton.disabled) return;
    const kind = this.kind;
    const keys = kind === "key" ? this.keys() : [];
    const added = this.added.body();
    const answer = await this.wait("join", "/api/join", { kind, keys, ...added });
    if (answer.ok) {
      this.dialog.close();
      this.joined(JSON.parse(answer.text), kind, added.same_names);
      return;
    }
    this.ended(answer, this.joinButton);
  }
}

// The table of the sets of keys of `side` matching none, with `names` as
// its heading and `rows` as its cells, in a box of its own height.
function unmatchedTable(side, names, rows) {
  const box = element("div", `join-unmatched join-unmatched-${side}`);
  const table = element("table");
  const head = element("thead");
  const headRow = element("tr");
  for (const name of names) headRow.append(element("th", "", name));
  head.append(headRow);
  const body = element("tbody");
  for (const cells of rows) {
    const row = element("tr");
    for (const cell of cells) row.append(element("td", "", cell));
    body.append(row);
  }
  table.append(head, body);
  box.append(table);
  return box;
}
