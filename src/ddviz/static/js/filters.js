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
//
// The "…" button of a card with its levels listed opens "Sort by": Name keeps
// the order of the summary (natural), Count puts the most rows first. The
// order belongs to the card and only moves the rows of the list.
//
// A column with too many levels to list but few enough to search (the server
// says, `GET /api/filter-levels`) gets a card of candidates: a search of its
// levels, the first 100 of which it lists by Name or Count to tick, and the
// ticked ones the list does not show, apart. The card switches to the text box
// (`部分一致`); only the mode shown sets its condition. A search or an order
// only fetches the candidates: the plot is not aggregated again.
import { draggedColumn } from "./builder.js";
import { attachDrag } from "./dragresize.js";
import { plainEnter } from "./keys.js";
import { levelText, MISSING } from "./names.js";
import { errorText } from "./notice.js";
import { Popup } from "./popup.js";
import { formatTemporal, isDateKind, parseTemporal } from "./temporal.js";

const TICK_SETTLE_MS = 400;
// Steps of a slider over the column's range.
const STEPS = 1000;
const SUMMARY_RETRY_MS = 300;
// Most candidates a search lists (`ddviz.compute.levelindex.LISTED`).
export const LISTED = 100;
const MS_PER_DAY = 86_400_000;
// Heights of the pane, lowest first: its head only (with the conditions in
// words), below the column list (55% of the left pane at most, or the height
// it was dragged to), and the whole left pane, the column list hidden. ▲ and
// ▼ step through them, as the table of the selected rows does.
const STATES = ["collapsed", "open", "maximized"];
const TITLES = {
  up: { collapsed: "フィルタ欄を開く", open: "左ペインいっぱいに広げる" },
  down: { open: "フィルタ欄を畳む（条件の要約は見出しに残る）", maximized: "元の高さに戻す" },
};
// Bounds of a dragged height: the pane's own, and what it leaves the column list.
const MIN_HEIGHT = 80;
const MIN_COLUMNS_HEIGHT = 160;
// The lowest height a card's list is dragged to (Issue #210).
const MIN_LIST_HEIGHT = 40;
// A card moves once the pointer is this far from where its head was pressed.
const REORDER_START = 5;
// While a card moves, the pane scrolls this fast with the pointer this near
// its top or bottom edge (half its height at most).
const EDGE = 32;
const EDGE_SPEED = 480;

// Returns where a card moved to `y` goes among the other cards, from their
// `{ top, height }` on the page in their order: before the first one whose
// middle is below `y`; after the last when there is none (0 with no other).
export function insertionIndex(rects, y) {
  const i = rects.findIndex((r) => y < r.top + r.height / 2);
  return i === -1 ? rects.length : i;
}

// Returns how fast (CSS px a second; up negative) the pane between `top`
// and `bottom` scrolls with the pointer at `y` while a card moves: within
// `EDGE` of an edge (half the height at most), else 0.
export function edgeSpeed(top, bottom, y) {
  const edge = Math.min(EDGE, (bottom - top) / 2);
  if (y < top || y > bottom) return 0;
  if (y < top + edge) return -EDGE_SPEED;
  if (y > bottom - edge) return EDGE_SPEED;
  return 0;
}

// Orders of the levels a card lists, by the "Sort by" menu.
const LEVEL_ORDERS = [
  ["name", "Name", "水準の名前の順（数字は値の順）"],
  ["count", "Count", "行数の多い順（同じ行数は名前の順）"],
];

// Returns the `[level, count]` pairs of a summary in `order`: "name" keeps
// them as given (the summary's natural order), "count" puts the larger
// counts first, keeping that order among equal counts.
export function sortLevels(levels, order) {
  const sorted = [...levels];
  if (order === "count") sorted.sort((a, b) => b[1] - a[1]);
  return sorted;
}

// The "Sort by" menu of a card. A press outside it closes it, except on the
// button that opened it, whose click closes it; another card's button
// switches to its own menu.
const levelMenu = new Popup();

// Closes the "Sort by" menu of a card; returns the button that opened it, or null.
function closeLevelMenu() {
  const button = levelMenu.anchor;
  levelMenu.close();
  return button;
}

// Opens the "Sort by" menu of a card under `button`, or above it when the
// window has no room below; `pick` gets the key.
function openLevelMenu(button, order, pick) {
  const menu = document.createElement("div");
  menu.className = "scale-menu sort-menu filter-sort-menu";
  const heading = document.createElement("div");
  heading.className = "scale-menu-heading";
  heading.textContent = "Sort by";
  menu.append(heading);
  for (const [key, text, title] of LEVEL_ORDERS) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scale-menu-item";
    row.dataset.order = key;
    row.classList.toggle("checked", order === key);
    row.textContent = text;
    row.title = title;
    row.addEventListener("click", () => {
      closeLevelMenu();
      pick(key);
    });
    menu.append(row);
  }
  levelMenu.openUnder(menu, button, { align: "left", gap: 2 });
}

// Returns the row of a level to tick: its box, its name and its rows (none
// when `count` is null); `toggle` gets whether it is ticked. `missing` tells
// that the card has the row of the missing values (`MISSING`), for a real
// "(null)" text to be marked as text (`levelText`).
function levelRow(level, count, checked, toggle, missing = false) {
  const label = document.createElement("label");
  label.className = "filter-level";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = checked;
  box.addEventListener("change", () => toggle(box.checked));
  const text = document.createElement("span");
  text.className = "filter-level-name";
  const name = levelText(level, missing ? [MISSING] : []);
  text.textContent = name;
  text.title = name;
  label.append(box, text);
  if (count !== null) {
    const num = document.createElement("span");
    num.className = "filter-level-count";
    num.textContent = count.toLocaleString();
    label.append(num);
  }
  return label;
}

