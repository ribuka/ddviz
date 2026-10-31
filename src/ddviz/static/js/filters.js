// The local filter pane, below the column list. A
// column dragged onto it gets a card: a numeric column a range (a slider with
// two thumbs and two boxes), a categorical column its levels with their counts
// to tick, or, with too many levels to list (an ID), a box of text the kept
// values contain. The server summarizes a column over every row, once
// (`GET /api/summary`). A row is drawn when it meets every card's condition
// (`ddviz.compute.rowfilter`); a card that keeps every row has no condition.
//
// A condition goes to the plot when a slider is let go, a box (or the text
// box) is left or Enter is pressed in it, or 0.4s after the last tick, so that a few ticks in
// a row aggregate once.
import { draggedColumn } from "./builder.js";
import { formatTemporal, isDateKind, parseTemporal } from "./temporal.js";

const TICK_SETTLE_MS = 400;
// Steps of a slider over the column's range.
const STEPS = 1000;
const SUMMARY_RETRY_MS = 300;
const MS_PER_DAY = 86_400_000;

// Returns a number short enough for the pane.
export function formatNumber(value) {
  if (!Number.isFinite(value)) return String(value);
  if (Number.isInteger(value)) return value.toLocaleString();
  return String(Number(value.toPrecision(4)));
}

// Returns a bound of a numeric card: a datetime, date or time column's as
// such (`temporal.js`), else as `formatNumber`.
function formatBound(card, value) {
  return formatTemporal(card.summary?.temporal, value) ?? formatNumber(value);
}

export class FilterPane {
  // `root` is the pane (`#filters`); `onChange` gets the conditions after each
  // committed change; `onSummary` gets the summary text whenever it changes.
  constructor(root, onChange, onSummary) {
    this.root = root;
    this.list = root.querySelector(".filter-list");
    this.head = root.querySelector(".filter-summary");
    this.toggle = root.querySelector(".filter-toggle");
    this.tip = document.getElementById("drop-tip");
    this.onChange = onChange;
    this.onSummary = onSummary;
    // One card per column, in the order added: `{name, numeric, summary,
    // range, levels, contains, element}`; `range` is [lo, hi], `levels` the
    // ticked set, `contains` the text of a column with too many levels.
    this.cards = [];
    this.committed = "[]";
    this.timer = null;
    this.toggle.addEventListener("click", () => this.setCollapsed(!root.classList.contains("collapsed")));
    root.querySelector(".filter-head").addEventListener("dblclick", () => this.toggle.click());
    this.attachDrop();
    this.render();
  }

  setCollapsed(collapsed) {
    this.root.classList.toggle("collapsed", collapsed);
    this.toggle.textContent = collapsed ? "▲" : "▼";
    this.toggle.title = collapsed ? "フィルタ欄を開く" : "フィルタ欄を畳む（条件の要約は見出しに残る）";
  }

  // A column from the list, or a placed one (a chip, which stays placed),
  // dropped on the pane gets a card.
  attachDrop() {
    this.root.addEventListener("dragover", (event) => {
      const column = draggedColumn();
      if (!column) return;
      event.preventDefault();
      event.stopPropagation();
      const known = this.cards.some((c) => c.name === column.name);
      event.dataTransfer.dropEffect = known ? "none" : "copy";
      this.root.classList.toggle("over", !known);
      this.showTip(known ? `${column.name} はフィルタにある` : `${column.name} で行を絞る`);
    });
    this.root.addEventListener("dragleave", (event) => {
      if (this.root.contains(event.relatedTarget)) return;
      this.root.classList.remove("over");
    });
    this.root.addEventListener("drop", (event) => {
      const column = draggedColumn();
      if (!column) return;
      event.preventDefault();
      event.stopPropagation();
      this.root.classList.remove("over");
      this.showTip(null);
      document.dispatchEvent(new Event("dragend"));
      this.add(column);
    });
  }

  showTip(text) {
    this.tip.textContent = text ?? "";
    this.tip.hidden = !text;
  }

  add({ name, numeric }) {
    if (this.cards.some((c) => c.name === name)) return;
    const card = { name, numeric, summary: null, range: null, levels: new Set(), contains: "", element: null };
    this.cards.push(card);
    this.setCollapsed(false);
    this.render();
    this.loadSummary(card);
  }

  remove(card) {
    this.cards = this.cards.filter((c) => c !== card);
    this.render();
    this.commit();
  }

  async loadSummary(card) {
    for (;;) {
      const response = await fetch(`/api/summary?${new URLSearchParams({ column: card.name })}`);
      if (!this.cards.includes(card)) return;
      if (response.status === 409) {
        await new Promise((resolve) => setTimeout(resolve, SUMMARY_RETRY_MS));
        continue;
      }
      if (!response.ok) {
        card.error = await response.text();
      } else {
        card.summary = await response.json();
        if (card.summary.numeric && card.summary.min !== null) card.range = [card.summary.min, card.summary.max];
      }
      this.render();
      return;
    }
  }

