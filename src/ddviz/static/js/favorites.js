// The favorites of the drawing settings (docs/spec.md, "お気に入り"): up to
// three settings saved by hand with a thumbnail, recalled from the pull-down
// of a star button right of redo (in the window's title bar, or in a browser
// in the row above the zones). The page alone keeps them: a new graph or a
// reload drops them. `Favorites` is the pure list; `FavoritesMenu` the
// button and its pull-down; the page (`app.js`) captures and applies the
// settings.

import { settingsKey } from "./history.js";
import { Popup, menuSeparator, placeUnder } from "./popup.js";

// The most favorites kept.
export const MAX_FAVORITES = 3;

// Returns the time of `date` as `HH:MM`.
export function timeText(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// The favorites, in the order saved: `{settings, key, thumbnail, time}`,
// where `key` is the settings' `settingsKey` (the thumbnail and the time are
// not compared).
export class Favorites {
  constructor(max = MAX_FAVORITES) {
    this.max = max;
    this.items = [];
  }

  get full() {
    return this.items.length >= this.max;
  }

  // Adds `settings` at the end; returns whether it was added (not when full).
  add(settings, thumbnail = null, time = new Date()) {
    if (this.full) return false;
    this.items.push(item(settings, thumbnail, time));
    return true;
  }

  // Replaces the favorite `index` with `settings`, at the same place;
  // returns whether there was one.
  replace(index, settings, thumbnail = null, time = new Date()) {
    if (index < 0 || index >= this.items.length) return false;
    this.items[index] = item(settings, thumbnail, time);
    return true;
  }

  // Removes the favorite `index`; those after it move up.
  remove(index) {
    if (index < 0 || index >= this.items.length) return false;
    this.items.splice(index, 1);
    return true;
  }

  // Returns the index of the favorite whose settings are `settings`
  // (`settingsKey`: the order of the keys does not count), or -1.
  indexOf(settings) {
    const key = settingsKey(settings);
    return this.items.findIndex((favorite) => favorite.key === key);
  }
}

function item(settings, thumbnail, time) {
  return { settings: structuredClone(settings), key: settingsKey(settings), thumbnail, time };
}

const STAR =
  '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 1.8l1.85 3.95 4.3.5-3.18 2.95.85 4.25L8 11.3l-3.82 2.15.85-4.25L1.85 6.25l4.3-.5z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>';

export const SAVE_TEXT = "現在の描画を保存";
export const CHOOSE_TEXT = "上書きするものを選んでください";
export const EMPTY_TEXT = "保存済みの描画はありません";

// The star button and its pull-down. The page gives:
// - `shown()`: the settings of the step shown (the committed drawing
//   settings), or null;
// - `canSave()`: whether a figure is drawn and no plot is in flight;
// - `capture()`: `{settings, thumbnail}` of the figure shown, to save;
// - `apply(settings)`: recalls a favorite's settings;
// - `blocked()`: whether the button is off (a conversion's overlay shown).
export class FavoritesMenu {
  #popup;
  // Whether a save waits for the favorite it replaces to be picked.
  #choosing = false;

  constructor({ favorites, shown, canSave, capture, apply, blocked = () => false }) {
    this.favorites = favorites;
    this.shown = shown;
    this.canSave = canSave;
    this.capture = capture;
    this.apply = apply;
    this.blocked = blocked;
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.className = "favorites-button";
    this.button.innerHTML = STAR;
    this.button.title = "お気に入り";
    this.button.setAttribute("aria-label", "お気に入り");
    this.button.setAttribute("aria-haspopup", "menu");
    this.button.setAttribute("aria-expanded", "false");
    this.button.addEventListener("click", () => (this.#popup.element ? this.#popup.close() : this.open()));
    this.#popup = new Popup({
      onClose: () => {
        this.#choosing = false;
        this.button.setAttribute("aria-expanded", "false");
      },
    });
    // Escape while choosing goes back to the list, before the popup closes
    // on it (`Popup` listens on the window as it bubbles).
    window.addEventListener(
      "keydown",
      (event) => {
        if (event.key !== "Escape" || !this.#choosing || !this.#popup.element) return;
        event.stopImmediatePropagation();
        event.preventDefault();
        this.#choose(false);
      },
      { capture: true },
    );
  }

  // Puts the button right of `element` (redo); in the window's title bar
  // with the title bar's look.
  placeAfter(element) {
    if (element.closest("#titlebar")) this.button.classList.add("titlebar-favorites");
    element.after(this.button);
  }

  // Whether the pull-down is open.
  get isOpen() {
    return this.#popup.element !== null;
  }

  // Whether the current drawing can be saved: a figure drawn, no plot in
  // flight, and no favorite of the same settings.
  saveEnabled() {
    const shown = this.shown();
    return shown !== null && this.canSave() && this.favorites.indexOf(shown) < 0;
  }

  open() {
    if (this.blocked()) return;
    const menu = document.createElement("div");
    menu.className = "scale-menu favorites-menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", "お気に入り");
    menu.addEventListener("keydown", (event) => this.#key(event));
    this.#popup.openUnder(menu, this.button);
    this.button.setAttribute("aria-expanded", "true");
    this.#render(0);
  }

  close() {
    this.#popup.close();
  }

  // Follows a change of the page (a plot started or committed, a step
  // pushed): the save's state and the mark of the favorite shown. A save
  // that waits for its favorite stops when saving no longer can.
  refresh() {
    this.button.disabled = this.blocked();
    if (!this.#popup.element) return;
    if (this.blocked()) {
      this.close();
      return;
    }
    if (this.#choosing && !this.saveEnabled()) this.#choosing = false;
    this.#render();
  }

  // The items the arrows move among: the enabled buttons and the rows.
  #items() {
    const menu = this.#popup.element;
    return menu ? [...menu.querySelectorAll(".favorites-item:not(:disabled)")] : [];
  }

  // Draws the pull-down's content again, keeping the focus on the item of
  // its index (`focus`, by default the one focused), or on the first, and
  // places it under the button again at its new size: `Popup.openUnder`
  // placed it empty, and a row added or the choosing state changes its
  // height.
  #render(focus = null) {
    const menu = this.#popup.element;
    const before = this.#items().indexOf(document.activeElement);
    const at = focus ?? (before >= 0 ? before : null);
    menu.replaceChildren();
    if (this.#choosing) {
      const prompt = document.createElement("div");
      prompt.className = "favorites-prompt";
      prompt.textContent = CHOOSE_TEXT;
      menu.append(prompt, this.#menuButton("キャンセル", () => this.#choose(false)));
    } else {
      const save = this.#menuButton(SAVE_TEXT, () => this.#save());
      save.disabled = !this.saveEnabled();
      menu.append(save);
    }
    menu.append(menuSeparator());
    const shown = this.shown();
    const current = shown === null ? -1 : this.favorites.indexOf(shown);
    if (!this.favorites.items.length) {
      const empty = document.createElement("div");
      empty.className = "favorites-empty";
      empty.textContent = EMPTY_TEXT;
      menu.append(empty);
    }
    this.favorites.items.forEach((favorite, index) => menu.append(this.#row(favorite, index, index === current)));
    placeUnder(menu, this.button);
    if (at !== null) {
      const items = this.#items();
      items[Math.min(at, items.length - 1)]?.focus();
    }
  }

  #menuButton(text, onPick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scale-menu-item favorites-item";
    button.setAttribute("role", "menuitem");
    button.tabIndex = -1;
    button.textContent = text;
    button.addEventListener("click", onPick);
    return button;
  }

  // Returns the row of `favorite`: its thumbnail, its time, the mark of the
  // one shown and its × (delete).
  #row(favorite, index, isShown) {
    const row = document.createElement("div");
    row.className = "favorites-item favorites-row";
    row.classList.toggle("shown", isShown);
    row.setAttribute("role", "menuitem");
    row.tabIndex = -1;
    if (isShown) row.setAttribute("aria-current", "true");
    const thumb = document.createElement("div");
    thumb.className = "favorites-thumb";
    if (favorite.thumbnail) thumb.append(favorite.thumbnail);
    const time = document.createElement("span");
    time.className = "favorites-time";
    time.textContent = timeText(favorite.time);
    const text = document.createElement("div");
    text.className = "favorites-text";
    text.append(time);
    if (isShown) {
      const mark = document.createElement("span");
      mark.className = "favorites-shown";
      mark.textContent = "表示中";
      text.append(mark);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "favorites-remove";
    remove.tabIndex = -1;
    remove.textContent = "×";
    remove.title = "削除";
    remove.setAttribute("aria-label", "削除");
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      this.#remove(index);
    });
    row.append(thumb, text, remove);
    row.addEventListener("click", () => this.#pick(index));
    return row;
  }

  // Saves the current drawing: at the end below three, else after the
  // favorite to replace is picked.
  #save() {
    if (!this.saveEnabled()) return;
    if (this.favorites.full) {
      this.#choose(true);
      return;
    }
    const { settings, thumbnail } = this.capture();
    this.favorites.add(settings, thumbnail);
    this.#render();
  }

  #choose(choosing) {
    this.#choosing = choosing;
    this.#render(0);
  }

  // A row picked: while choosing, replaced with the current drawing;
  // otherwise recalled, unless it is the one shown.
  #pick(index) {
    const favorite = this.favorites.items[index];
    if (!favorite) return;
    if (this.#choosing) {
      if (!this.saveEnabled()) return;
      const { settings, thumbnail } = this.capture();
      this.favorites.replace(index, settings, thumbnail);
      this.#choosing = false;
      this.#render();
      return;
    }
    const shown = this.shown();
    if (shown !== null && this.favorites.indexOf(shown) === index) return;
    this.close();
    this.apply(structuredClone(favorite.settings));
  }

  #remove(index) {
    this.favorites.remove(index);
    this.#render();
  }

  // The arrows move among the items, Enter picks the one focused and
  // Delete removes the row focused.
  #key(event) {
    const items = this.#items();
    const at = items.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!items.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = at < 0 ? (step > 0 ? 0 : items.length - 1) : (at + step + items.length) % items.length;
      items[next].focus();
    } else if (event.key === "Enter" && at >= 0 && items[at].classList.contains("favorites-row")) {
      event.preventDefault();
      items[at].click();
    } else if (event.key === "Delete" && at >= 0 && items[at].classList.contains("favorites-row")) {
      event.preventDefault();
      this.#remove(this.#rowIndex(items[at]));
    }
  }

  #rowIndex(row) {
    return [...this.#popup.element.querySelectorAll(".favorites-row")].indexOf(row);
  }
}