// Returns a number short enough for the pane.
export function formatNumber(value) {
  if (!Number.isFinite(value)) return String(value);
  // An integer of 16 digits or more (1e300 too) takes 4 significant digits,
  // as the others: with every digit it ran out of the card.
  if (Math.abs(value) >= 1e15) return value.toPrecision(4);
  if (Number.isInteger(value)) return value.toLocaleString();
  return String(Number(value.toPrecision(4)));
}

// Returns a bound of a numeric card: a datetime, date or time column's as
// such (`temporal.js`), else as `formatNumber`.
function formatBound(card, value) {
  return formatTemporal(card.summary?.temporal, value) ?? formatNumber(value);
}

// Returns conditions in the order of their columns (JavaScript's comparison of
// strings, apart from the locale): the order of the cards only shows.
function byColumn(list) {
  return [...list].sort((a, b) => (a.column < b.column ? -1 : a.column > b.column ? 1 : 0));
}

// Returns a key of conditions of the local filter
// (`ddviz.server.plan.parse_filters`), from the page's or from a result's
// meta; conditions in another order have the same key.
export function filtersKey(list) {
  return JSON.stringify(
    byColumn(list).map((f) => [f.column, f.range ?? null, f.levels ?? null, f.contains ?? null, f.nulls ?? false]),
  );
}

// Returns how a card sets its condition: "range" for a numeric column,
// "pick" for the candidates ticked (a card of candidates in its "pick"
// mode), "contains" for the text its values contain, "listed" for the
// levels it lists; null before its summary comes.
export function cardKind(card) {
  if (!card.summary) return null;
  if (card.numeric) return "range";
  if (card.candidates && card.mode === "pick") return "pick";
  if (card.summary.levels === null) return "contains";
  return "listed";
}

// Returns whether a card shows the row of its column's missing values
// (`(null)`): the column has some (null, or NaN in a float column).
function hasNulls(card) {
  return (card.summary?.nulls ?? 0) >= 1;
}

// Returns whether a card's `(null)` row is ticked in the way it sets its
// condition (`cardKind`): its missing rows are kept besides the rows its
// values keep. False for a column without missing values.
function keepsNulls(card) {
  const kind = cardKind(card);
  return kind !== null && hasNulls(card) && card.nulls[kind];
}

// Returns whether a numeric card's range is narrower than the column's.
function narrowed(card) {
  return card.range !== null && (card.range[0] > card.summary.min || card.range[1] < card.summary.max);
}

// Returns a card's state that sets its condition, as `FilterPane.snapshot`
// keeps it.
function cardState(card) {
  return {
    card,
    range: card.range && [...card.range],
    levels: new Set(card.levels),
    contains: card.contains,
    nulls: { ...card.nulls },
    mode: card.mode,
    query: card.query,
    order: card.order,
  };
}

// Returns the count of a card's ticked levels: `picked` of `total` and the
// missing rows (`nulls`), or `idle` with nothing ticked.
function pickedText(picked, total, nulls, idle) {
  if (picked) return `${picked.toLocaleString()} / ${total} 水準${nulls ? "と null " : ""}を選択`;
  return nulls ? "null を選択" : idle;
}

// Returns the row of a card's count of ticked levels and its button that
// unticks them all.
function clearBar(title) {
  const bar = document.createElement("div");
  bar.className = "filter-note";
  const counter = document.createElement("span");
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "filter-reset";
  clear.textContent = "すべて外す";
  clear.title = title;
  bar.append(counter, clear);
  return { bar, counter, clear };
}

// Returns a new card of the column `name`, before its summary comes.
function newCard(name, numeric) {
  return {
    name,
    numeric,
    summary: null,
    range: null,
    levels: new Set(),
    contains: "",
    // The tick of the `(null)` row in each way the card sets its
    // condition (`cardKind`): a card of candidates keeps one per mode.
    nulls: { range: true, pick: false, contains: false, listed: false },
    order: "name",
    element: null,
    listHeight: null,
    candidates: null,
    mode: "pick",
    query: "",
    draft: "",
    shown: null,
    seq: 0,
    loading: false,
    failure: null,
  };
}

// Returns the state of the pane `snapshot` (`FilterPane.snapshot`) as JSON
// values, for the drawing settings of undo and redo (`history.js`): each
// card by its column, its ticked levels sorted, and its range null when it
// is the column's whole range (or not known yet), as it sets no condition.
export function filterSettings(snapshot) {
  return snapshot.map(({ card, range, levels, contains, nulls, mode, query, order }) => {
    const whole = card.summary?.numeric && range && range[0] <= card.summary.min && range[1] >= card.summary.max;
    return {
      name: card.name,
      numeric: card.numeric,
      range: range && !whole ? [...range] : null,
      levels: [...levels].sort((a, b) => {
        const x = JSON.stringify(a);
        const y = JSON.stringify(b);
        return x < y ? -1 : x > y ? 1 : 0;
      }),
      contains,
      nulls: { ...nulls },
      mode,
      query,
      order,
    };
  });
}