  // Returns the conditions of the cards that leave rows out, for the server
  // (`ddviz.server.plan.parse_filters`).
  conditions() {
    const out = [];
    for (const card of this.cards) {
      if (!this.isActive(card)) continue;
      if (card.numeric) out.push({ column: card.name, range: [...card.range] });
      else if (card.summary.levels === null) out.push({ column: card.name, contains: card.contains });
      else out.push({ column: card.name, levels: [...card.levels].sort() });
    }
    return out;
  }

  isActive(card) {
    if (!card.summary) return false;
    if (card.numeric) {
      return card.range !== null && (card.range[0] > card.summary.min || card.range[1] < card.summary.max);
    }
    if (card.summary.levels === null) return card.contains !== "";
    return card.levels.size > 0;
  }

  // Returns the conditions in a few words: "g1: 3/10、x: −2〜5、id: 「a1」を含む".
  summaryText() {
    return this.cards
      .filter((card) => this.isActive(card))
      .map((card) => {
        if (card.numeric) return `${card.name}: ${formatBound(card, card.range[0])}〜${formatBound(card, card.range[1])}`;
        if (card.summary.levels === null) return `${card.name}: 「${card.contains}」を含む`;
        return `${card.name}: ${card.levels.size}/${card.summary.levels.length}`;
      })
      .join("、");
  }

  // Sends the conditions now, unless they are the ones sent last.
  commit() {
    clearTimeout(this.timer);
    this.updateSummary();
    const conditions = this.conditions();
    const key = JSON.stringify(conditions);
    if (key === this.committed) return;
    this.committed = key;
    this.onChange(conditions);
  }

