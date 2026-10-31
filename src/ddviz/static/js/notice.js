// The status bar's message, with an icon for errors and warnings, and the
// toasts at the top right that tell of an error (Issue #31).

const TOAST_MS = 10000;
const MAX_TOASTS = 3;

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
  }

  // Shows an error with its icon, and tells of it in a toast too.
  error(text) {
    const message = `エラー: ${text}`;
    this.element.classList.add("notice-error");
    this.element.textContent = message;
    this.toasts.show(message);
  }
}

// The stack of error toasts at the top right. Each closes by its button or
// by itself after a while; the same message again replaces its toast.
export class Toasts {
  constructor(container) {
    this.container = container;
  }

  show(text) {
    for (const old of this.container.querySelectorAll(".toast")) {
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
    this.container.append(toast);
    toast.timer = setTimeout(() => this.close(toast), TOAST_MS);
    const shown = this.container.querySelectorAll(".toast");
    for (const extra of [...shown].slice(0, Math.max(0, shown.length - MAX_TOASTS))) this.close(extra);
  }

  close(toast) {
    clearTimeout(toast.timer);
    toast.remove();
  }
}