export class FilterPane {
  // `root` is the pane (`#filters`); `onChange` gets the conditions after each
  // committed change; `onSummary` gets the summary text whenever it changes.
  // `onCards(edit)` is called after a card is added, removed or moved: a
  // change of the cards themselves, which the drawing settings keep;
  // `edit(entries)` returns the cards of the drawing settings `entries`
  // (`filterSettings`) with that change alone.
  constructor(root, onChange, onSummary, onCards = () => {}) {
    this.root = root;
    this.list = root.querySelector(".filter-list");
    // What scrolls the cards (the list itself in a page without it).
    this.body = root.querySelector(".filter-body") ?? this.list;
    this.head = root.querySelector(".filter-summary");
    // The dashed "Drop a column to filter": shown only while no card is
    // there (render). The whole pane takes a drop either way (attachDrop).
    this.drop = root.querySelector(".filter-drop");
    this.up = root.querySelector(".filter-up");
    this.down = root.querySelector(".filter-down");
    this.state = "open";
    this.tip = document.getElementById("drop-tip");
    this.onChange = onChange;
    this.onSummary = onSummary;
    this.onCards = onCards;
    // One card per column, in the order shown (added last at the end, moved
    // by its head): `{name, numeric, summary,
    // range, levels, contains, element}`; `range` is [lo, hi], `levels` the
    // ticked set, `contains` the text of a column with too many levels. A
    // card of candidates also has `candidates` (`null` until the first
    // answer, `false` for a column with too many levels to search, else the
    // answer), its `mode` ("pick" or "contains"), the `query` sent last, the
    // `draft` in its search box, `shown` (the query and order of the
    // candidates listed), `seq` (the number of its request sent last, for
    // dropping older answers), `loading` and `failure`. `listHeight` is the
    // height its list of levels (or of candidates) was dragged to, null
    // before: it only shows, and stays until the card is removed.
    this.cards = [];
    // The card being moved by its head (`attachReorder`), as `{ cancel }`.
    this.reorder = null;
    this.committed = "[]";
    // The state of the conditions sent last (`commit`).
    this.sent = [];
    // The card of each column added while the page is open, removed or not:
    // the drawing settings (`applySettings`) bring it back with its summary.
    this.known = new Map();
    // The cards of drawing settings whose summaries load before they are
    // applied (`prepare`): not in the pane yet, their answers are kept.
    this.preparing = new Set();
    this.timer = null;
    this.up.addEventListener("click", () => this.step(1));
    this.down.addEventListener("click", () => this.step(-1));
    // A double click on the head steps once: up from folded, else down. A
    // button's own double click has already stepped by its two clicks.
    root.querySelector(".filter-head").addEventListener("dblclick", (event) => {
      if (event.target.closest("button")) return;
      this.step(this.state === "collapsed" ? 1 : -1);
    });
    this.attachResize(root.querySelector(".filter-resize"));
    this.attachDrop();
    this.setState("open");
    this.render();
  }

  // Raises (1) or lowers (-1) the pane by one of `STATES`.
  step(by) {
    const i = STATES.indexOf(this.state) + by;
    if (i >= 0 && i < STATES.length) this.setState(STATES[i]);
  }

  // Only the pane's height changes: the cards, the conditions, the column
  // list and the plot area stay as they are, so nothing is sent or drawn again.
  setState(state) {
    if (state === "collapsed") this.cancelReorder();
    this.state = state;
    this.root.classList.toggle("collapsed", state === "collapsed");
    this.root.classList.toggle("maximized", state === "maximized");
    this.up.disabled = state === "maximized";
    this.down.disabled = state === "collapsed";
    this.up.title = TITLES.up[state] ?? "";
    this.down.title = TITLES.down[state] ?? "";
  }

