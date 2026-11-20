// The buttons and keys of undo and redo of the drawing settings
// (docs/spec.md, "undo/redo"): in the window's title bar right of its `…`
// menu, or in a browser at the left end of the row above the zones (`#top`);
// Ctrl+Z, and Ctrl+Y or Ctrl+Shift+Z, in both.

import { Popup } from "./popup.js";

const ICONS = {
  undo: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M5.5 3 2 6.5 5.5 10M2.5 6.5H10a4 4 0 0 1 0 8H7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  redo: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M10.5 3 14 6.5 10.5 10M13.5 6.5H6a4 4 0 0 0 0 8h3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

function button(name, label, onClick) {
  const element = document.createElement("button");
  element.type = "button";
  element.className = `undo-button undo-${name}`;
  element.innerHTML = ICONS[name];
  element.title = label;
  element.setAttribute("aria-label", label);
  element.disabled = true;
  element.addEventListener("click", onClick);
  return element;
}

// Makes the two buttons and puts them in their place; returns them as
// `{undo, redo}`, disabled until `update` says otherwise.
export function undoButtons(onUndo, onRedo) {
  const undo = button("undo", "元に戻す (Ctrl+Z)", onUndo);
  const redo = button("redo", "やり直す (Ctrl+Y)", onRedo);
  const menu = document.querySelector("#titlebar .titlebar-menu");
  if (menu) {
    undo.classList.add("titlebar-undo");
    redo.classList.add("titlebar-undo");
    menu.after(undo, redo);
  } else {
    document.getElementById("top").prepend(undo, redo);
  }
  return { undo, redo };
}

// Whether a key goes to what has the focus or is open: a text field, a
// select or an editable element, an open dialog, or a popup menu. The
// page's other shortcuts (Ctrl+J of the join, app.js) leave those keys to
// the browser too.
export function keyTaken(event) {
  const target = event.target;
  if (target instanceof Element && target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) {
    return true;
  }
  if (Popup.anyOpen()) return true;
  return document.querySelector("dialog[open], .titlebar-popup, .titlebar-backdrop, .prefs-backdrop") !== null;
}

// Listens to Ctrl+Z (undo), and Ctrl+Y and Ctrl+Shift+Z (redo), but for
// those `keyTaken` leaves to the browser and those of an IME composing.
export function attachUndoKeys(onUndo, onRedo) {
  document.addEventListener("keydown", (event) => {
    if (!event.ctrlKey || event.altKey || event.metaKey || event.isComposing) return;
    const key = event.key.toLowerCase();
    const undo = key === "z" && !event.shiftKey;
    const redo = (key === "y" && !event.shiftKey) || (key === "z" && event.shiftKey);
    if (!(undo || redo) || keyTaken(event)) return;
    event.preventDefault();
    if (undo) onUndo();
    else onRedo();
  });
}
