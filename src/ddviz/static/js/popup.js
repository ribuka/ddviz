// The parts shared by the right-click menus, which open at the mouse
// (plotmenu.js, axismenu.js, scalemenu.js, shapemenu.js, smoothmenu.js,
// zonemenu.js, wrapmenu.js, columnmenu.js), and the popups that open under a
// button (columns.js, filters.js, datamenu.js, saves.js): opening and closing
// a popup, placing it in the window, and the items, headings and separators
// of a menu.

// The margin kept between a popup and the window's edges, in px.
export const EDGE = 4;

// Places `element` (already in the document) with its top left at (x, y),
// moved so that it stays EDGE px inside the window.
export function placeAt(element, x, y) {
  const { innerWidth, innerHeight } = window;
  const rect = element.getBoundingClientRect();
  element.style.left = `${Math.max(EDGE, Math.min(x, innerWidth - rect.width - EDGE))}px`;
  element.style.top = `${Math.max(EDGE, Math.min(y, innerHeight - rect.height - EDGE))}px`;
}

// Places `element` (already in the document) under `anchor`, `gap` px
// below it, its left edge at the anchor's left (align "left") or its right
// edge at the anchor's right (align "right"); above the anchor when the
// window has no room below. It stays EDGE px inside the window.
export function placeUnder(element, anchor, { align = "left", gap = 2 } = {}) {
  const { innerWidth, innerHeight } = window;
  const r = anchor.getBoundingClientRect();
  const { width, height } = element.getBoundingClientRect();
  const left = align === "right" ? r.right - width : r.left;
  const below = r.bottom + gap;
  const top = below + height <= innerHeight - EDGE ? below : r.top - gap - height;
  element.style.left = `${Math.max(EDGE, Math.min(left, innerWidth - width - EDGE))}px`;
  element.style.top = `${Math.max(EDGE, Math.min(top, innerHeight - height - EDGE))}px`;
}

// Every popup made (`Popup.anyOpen`).
const popups = new Set();

// A popup of one module, open or closed. It closes on a press outside the
// element, outside the anchor it was opened under and outside every element
// `inside()` returns, and on Escape.
export class Popup {
  #element = null;
  #anchor = null;
  #onClose;

  constructor({ onClose = () => {}, inside = () => [] } = {}) {
    this.#onClose = onClose;
    popups.add(this);
    window.addEventListener("pointerdown", (event) => {
      if (!this.#element || this.#element.contains(event.target)) return;
      if (this.#anchor?.contains(event.target)) return;
      if (inside().some((other) => other?.contains(event.target))) return;
      this.close();
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this.close();
    });
  }

  // The open element, or null.
  get element() {
    return this.#element;
  }

  // The anchor of the popup opened with `openUnder`, or null.
  get anchor() {
    return this.#anchor;
  }

  // Closes the popup open, appends `element` to the page and places it at
  // the mouse of `event`.
  open(element, event) {
    this.close();
    document.body.append(element);
    placeAt(element, event.clientX, event.clientY);
    this.#element = element;
  }

  // Closes the popup open, appends `element` to the page and places it
  // under `anchor` (`placeUnder`). A press on `anchor` does not close it:
  // the anchor's own click decides (see `anchor`).
  openUnder(element, anchor, options = {}) {
    this.close();
    document.body.append(element);
    placeUnder(element, anchor, options);
    this.#element = element;
    this.#anchor = anchor;
  }

  // Whether a popup of any module is open (its element still in the page).
  static anyOpen() {
    return [...popups].some((popup) => popup.#element?.isConnected);
  }

  // Removes the element if open, then calls `onClose` (also when closed).
  close() {
    this.#element?.remove();
    this.#element = null;
    this.#anchor = null;
    this.#onClose();
  }
}

// Returns a button.scale-menu-item with `text`; class `checked` when
// `checked`, `disabled` when `disabled`; a click calls `onPick()`. It does
// not close the menu: `onPick` does when it should.
export function menuItem(text, onPick, { checked = false, disabled = false } = {}) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "scale-menu-item";
  row.classList.toggle("checked", checked);
  row.disabled = disabled;
  row.textContent = text;
  row.addEventListener("click", () => onPick());
  return row;
}

// Returns a div.scale-menu-heading with `text`.
export function menuHeading(text) {
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = text;
  return head;
}

// Returns a div.scale-menu-separator.
export function menuSeparator() {
  const gap = document.createElement("div");
  gap.className = "scale-menu-separator";
  return gap;
}
