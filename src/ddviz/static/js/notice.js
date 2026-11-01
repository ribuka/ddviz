// The status bar's message, with an icon for errors and warnings, and the
// toasts at the top right that tell of an error (Issue #31).

const TOAST_MS = 10000;
const MAX_TOASTS = 3;
// The exit of a closing toast; the same as `.toast-leaving` in app.css.
const EXIT_MS = 150;

// Returns the message of an error response: its `detail` when it is JSON
// (FastAPI's errors), else the text itself.
export function errorText(text) {
  try {
    const detail = JSON.parse(text).detail;
    if (typeof detail === "string") return detail;
  } catch {
    // Not JSON: the text itself.
  }
  return text;
}

// The status bar's message: plain, or an error with its icon and a toast.
export class StatusLine {
  constructor(element, toasts) {
    this.element = element;
    this.toasts = toasts;
  }

  // Shows a plain message (progress, rows), dropping an earlier error's look.
  show(text) {
    this.element.classList.remove("notice-error");
    this.element.textContent = text;
    // The bar shows one line; a long message ends in "…" (app.css).
    this.element.title = text;
  }

  // Shows an error with its icon, and tells of it in a toast too.
  error(text) {
    const message = `エラー: ${text}`;
    this.element.classList.add("notice-error");
    this.element.textContent = message;
    this.element.title = message;
    this.toasts.show(message);
  }
}

// The stack of error toasts at the top right. Each closes by its button or
// by itself after a while; the same message again replaces its toast.
//
// The timer stops while the pointer is on the toast or the window is hidden,
// and goes on with the time left (Issue #46). A closing toast plays its exit
// (`.toast-leaving` in app.css) and leaves the DOM after EXIT_MS; until then
// it no longer counts as shown and cannot be closed again.
export class Toasts {
  constructor(container) {
    this.container = container;
    document.addEventListener("visibilitychange", () => {
      for (const toast of this.shown()) this.resume(toast);
    });
  }

  // The toasts that are not leaving, oldest first.
  shown() {
    return [...this.container.querySelectorAll(".toast:not(.toast-leaving)")];
  }

  show(text) {
    for (const old of this.shown()) {
      if (old.dataset.text === text) this.close(old);
    }
    const toast = document.createElement("div");
    toast.className = "toast notice-error";
    toast.dataset.text = text;
    toast.setAttribute("role", "alert");
    const message = document.createElement("span");
    message.className = "toast-text";
    message.textContent = text;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.title = "閉じる";
    close.setAttribute("aria-label", "閉じる");
    close.textContent = "×";
    close.addEventListener("click", () => this.close(toast));
    toast.append(message, close);
    toast.left = TOAST_MS;
    toast.hovered = false;
    toast.addEventListener("mouseenter", () => {
      toast.hovered = true;
      this.resume(toast);
    });
    toast.addEventListener("mouseleave", () => {
      toast.hovered = false;
      this.resume(toast);
    });
    this.container.append(toast);
    this.resume(toast);
    const shown = this.shown();
    for (const extra of shown.slice(0, Math.max(0, shown.length - MAX_TOASTS))) this.close(extra);
  }

  // Runs the toast's timer, or stops it while it is hovered or the window is
  // hidden, keeping the time left.
  resume(toast) {
    if (toast.timer !== undefined) {
      clearTimeout(toast.timer);
      toast.timer = undefined;
      toast.left -= performance.now() - toast.started;
    }
    if (toast.hovered || document.hidden) return;
    toast.started = performance.now();
    toast.timer = setTimeout(() => this.close(toast), Math.max(0, toast.left));
  }

  close(toast) {
    if (toast.classList.contains("toast-leaving")) return;
    clearTimeout(toast.timer);
    toast.timer = undefined;
    toast.classList.add("toast-leaving");
    setTimeout(() => toast.remove(), EXIT_MS);
  }
}