  // Sends the conditions once the ticks have stopped for a moment.
  commitSoon() {
    this.updateSummary();
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.commit(), TICK_SETTLE_MS);
  }

  updateSummary() {
    const text = this.summaryText();
    const count = this.cards.filter((c) => this.isActive(c)).length;
    this.head.textContent = count ? `（${count}）${text}` : "";
    this.head.title = text;
    this.onSummary(count, text);
  }

  render() {
    this.list.replaceChildren(...this.cards.map((card) => this.cardElement(card)));
    this.updateSummary();
  }

  cardElement(card) {
    const element = document.createElement("div");
    element.className = "filter-card";
    card.element = element;
    const head = document.createElement("div");
    head.className = "filter-card-head";
    const type = document.createElement("span");
    type.className = `column-type ${card.numeric ? "numeric" : "categorical"}`;
    type.textContent = card.numeric ? "#" : "A";
    const name = document.createElement("span");
    name.className = "filter-card-name";
    name.textContent = card.name;
    name.title = card.name;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "filter-card-remove";
    close.textContent = "×";
    close.title = "このフィルタを外す";
    close.addEventListener("click", () => this.remove(card));
    head.append(type, name, close);
    element.append(head);
    const body = document.createElement("div");
    body.className = "filter-card-body";
    element.append(body);
    if (card.error) {
      body.textContent = `エラー: ${card.error}`;
    } else if (!card.summary) {
      body.textContent = "集計中…";
    } else if (card.numeric) {
      this.numericBody(card, body);
    } else {
      this.levelBody(card, body);
    }
    return element;
  }

  numericBody(card, body) {
    const { min, max, nulls, integer, temporal } = card.summary;
    // A datetime, date or time column's bounds are typed as text; its
    // values are milliseconds (`ddviz.compute.temporal`).
    const dates = isDateKind(temporal);
    const toText = (v) => (dates ? formatTemporal(temporal, v) : String(v));
    const fromText = (text) => (dates ? parseTemporal(temporal, text) : text === "" ? null : Number(text));
    const note = document.createElement("div");
    note.className = "filter-note";
    note.textContent = `最小 ${formatBound(card, min)}　最大 ${formatBound(card, max)}` + (nulls ? `　null ${nulls.toLocaleString()} 行` : "");
    body.append(note);
    if (min === null) {
      note.textContent = "有限な値が無い";
      return;
    }
    const span = max - min;
    const toStep = (v) => (span > 0 ? Math.round(((v - min) / span) * STEPS) : 0);
    const fromStep = (s) => {
      if (s <= 0) return min;
      if (s >= STEPS) return max;
      const v = min + (span * s) / STEPS;
      // A date steps by days, as it is shown; a datetime or time keeps its
      // microseconds (6 digits of milliseconds since 1970 are days).
      if (temporal === "date") return Math.round(v / MS_PER_DAY) * MS_PER_DAY;
      if (dates) return Math.round(v * 1000) / 1000;
      return integer ? Math.round(v) : Number(v.toPrecision(6));
    };
    const slider = document.createElement("div");
    slider.className = "filter-slider";
    const fill = document.createElement("div");
    fill.className = "filter-slider-fill";
    const thumbs = [0, 1].map((i) => {
      const input = document.createElement("input");
      input.type = "range";
      input.min = 0;
      input.max = STEPS;
      input.value = toStep(card.range[i]);
      input.disabled = span === 0;
      return input;
    });
    slider.append(fill, ...thumbs);
    const boxes = document.createElement("div");
    boxes.className = "filter-range";
    // A datetime's bounds are too long to sit side by side.
    boxes.classList.toggle("dates", dates);
    const inputs = [0, 1].map((i) => {
      const input = document.createElement("input");
      if (dates) {
        input.type = "text";
        input.classList.add("filter-date");
        input.placeholder = formatTemporal(temporal, i === 0 ? min : max);
      } else {
        input.type = "number";
        input.step = integer ? 1 : "any";
      }
      input.value = toText(card.range[i]);
      return input;
    });
    boxes.append(inputs[0], "〜", inputs[1]);
    const show = () => {
      for (const i of [0, 1]) {
        thumbs[i].value = toStep(card.range[i]);
        if (document.activeElement !== inputs[i]) inputs[i].value = toText(card.range[i]);
      }
      const [a, b] = thumbs.map((t) => (Number(t.value) / STEPS) * 100);
      fill.style.left = `${a}%`;
      fill.style.width = `${b - a}%`;
    };
    thumbs.forEach((thumb, i) => {
      // Dragging moves the bounds; letting go sends them.
      thumb.addEventListener("input", () => {
        let step = Number(thumb.value);
        const other = Number(thumbs[1 - i].value);
        step = i === 0 ? Math.min(step, other) : Math.max(step, other);
        card.range[i] = fromStep(step);
        show();
        this.updateSummary();
      });
      thumb.addEventListener("change", () => this.commit());
    });
    inputs.forEach((input, i) => {
      input.addEventListener("change", () => {
        let value = fromText(input.value);
        if (value === null || !Number.isFinite(value)) value = i === 0 ? min : max;
        value = Math.min(Math.max(value, min), max);
        card.range[i] = i === 0 ? Math.min(value, card.range[1]) : Math.max(value, card.range[0]);
        input.value = toText(card.range[i]);
        show();
        this.commit();
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") input.blur();
      });
    });
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "filter-reset";
    reset.textContent = "全範囲";
    reset.title = "範囲を最小〜最大に戻す（絞らない）";
    reset.addEventListener("click", () => {
      card.range = [min, max];
      show();
      this.commit();
    });
    boxes.append(reset);
    body.append(slider, boxes);
    show();
  }

  levelBody(card, body) {
    const { levels, n_levels: count, nulls } = card.summary;
    if (levels === null) {
      this.containsBody(card, body);
      return;
    }
    const bar = document.createElement("div");
    bar.className = "filter-note";
    const counter = document.createElement("span");
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "filter-reset";
    clear.textContent = "すべて外す";
    clear.title = "選んだ水準を外す（絞らない）";
    bar.append(counter, clear);
    const list = document.createElement("div");
    list.className = "filter-levels";
    const boxes = levels.map(([level, n]) => {
      const label = document.createElement("label");
      label.className = "filter-level";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = card.levels.has(level);
      box.addEventListener("change", () => {
        if (box.checked) card.levels.add(level);
        else card.levels.delete(level);
        update();
        this.commitSoon();
      });
      const text = document.createElement("span");
      text.className = "filter-level-name";
      text.textContent = level;
      text.title = level;
      const num = document.createElement("span");
      num.className = "filter-level-count";
      num.textContent = n.toLocaleString();
      label.append(box, text, num);
      list.append(label);
      return box;
    });
    const update = () => {
      const picked = card.levels.size;
      counter.textContent = picked ? `${picked} / ${levels.length} 水準を選択` : `${levels.length} 水準（選ぶと絞る）`;
      if (nulls) counter.textContent += `　null ${nulls.toLocaleString()} 行`;
      clear.disabled = picked === 0;
    };
    clear.addEventListener("click", () => {
      card.levels.clear();
      for (const box of boxes) box.checked = false;
      update();
      this.commit();
    });
    update();
    body.append(bar, list);
  }

  // A column with too many levels to list is filtered by the text its kept
  // values contain (literally, case-sensitively); an empty box keeps every row.
  containsBody(card, body) {
    const { n_levels: count, nulls } = card.summary;
    const note = document.createElement("div");
    note.className = "filter-note";
    note.textContent = `水準が多すぎる（約 ${count.toLocaleString()} 個）ため、部分一致で絞る`;
    if (nulls) note.textContent += `　null ${nulls.toLocaleString()} 行`;
    const bar = document.createElement("div");
    bar.className = "filter-contains";
    const input = document.createElement("input");
    input.type = "text";
    input.value = card.contains;
    input.placeholder = "含む文字列";
    input.title = "この文字列を含む行だけを残す（大文字と小文字を区別する。空なら絞らない）";
    input.addEventListener("change", () => {
      card.contains = input.value;
      this.commit();
    });
    input.addEventListener("keydown", (event) => {
      // The Enter that commits an IME conversion keeps editing.
      if (event.key === "Enter" && !event.isComposing && event.keyCode !== 229) input.blur();
    });
    bar.append(input);
    body.append(note, bar);
  }
}