  // Drags the pane's top edge: up makes it taller, down lower, leaving the
  // column list `MIN_COLUMNS_HEIGHT`. The height dragged to is kept apart from
  // the state (`--filter-height` with the class `sized`), for going back to
  // it from either end; CSS fits it into a shorter left pane. A drag down from
  // the maximized pane brings it back to open; a click alone changes nothing.
  attachResize(handle) {
    attachDrag(handle, (event) => {
      const startY = event.clientY;
      const startHeight = this.root.offsetHeight;
      // The head and the handle always fit.
      const floor = this.root.querySelector(".filter-head").offsetHeight + handle.offsetHeight;
      const limit = Math.max(this.root.parentElement.clientHeight - MIN_COLUMNS_HEIGHT, floor);
      const lowest = Math.min(MIN_HEIGHT, limit);
      this.root.style.setProperty("--filter-floor", `${floor}px`);
      return {
        move: (e) => {
          if (this.state === "maximized") {
            if (e.clientY <= startY) return;
            this.setState("open");
          }
          const height = Math.min(Math.max(startHeight + startY - e.clientY, lowest), limit);
          this.root.style.setProperty("--filter-height", `${height}px`);
          this.root.classList.add("sized");
        },
        end: () => {},
      };
    });
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
      if (this.cards.some((c) => c.name === column.name)) return;
      this.add(column);
      column.placed?.();
    });
  }

  showTip(text) {
    this.tip.textContent = text ?? "";
    this.tip.hidden = !text;
  }

  // Whether the pane has a card of the column `name`.
  has(name) {
    return this.cards.some((c) => c.name === name);
  }

  add({ name, numeric }) {
    if (this.cards.some((c) => c.name === name)) return;
    this.cancelReorder();
    const card = newCard(name, numeric);
    this.known.set(name, card);
    this.cards.push(card);
    // A new card sets no condition: the state sent has it, so that a request
    // sent now goes back to it (`RestorePoint`).
    this.sent = [...this.sent, cardState(card)];
    // A folded pane opens to show the card; a maximized one stays so.
    if (this.state === "collapsed") this.setState("open");
    this.render();
    this.loadSummary(card);
    const entry = filterSettings([cardState(newCard(name, numeric))])[0];
    this.onCards((entries) => (entries.some((e) => e.name === name) ? entries : [...entries, entry]));
  }

  remove(card) {
    this.cancelReorder();
    this.cards = this.cards.filter((c) => c !== card);
    // An answer to its request on the way is dropped.
    card.seq++;
    // Gone from the state sent too, even when its conditions stay the same
    // (a card without a condition) and nothing is sent.
    this.sent = this.sent.filter((s) => s.card !== card);
    this.render();
    this.commit();
    // A card that sets a condition there stays: its removal is a new
    // condition, committed when its result is drawn.
    this.onCards((entries) => entries.filter((e) => e.name !== card.name || this.hasCondition(e)));
  }

  // Whether the answers to a card's requests are kept: it is in the pane, or
  // its drawing settings are being prepared (`prepare`).
  holds(card) {
    return this.cards.includes(card) || this.preparing.has(card);
  }

  // Loads a card's summary, then the first candidates of a card that searches
  // them (`searches`).
  async loadSummary(card) {
    for (;;) {
      const response = await fetch(`/api/summary?${new URLSearchParams({ column: card.name })}`);
      if (!this.holds(card)) return;
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
      if (this.searches(card)) await this.loadCandidates(card);
      return;
    }
  }

  // Whether a card searches the candidates of its levels: a categorical
  // column with too many levels to list, unless the server found too many
  // to search.
  searches(card) {
    return !card.numeric && card.summary?.levels === null && card.candidates !== false;
  }

  // Whether a card's condition is its ticked candidates.
  picks(card) {
    return cardKind(card) === "pick";
  }

  // Fetches the candidates of a card for its `query` and `order`. An answer
  // to a card removed since, or to an older request of the card, is dropped.
  async loadCandidates(card) {
    const seq = ++card.seq;
    const asked = { query: card.query, order: card.order };
    card.loading = true;
    card.failure = null;
    this.showCandidates(card);
    let found = null;
    let failure = null;
    try {
      const params = new URLSearchParams({ column: card.name, q: asked.query, order: asked.order });
      const response = await fetch(`/api/filter-levels?${params}`);
      if (response.ok) found = await response.json();
      else failure = errorText(await response.text(), response.status);
    } catch (error) {
      failure = String(error);
    }
    if (!this.holds(card) || seq !== card.seq) return;
    card.loading = false;
    if (failure !== null) {
      card.failure = failure;
      this.showCandidates(card);
      return;
    }
    const first = card.candidates === null;
    if (found.levels === null) {
      // Too many to search: the card filters by the text its values contain.
      card.candidates = false;
      card.mode = "contains";
      card.summary = { ...card.summary, n_levels: found.n_levels };
      card.levels.clear();
      this.renderCard(card);
      return;
    }
    card.candidates = found;
    card.shown = asked;
    if (first) this.renderCard(card);
    else this.showCandidates(card);
  }

  // Shows the candidates of a card, its fetching or its failure. A card in
  // the text box mode shows them when it switches back, so that the box
  // being typed in stays.
  showCandidates(card) {
    if (card.refresh) card.refresh();
    else if (!(card.candidates && card.mode === "contains")) this.renderCard(card);
  }

  // Draws one card again, keeping the others (and their boxes' focus).
  renderCard(card) {
    if (card.element?.isConnected) {
      this.cancelReorder();
      card.element.replaceWith(this.cardElement(card));
    }
    this.updateSummary();
  }

  // Returns the conditions of the cards that leave rows out, for the server
  // (`ddviz.server.plan.parse_filters`).
  conditions() {
    const out = [];
    for (const card of this.cards) {
      if (!this.isActive(card)) continue;
      const kind = cardKind(card);
      const also = keepsNulls(card) ? { nulls: true } : {};
      if (kind === "range") {
        if (narrowed(card)) out.push({ column: card.name, range: [...card.range], ...also });
        else out.push({ column: card.name, nulls: false });
      } else if (kind === "contains" ? card.contains === "" : card.levels.size === 0) {
        out.push({ column: card.name, nulls: true });
      } else if (kind === "contains") {
        out.push({ column: card.name, contains: card.contains, ...also });
      } else {
        out.push({ column: card.name, levels: [...card.levels].sort(), ...also });
      }
    }
    return byColumn(out);
  }

  isActive(card) {
    const kind = cardKind(card);
    if (kind === null) return false;
    if (kind === "range") return narrowed(card) || (hasNulls(card) && !card.nulls.range);
    if (kind === "contains") return card.contains !== "" || keepsNulls(card);
    return card.levels.size > 0 || keepsNulls(card);
  }

  // Returns the conditions in a few words: "g1: 3/10、x: −2〜5、id: 「a1」を含む",
  // with "+null" for a card that keeps the missing rows too, "g1: null" for
  // one that keeps only them and "x: null を除く" for a numeric card that
  // only leaves them out.
  summaryText() {
    return this.cards
      .filter((card) => this.isActive(card))
      .map((card) => {
        const kind = cardKind(card);
        const plus = keepsNulls(card) ? "+null" : "";
        if (kind === "range") {
          if (!narrowed(card)) return `${card.name}: null を除く`;
          return `${card.name}: ${formatBound(card, card.range[0])}〜${formatBound(card, card.range[1])}${plus}`;
        }
        let values = null;
        if (kind === "contains") {
          if (card.contains !== "") values = `「${card.contains}」を含む`;
        } else if (card.levels.size > 0) {
          const total = kind === "pick" ? card.candidates.n_levels : card.summary.levels.length;
          values = `${card.levels.size}/${total}`;
        }
        return values === null ? `${card.name}: null` : `${card.name}: ${values}${plus}`;
      })
      .join("、");
  }

  // Sends the conditions now, unless they are the ones sent last. The state
  // they come from is kept as `sent` (`snapshot`), for a failed request to
  // go back to (`RestorePoint`).
  commit() {
    clearTimeout(this.timer);
    this.updateSummary();
    const conditions = this.conditions();
    const key = JSON.stringify(conditions);
    if (key === this.committed) return;
    this.committed = key;
    this.sent = this.snapshot();
    this.onChange(conditions);
  }

  // Returns the state of the pane that sets the conditions: its cards in
  // their order, and each one's range, ticked levels and text; a card of
  // candidates' mode, and the query and order of its candidates. What only
  // shows (the order of a listed card's levels) is not part of it.
  snapshot() {
    return this.cards.map(cardState);
  }

  // Puts the cards back as `snapshot()` had them: a card removed since comes
  // back as it was before, with what it showed, and one added since goes; a
  // card kept keeps what it shows. Ticks waiting to be sent are dropped and
  // nothing is sent (`onChange` is not called); the summary follows.
  //
  // A card of candidates gets back its mode and the query and order of its
  // candidates, fetched again when they differ from those listed or when the
  // card was removed while they loaded.
  restore(snapshot) {
    clearTimeout(this.timer);
    this.timer = null;
    const refetch = [];
    this.cards = snapshot.map(({ card, range, levels, contains, nulls, mode, query, order }) => {
      // A card whose summary came after the snapshot has its whole range.
      const whole = card.summary?.numeric && card.summary.min !== null ? [card.summary.min, card.summary.max] : null;
      card.range = range ? [...range] : whole;
      card.levels = new Set(levels);
      card.contains = contains;
      card.nulls = { ...nulls };
      if (this.searches(card)) {
        card.mode = mode;
        card.query = query;
        card.draft = query;
        card.order = order;
        const listed = card.shown && card.shown.query === query && card.shown.order === order;
        if (card.summary && (card.loading || (card.candidates && !listed))) refetch.push(card);
      }
      return card;
    });
    this.committed = JSON.stringify(this.conditions());
    this.sent = snapshot;
    this.render();
    // A card removed while its summary loaded stopped loading it.
    for (const card of this.cards) {
      if (!card.summary && !card.error) this.loadSummary(card);
    }
    for (const card of refetch) this.loadCandidates(card);
  }

  // Puts the cards back as the drawing settings `settings` (`filterSettings`)
  // had them, as `restore` does: nothing is sent. A card of a column added
  // before is that card again, with its summary; another one is new, and
  // loads its summary.
  applySettings(settings) {
    const snapshot = settings.map(({ name, numeric, range, levels, contains, nulls, mode, query, order }) => {
      const card = this.known.get(name) ?? this.knownCard({ name, numeric, mode, query, order });
      return { card, range, levels: new Set(levels), contains, nulls, mode, query, order };
    });
    this.restore(snapshot);
  }

  // Returns a new card of the drawing settings' card `entry`, known from now
  // on (`known`), with its mode and the query and order of its candidates.
  knownCard({ name, numeric, mode, query, order }) {
    const card = newCard(name, numeric);
    Object.assign(card, { mode, query, draft: query, order });
    this.known.set(name, card);
    return card;
  }

  // Loads what the cards of the drawing settings `settings` (`filterSettings`)
  // need to set their conditions before they are applied (`applySettings`):
  // the summary of each column without a card yet, and the first candidates
  // of the query and order of a card that searches them. A card without its
  // summary sets no condition (`cardKind`), nor one of candidates without
  // them, so the conditions taken right after the settings are applied
  // (`conditions`) would lack theirs (Issue #342). Throws when one of them
  // cannot be loaded: the settings would be drawn without its condition.
  async prepare(settings) {
    const cards = settings.filter(({ name }) => !this.known.has(name)).map((entry) => this.knownCard(entry));
    for (const card of cards) this.preparing.add(card);
    try {
      await Promise.all(cards.map((card) => this.loadSummary(card)));
    } finally {
      for (const card of cards) this.preparing.delete(card);
    }
    for (const card of cards) {
      if (card.summary === null) throw new Error(`フィルタの列 ${card.name} の要約を読めませんでした：${errorText(card.error ?? "")}`);
      if (card.failure !== null) throw new Error(`フィルタの列 ${card.name} の候補を読めませんでした：${card.failure}`);
    }
  }

  // Returns whether the card of the drawing settings `entry` (`filterSettings`)
  // sets a condition, with the summary of its column's card.
  hasCondition(entry) {
    const card = this.known.get(entry.name);
    if (!card?.summary) return false;
    const whole = card.summary.numeric && card.summary.min !== null ? [card.summary.min, card.summary.max] : null;
    return this.isActive({
      ...card,
      range: entry.range ?? whole,
      levels: new Set(entry.levels),
      contains: entry.contains,
      nulls: { ...entry.nulls },
      mode: entry.mode,
    });
  }

  // Returns the cards of the drawing settings `entries` (`filterSettings`)
  // as the pane has them now, in its order: a card of `entries` as it is
  // there, a card added since without a condition, and a card of `entries`
  // removed since only when it sets a condition there (its removal is a new
  // condition, committed when its result is drawn). The conditions are
  // those of `entries`: none of the pane's not drawn yet.
  withCards(entries) {
    const byName = new Map(entries.map((entry) => [entry.name, entry]));
    const out = this.cards.map((card) => byName.get(card.name) ?? filterSettings([cardState(newCard(card.name, card.numeric))])[0]);
    entries.forEach((entry, i) => {
      if (!this.cards.some((card) => card.name === entry.name) && this.hasCondition(entry)) {
        out.splice(Math.min(i, out.length), 0, entry);
      }
    });
    return structuredClone(out);
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
    this.cancelReorder();
    this.list.replaceChildren(...this.cards.map((card) => this.cardElement(card)));
    if (this.drop) this.drop.hidden = this.cards.length > 0;
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
    head.append(type, name);
    if (!card.numeric && card.summary && (card.summary.levels !== null || this.picks(card))) {
      const sort = document.createElement("button");
      sort.type = "button";
      sort.className = "filter-card-sort";
      sort.textContent = "…";
      sort.title = "水準の並べ替え";
      sort.setAttribute("aria-label", "Sort by");
      sort.addEventListener("click", () => {
        if (closeLevelMenu() === sort) return;
        openLevelMenu(sort, card.order, (picked) => {
          if (this.picks(card)) {
            // The candidates of the query sent last, in the new order.
            if (picked === card.order && !card.failure) return;
            card.order = picked;
            this.loadCandidates(card);
            return;
          }
          card.order = picked;
          card.arrange?.();
        });
      });
      head.append(sort);
    }
    head.append(close);
    head.title = "ドラッグでカードの順番を変える";
    this.attachReorder(card, head);
    element.append(head);
    const body = document.createElement("div");
    body.className = "filter-card-body";
    element.append(body);
    card.levelList = null;
    if (card.error) {
      body.textContent = `エラー: ${card.error}`;
    } else if (!card.summary) {
      body.textContent = "集計中…";
    } else if (card.numeric) {
      this.numericBody(card, body);
    } else {
      this.levelBody(card, body);
    }
    if (card.levelList) element.append(this.listHandle(card));
    return element;
  }

  // Shows a card's list of levels (`levelList`) at the height it was dragged
  // to; before a drag, as high as its rows, 180px at most (CSS).
  fitList(card) {
    const list = card.levelList;
    const sized = card.listHeight !== null;
    list.classList.toggle("sized", sized);
    list.style.height = sized ? `${card.listHeight}px` : "";
  }

  // The bottom edge of a card that lists levels to tick: dragging it down
  // makes the list taller, up lower, `MIN_LIST_HEIGHT` at least and with no
  // upper bound (the pane scrolls). It starts from the height the list
  // shows; a click alone changes nothing. Only the list changes: nothing is
  // sent.
  listHandle(card) {
    const handle = document.createElement("div");
    handle.className = "filter-list-resize";
    handle.title = "ドラッグで一覧の高さを変える";
    attachDrag(handle, (event) => {
      const list = card.levelList;
      const startY = event.clientY;
      const startHeight = list.hidden ? 0 : list.getBoundingClientRect().height;
      return {
        move: (e) => {
          // The card was drawn again or removed since: the drag is over.
          if (!list.isConnected || card.levelList !== list) return;
          if (card.listHeight === null && e.clientY === startY) return;
          card.listHeight = Math.max(MIN_LIST_HEIGHT, startHeight + e.clientY - startY);
          list.hidden = false;
          this.fitList(card);
        },
        end: () => {},
      };
    });
    return handle;
  }

  // Ends the move of a card, if one moves, leaving the cards in their order.
  cancelReorder() {
    this.reorder?.cancel();
  }

  // Moves a card by its head, apart from its buttons: a press of the primary
  // button and a move of `REORDER_START` px start it. A copy of the card
  // follows the pointer and a line shows where it goes (`insertionIndex`
  // among the other cards); letting go within the pane puts it there.
  // Letting go outside the pane, Escape or pointercancel leave the order as
  // it was, as do a card added, removed or drawn again and the pane folded
  // meanwhile (`cancelReorder`). With the pointer near the pane's top or
  // bottom edge the pane scrolls (`edgeSpeed`). Only the order of the cards
  // and of the summary changes: their elements move as they are, nothing is
  // sent and no answer waited for is dropped.
  attachReorder(card, head) {
    head.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest("button") || this.reorder) return;
      const startX = event.clientX;
      const startY = event.clientY;
      const pointerId = event.pointerId;
      head.setPointerCapture(pointerId);
      let x = startX;
      let y = startY;
      let moving = false;
      let preview = null;
      let line = null;
      let frame = 0;
      let last = null;
      // The cards but the one moved, and where it goes among them.
      const others = () => this.cards.filter((c) => c !== card);
      let index = this.cards.indexOf(card);
      const rect = card.element.getBoundingClientRect();
      const place = () => {
        const rest = others();
        const rects = rest.map((c) => c.element.getBoundingClientRect());
        index = insertionIndex(rects, y);
        const box = this.list.getBoundingClientRect();
        const at =
          index < rects.length
            ? rects[index].top - 3
            : rects.length
              ? rects[rects.length - 1].bottom + 3
              : card.element.getBoundingClientRect().top;
        line.style.cssText = `left: ${box.left + 8}px; width: ${Math.max(box.width - 16, 0)}px; top: ${at - 1}px`;
        preview.style.top = `${rect.top + y - startY}px`;
      };
      const scroll = (time) => {
        frame = 0;
        const box = this.body.getBoundingClientRect();
        const inside = x >= box.left && x <= box.right;
        const speed = inside ? edgeSpeed(box.top, box.bottom, y) : 0;
        if (speed === 0) {
          last = null;
          return;
        }
        if (last !== null) {
          const most = this.body.scrollHeight - this.body.clientHeight;
          const to = Math.min(Math.max(this.body.scrollTop + (speed * (time - last)) / 1000, 0), most);
          this.body.scrollTop = to;
          place();
        }
        last = time;
        frame = requestAnimationFrame(scroll);
      };
      const follow = () => {
        if (!frame) frame = requestAnimationFrame(scroll);
      };
      const begin = () => {
        moving = true;
        closeLevelMenu();
        preview = card.element.cloneNode(true);
        preview.classList.add("filter-card-preview");
        preview.style.left = `${rect.left}px`;
        preview.style.width = `${rect.width}px`;
        line = document.createElement("div");
        line.className = "filter-card-line";
        document.body.append(preview, line);
        document.body.classList.add("filter-reordering");
        card.element.classList.add("moving");
        place();
      };
      const finish = (put) => {
        this.reorder = null;
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", cancel);
        window.removeEventListener("keydown", key, true);
        if (head.hasPointerCapture?.(pointerId)) head.releasePointerCapture(pointerId);
        cancelAnimationFrame(frame);
        frame = 0;
        if (!moving) return;
        preview.remove();
        line.remove();
        document.body.classList.remove("filter-reordering");
        card.element.classList.remove("moving");
        if (put) this.moveCard(card, index);
      };
      const move = (e) => {
        if (e.pointerId !== pointerId) return;
        x = e.clientX;
        y = e.clientY;
        if (!moving) {
          if (Math.hypot(x - startX, y - startY) < REORDER_START) return;
          begin();
        }
        place();
        follow();
      };
      const up = (e) => {
        if (e.pointerId !== pointerId) return;
        const box = this.body.getBoundingClientRect();
        const within = e.clientX >= box.left && e.clientX <= box.right && e.clientY >= box.top && e.clientY <= box.bottom;
        finish(within);
      };
      const cancel = (e) => {
        if (e.pointerId === pointerId) finish(false);
      };
      const key = (e) => {
        if (e.key === "Escape") finish(false);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", cancel);
      window.addEventListener("keydown", key, true);
      this.reorder = { cancel: () => finish(false) };
    });
  }

  // Puts a card at `index` among the other cards, moving its element as it
  // is; the summary follows the new order. The same place changes nothing.
  moveCard(card, index) {
    if (this.cards.indexOf(card) === index) return;
    const rest = this.cards.filter((c) => c !== card);
    rest.splice(index, 0, card);
    this.cards = rest;
    // An element put elsewhere loses the scroll of its lists (and its focus,
    // unless `moveBefore` keeps them): the lists get theirs back.
    const lists = [...card.element.querySelectorAll(".filter-levels")].map((e) => [e, e.scrollTop]);
    const next = rest[index + 1]?.element ?? null;
    if (this.list.moveBefore) this.list.moveBefore(card.element, next);
    else this.list.insertBefore(card.element, next);
    for (const [e, top] of lists) e.scrollTop = top;
    this.updateSummary();
    // In `entries`, the card goes before the card now after it, or last.
    const after = rest[index + 1]?.name;
    this.onCards((entries) => {
      const entry = entries.find((e) => e.name === card.name);
      if (!entry) return entries;
      const out = entries.filter((e) => e !== entry);
      const at = out.findIndex((e) => e.name === after);
      out.splice(at < 0 ? out.length : at, 0, entry);
      return out;
    });
  }

  numericBody(card, body) {
    const { min, max, integer, temporal } = card.summary;
    // A datetime, date or time column's bounds are typed as text; its
    // values are milliseconds (`ddviz.compute.temporal`).
    const dates = isDateKind(temporal);
    const toText = (v) => (dates ? formatTemporal(temporal, v) : String(v));
    const fromText = (text) => (dates ? parseTemporal(temporal, text) : text === "" ? null : Number(text));
    const note = document.createElement("div");
    note.className = "filter-note";
    note.textContent = `最小 ${formatBound(card, min)}　最大 ${formatBound(card, max)}`;
    body.append(note);
    if (min === null) {
      note.textContent = "有限な値が無い";
      if (hasNulls(card)) body.append(this.nullRow(card, () => {}));
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
        if (plainEnter(event)) input.blur();
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
    if (hasNulls(card)) body.append(this.nullRow(card, () => {}));
    show();
  }

  // Returns the `(null)` row of a card, ticked as the card keeps the missing
  // rows in the way it now sets its condition; a tick calls `after` (which
  // shows the count again) and sends the conditions soon, as a level's.
  nullRow(card, after) {
    const kind = cardKind(card);
    const row = levelRow(MISSING, card.summary.nulls, card.nulls[kind], (checked) => {
      card.nulls[kind] = checked;
      after();
      this.commitSoon();
    });
    row.classList.add("filter-null");
    return row;
  }

  levelBody(card, body) {
    const { levels } = card.summary;
    card.refresh = null;
    if (levels === null) {
      if (card.candidates === false) this.containsBody(card, body);
      else this.candidateBody(card, body);
      return;
    }
    const { bar, counter, clear } = clearBar("選んだ水準を外す（絞らない）");
    const list = document.createElement("div");
    list.className = "filter-levels";
    const labels = new Map();
    const boxes = levels.map(([level, n]) => {
      const label = levelRow(
        level,
        n,
        card.levels.has(level),
        (checked) => this.tickLevel(card, level, checked, update),
        hasNulls(card),
      );
      labels.set(level, label);
      return label.querySelector("input");
    });
    // The missing rows' row, the last in either order.
    const nullRow = hasNulls(card) ? this.nullRow(card, () => update()) : null;
    if (nullRow) boxes.push(nullRow.querySelector("input"));
    // Puts the rows in the card's order; the ticks stay as they are.
    card.arrange = () =>
      list.replaceChildren(
        ...sortLevels(levels, card.order).map(([level]) => labels.get(level)),
        ...(nullRow ? [nullRow] : []),
      );
    card.arrange();
    const update = () => {
      const picked = card.levels.size;
      const nulls = keepsNulls(card);
      counter.textContent = pickedText(picked, levels.length, nulls, `${levels.length} 水準（選ぶと絞る）`);
      clear.disabled = picked === 0 && !nulls;
    };
    clear.addEventListener("click", () => {
      card.levels.clear();
      card.nulls.listed = false;
      for (const box of boxes) box.checked = false;
      update();
      this.commit();
    });
    update();
    body.append(bar, list);
    card.levelList = list;
    this.fitList(card);
  }

  // A card of candidates: "候補を集計中…" until the first answer (or its
  // failure), then the switch of its modes over either the search of the
  // candidates or the text box.
  candidateBody(card, body) {
    if (card.candidates === null) {
      if (card.failure) body.append(this.failureLine(card));
      else body.textContent = "候補を集計中…";
      return;
    }
    body.append(this.modeSwitch(card));
    if (card.mode === "contains") {
      this.containsBody(card, body);
      return;
    }
    const { bar, counter, clear } = clearBar("選んだ水準を、候補に無いものも含めて外す（絞らない）");
    const search = document.createElement("div");
    search.className = "filter-search";
    const input = document.createElement("input");
    input.type = "text";
    input.value = card.draft;
    input.placeholder = "候補を検索";
    input.title = "空白で区切った語をすべて含む水準を探す（順不同。大文字と小文字を区別しない。空ならすべて）。Enter か「検索」で探す";
    const go = document.createElement("button");
    go.type = "button";
    go.className = "filter-reset filter-search-go";
    go.textContent = "検索";
    search.append(input, go);
    const status = document.createElement("div");
    status.className = "filter-candidates-status";
    const list = document.createElement("div");
    list.className = "filter-levels";
    const more = document.createElement("div");
    more.className = "filter-note filter-truncated";
    more.textContent = `先頭${LISTED}件を表示しています。検索語を絞ってください`;
    const picked = document.createElement("div");
    picked.className = "filter-picked";
    const pickedHead = document.createElement("div");
    pickedHead.className = "filter-note";
    pickedHead.textContent = "選択済み";
    const pickedList = document.createElement("div");
    pickedList.className = "filter-levels";
    picked.append(pickedHead, pickedList);

    const send = () => {
      card.query = input.value;
      card.draft = input.value;
      this.loadCandidates(card);
    };
    input.addEventListener("input", () => (card.draft = input.value));
    input.addEventListener("keydown", (event) => {
      // The Enter that commits an IME conversion keeps editing.
      if (!plainEnter(event)) return;
      event.preventDefault();
      send();
    });
    go.addEventListener("click", send);

    const count = () => {
      const size = card.levels.size;
      const nulls = keepsNulls(card);
      const total = card.candidates.n_levels.toLocaleString();
      counter.textContent = pickedText(size, total, nulls, `${total} 水準（検索して選ぶと絞る）`);
      clear.disabled = size === 0 && !nulls;
    };
    // A ticked level the candidates do not list, to untick.
    const showPicked = () => {
      const listed = new Set(card.candidates.levels.map(([level]) => level));
      const outside = [...card.levels].filter((level) => !listed.has(level));
      pickedList.replaceChildren(
        ...outside.map((level) =>
          levelRow(
            level,
            null,
            true,
            () => {
              card.levels.delete(level);
              showPicked();
              count();
              this.commitSoon();
            },
            hasNulls(card),
          ),
        ),
      );
      picked.hidden = outside.length === 0;
    };
    card.refresh = () => {
      const { levels, truncated } = card.candidates;
      status.replaceChildren();
      if (card.loading) status.textContent = "候補を取得中…";
      else if (card.failure) status.append(this.failureLine(card));
      else if (levels.length === 0) status.textContent = "一致する候補がありません";
      status.hidden = !status.hasChildNodes();
      list.classList.toggle("loading", card.loading);
      // The missing rows' row comes last whatever the search, past the
      // candidates it does not count.
      const missing = hasNulls(card);
      list.replaceChildren(
        ...levels.map(([level, n]) =>
          levelRow(level, n, card.levels.has(level), (checked) => this.tickLevel(card, level, checked, count), missing),
        ),
        ...(missing ? [this.nullRow(card, count)] : []),
      );
      // A list dragged to a height keeps it with no candidate.
      list.hidden = levels.length === 0 && !missing && card.listHeight === null;
      more.hidden = !truncated;
      showPicked();
      count();
    };
    clear.addEventListener("click", () => {
      card.levels.clear();
      card.nulls.pick = false;
      card.refresh();
      this.commit();
    });
    body.append(bar, search, status, list, more, picked);
    card.levelList = list;
    this.fitList(card);
    card.refresh();
  }

  // Ticks (`checked`) or unticks a level of a card, then calls `after` (which
  // shows the count again) and sends the conditions soon.
  tickLevel(card, level, checked, after) {
    if (checked) card.levels.add(level);
    else card.levels.delete(level);
    after();
    this.commitSoon();
  }

  // The error of a card's candidates, with a button that asks again.
  failureLine(card) {
    const line = document.createElement("div");
    line.className = "filter-error";
    const text = document.createElement("span");
    text.textContent = `エラー: ${card.failure}`;
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "filter-reset";
    retry.textContent = "再試行";
    retry.title = "同じ検索語と並び順で候補を取り直す";
    retry.addEventListener("click", () => this.loadCandidates(card));
    line.append(text, retry);
    return line;
  }

  // The switch between ticking candidates and typing the text the values
  // contain; each mode keeps its own state.
  modeSwitch(card) {
    const bar = document.createElement("div");
    bar.className = "filter-mode";
    bar.setAttribute("role", "group");
    for (const [mode, text, title] of [
      ["pick", "水準を選択", "水準を検索してチェックした値と一致する行だけを残す"],
      ["contains", "部分一致", "入力した語をすべて含む行だけを残す"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.mode = mode;
      button.textContent = text;
      button.title = title;
      button.setAttribute("aria-pressed", String(card.mode === mode));
      button.addEventListener("click", () => {
        if (card.mode === mode) return;
        card.mode = mode;
        this.renderCard(card);
        this.commit();
      });
      bar.append(button);
    }
    return bar;
  }

  // A column with too many levels to list is filtered by the text its kept
  // values contain: every word of it, in any order, literally and ignoring
  // case (`ddviz.shared.keywords`); a blank box keeps every row.
  containsBody(card, body) {
    const { n_levels: count } = card.summary;
    const note = document.createElement("div");
    note.className = "filter-note";
    if (card.candidates) {
      note.textContent = `${card.candidates.n_levels.toLocaleString()} 水準から部分一致で絞る`;
    } else {
      note.textContent = `水準が多すぎる（約 ${count.toLocaleString()} 個）ため、部分一致で絞る`;
    }
    const bar = document.createElement("div");
    bar.className = "filter-contains";
    const input = document.createElement("input");
    input.type = "text";
    input.value = card.contains;
    input.placeholder = "含む文字列";
    input.title = "空白で区切った語をすべて含む行だけを残す（順不同。大文字と小文字を区別しない。空なら絞らない）";
    input.addEventListener("change", () => {
      card.contains = input.value.trim();
      this.commit();
    });
    input.addEventListener("keydown", (event) => {
      // The Enter that commits an IME conversion keeps editing.
      if (plainEnter(event)) input.blur();
    });
    bar.append(input);
    body.append(note, bar);
    if (hasNulls(card)) body.append(this.nullRow(card, () => {}));
  }
}

// Where the filter pane goes back to when a change of the filter fails: the
// state of the pane (`FilterPane.snapshot`) that the result drawn last was
// aggregated with. A request keeps the state it is sent with as a candidate
// (`propose`), which becomes the point once its result is drawn (`confirm`),
// as the figure does; a candidate older than the point never replaces it.
export class RestorePoint {
  constructor(state = []) {
    this.state = state;
    this.order = 0;
    this.confirmed = 0;
  }

  // Returns the candidate of a request sent with the pane's state `state`.
  propose(state) {
    return { state, order: ++this.order };
  }

  // Makes a candidate the point, its request's result being drawn, unless a
  // later one already is.
  confirm(candidate) {
    if (candidate.order <= this.confirmed) return;
    this.confirmed = candidate.order;
    this.state = candidate.state;
  }

  // Returns the state to go back to: that of the result drawn last.
  point() {
    return this.state;
  }
}
