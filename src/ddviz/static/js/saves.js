// The saves of the plot's data (Issue #194): each save's progress in a toast
// with a cancel button, its end there with the file's actions, and the
// history of the page's saves.
//
// A save writes the rows on the server (`POST /api/plot-data/{task}`, the
// export: the bar goes to 90%), then fetches the file as a plain download
// (the transfer: 90 to 100%). In the desktop window (`html.desktop`),
// `ddviz.desktop.downloads` saves it to Downloads and tells the page how
// far it got (`window.ddvizSaveProgress`) and how it ended
// (`window.ddvizSaved`); the page opens the saved file or shows it in its
// folder by the server (`/api/saves/{file}/open|reveal`), never through the
// window's JS API. A browser (`--port`) saves the download as its settings
// say, so the save ends when the download starts.
//
// One export at a time: the table's pool runs it, and another export would
// kill it (`running`). The history lives as long as the page; in the window
// a button in the title bar opens it, in a browser the save menu
// (`datamenu.js`).

const FORMATS = { csv: "CSV", parquet: "Parquet" };
// Share of the bar of the export; the transfer fills the rest.
const EXPORT_SHARE = 90;
const UNITS = ["B", "KB", "MB", "GB", "TB"];
const SVG = 'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
const ICONS = {
  open: `<svg ${SVG}><path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M12 9.5v3.5a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-8a.5.5 0 0 1 .5-.5H7"/></svg>`,
  reveal: `<svg ${SVG}><path d="M1.5 4a1 1 0 0 1 1-1h3.6l1.4 1.5h6a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z"/></svg>`,
  history: `<svg ${SVG}><path d="M8 2.5v7M5 6.8 8 9.8l3-3M3 11.5v1.5h10v-1.5"/></svg>`,
};

// Returns `bytes` in the unit of `scale` (the larger of what is shown):
// "1.2 GB", or "512 B" in bytes.
function sizeIn(bytes, scale) {
  let unit = 0;
  while (unit < UNITS.length - 1 && scale >= 1000 ** (unit + 1)) unit++;
  const value = unit === 0 ? String(bytes) : (bytes / 1000 ** unit).toFixed(1);
  return [value, UNITS[unit]];
}

export function formatSize(bytes) {
  return sizeIn(bytes, bytes).join(" ");
}

// "1.2 / 1.4 GB": both in the unit of the larger.
export function formatSizes(done, total) {
  const scale = Math.max(done, total);
  const [a, unit] = sizeIn(done, scale);
  return `${a} / ${sizeIn(total, scale)[0]} ${unit}`;
}

function clock(date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

// The bar of a save in progress, 0 to 100; null while the rows are counted
// (the bar is indeterminate).
export function savePercent(save) {
  if (save.state === "counting") return null;
  if (save.state === "writing") return save.total ? (EXPORT_SHARE * save.done) / save.total : EXPORT_SHARE;
  return EXPORT_SHARE + (save.transferTotal ? ((100 - EXPORT_SHARE) * save.received) / save.transferTotal : 0);
}

const RUNNING = new Set(["counting", "writing", "transfer"]);

// Returns the text of a save's state: in its toast (`toast`) or in its row
// of the history.
export function saveText(save, toast) {
  if (save.cancelling && RUNNING.has(save.state)) return "中止しています…";
  switch (save.state) {
    case "counting":
      return "書き出す行を数えています…";
    case "writing":
      return `データを書き出しています（${save.done.toLocaleString()} / ${save.total.toLocaleString()} 行）`;
    case "transfer":
      if (save.transferTotal) return `保存しています（${formatSizes(save.received, save.transferTotal)}）`;
      return save.received ? `保存しています（${formatSize(save.received)}）` : "保存しています…";
    case "saved":
    case "missing":
      if (toast) return `ダウンロードに保存しました（${save.name}）`;
      return save.state === "missing" ? "移動または削除されました" : `${formatSize(save.size)} · ${clock(save.ended)}`;
    case "browser":
      return toast ? `ダウンロードを開始しました（${save.name}）` : `ブラウザーのダウンロード · ${clock(save.ended)}`;
    case "error":
      return toast ? `保存できませんでした：${save.error}` : `失敗：${save.error}`;
    case "cancelled":
      if (!toast) return "中止しました";
      return save.name ? `保存を中止しました（${save.name}）` : "保存を中止しました";
    default:
      return "";
  }
}

// Returns the error text of a failed response.
async function detail(response) {
  const text = await response.text();
  try {
    return JSON.parse(text).detail ?? text;
  } catch {
    return text;
  }
}

// Fetches a written file as a download: a browser saves it as its settings
// say; the window (WebView2) saves it to Downloads without asking.
function download(file) {
  const link = document.createElement("a");
  link.href = `/api/plot-data/file/${file}`;
  link.download = "";
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
}

function iconButton(className, icon, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.innerHTML = ICONS[icon];
  button.title = label;
  button.setAttribute("aria-label", label);
  return button;
}

export class Saves {
  // `toasts` shows them (`notice.js`); `exportEnded` is called whenever an
  // export ends, however it ends (the table fetches its pages again).
  constructor(toasts, exportEnded) {
    this.toasts = toasts;
    this.exportEnded = exportEnded;
    this.desktop = document.documentElement.classList.contains("desktop");
    // Newest first.
    this.saves = [];
    this.exporting = null;
    this.panel = null;
    this.panelAnchor = null;
    this.button = this.titleButton();
    window.addEventListener("pointerdown", (event) => {
      if (this.panel && !this.panel.contains(event.target) && !this.panelAnchor?.contains(event.target)) this.closeHistory();
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.panel) this.closeHistory();
    });
  }

  // Whether an export runs: no other save starts meanwhile.
  get running() {
    return this.exporting !== null;
  }

  get empty() {
    return this.saves.length === 0;
  }

  // Writes the rows of the overview `task` as `format` with the rows and
  // columns `picked`, and saves the file.
  async start(task, format, picked) {
    const save = {
      id: crypto.randomUUID(),
      format,
      state: "counting",
      name: null,
      file: null,
      done: 0,
      total: 0,
      received: 0,
      transferTotal: 0,
      cancelling: false,
      views: new Set(),
      toast: null,
    };
    this.saves.unshift(save);
    this.exporting = save;
    this.showToast(save);
    this.refreshHistory();
    try {
      if (task === null) throw new Error("グラフがありません");
      const response = await fetch(`/api/plot-data/${task}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format, ...picked, export: save.id }),
      });
      if (response.status === 409 && (await response.clone().json().catch(() => ({}))).cancelled) {
        this.end(save, "cancelled");
        return;
      }
      if (!response.ok) {
        throw new Error(response.status === 404 ? "図が新しくなりました。もう一度選んでください" : await detail(response));
      }
      const written = await response.json();
      save.name = written.name;
      save.file = written.file;
      if (save.cancelling) {
        this.end(save, "cancelled");
        return;
      }
      if (this.desktop) {
        save.state = "transfer";
        this.update(save);
        download(written.file);
      } else {
        download(written.file);
        this.end(save, "browser");
      }
    } catch (failure) {
      this.end(save, "error", failure.message);
    } finally {
      this.exporting = null;
      this.exportEnded();
    }
  }

  // The export's progress (a message of /api/events with `export`); those of
  // other pages are left out.
  exportProgress(message) {
    const save = this.exporting;
    if (save === null || message.export !== save.id) return;
    if (message.total === undefined) {
      save.state = "counting";
    } else {
      save.state = "writing";
      save.done = message.done;
      save.total = message.total;
    }
    this.update(save);
  }

  find(file) {
    return this.saves.find((s) => s.file !== null && s.file === file);
  }

  // The window's transfer of `file`: `{file, received, total}`.
  transferProgress(progress) {
    const save = this.find(progress.file);
    if (save?.state !== "transfer") return;
    save.received = progress.received;
    save.transferTotal = progress.total;
    this.update(save);
  }

  // How the window's save ended: `{file, saved, size}`, `{file, error}` or
  // `{file, cancelled}`. Returns false for a save the page does not know.
  saved(result) {
    const save = result.file === undefined ? undefined : this.find(result.file);
    if (save?.state !== "transfer") return false;
    if (result.saved !== undefined) {
      save.name = result.saved;
      save.size = result.size;
      this.end(save, "saved");
    } else if (result.cancelled) {
      this.end(save, "cancelled");
    } else {
      this.end(save, "error", result.error);
    }
    return true;
  }

  end(save, state, error) {
    save.state = state;
    save.error = error;
    save.ended = new Date();
    this.update(save);
    const kind = state === "error" ? "error" : "success";
    if (save.toast === null || !this.toasts.settle(save.toast, kind)) {
      this.showToast(save);
      this.toasts.settle(save.toast, kind);
    }
  }

  async cancel(save) {
    if (save.cancelling || !RUNNING.has(save.state)) return;
    save.cancelling = true;
    this.update(save);
    const response =
      save.state === "transfer"
        ? await fetch(`/api/saves/${save.file}/cancel`, { method: "POST" })
        : await fetch("/api/plot-data/cancel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ export: save.id }),
          });
    if (!response.ok) {
      save.cancelling = false;
      this.update(save);
      this.toasts.show(`中止できませんでした：${await detail(response)}`);
    }
  }

  // Opens the saved file (`open`) or shows it in its folder (`reveal`).
  async act(save, action) {
    const response = await fetch(`/api/saves/${save.file}/${action}`, { method: "POST" });
    if (response.ok) return;
    const reason = await detail(response);
    if (response.status === 404 && reason === "missing") {
      save.state = "missing";
      this.update(save);
      this.toasts.show(`ファイルが見つかりません。移動または削除されました（${save.name}）`);
    } else {
      this.toasts.show(`開けませんでした：${reason}`);
    }
  }

  // ---- views: a save's toast, and its row of the history ----

  showToast(save) {
    const view = this.view(save, true);
    save.toast = this.toasts.hold(view.root, () => {
      save.views.delete(view);
      if (save.toast?.contains(view.root)) save.toast = null;
    });
  }

  // Returns a view of `save`, kept up to date while it is in `save.views`.
  view(save, toast) {
    const root = document.createElement("div");
    root.className = toast ? "save-view toast-text" : "save-view save-row";
    const head = document.createElement("div");
    head.className = "save-head";
    const badge = document.createElement("span");
    badge.className = "save-badge";
    badge.textContent = FORMATS[save.format];
    const name = document.createElement("span");
    name.className = "save-name";
    head.append(badge, name);
    const line = document.createElement("div");
    line.className = "save-line";
    const status = document.createElement("span");
    status.className = "save-status";
    const open = iconButton("save-action save-open", "open", "ファイルを開く");
    open.addEventListener("click", () => this.act(save, "open"));
    const reveal = iconButton("save-action save-reveal", "reveal", "フォルダーに表示");
    reveal.addEventListener("click", () => this.act(save, "reveal"));
    line.append(status, open, reveal);
    const progress = document.createElement("div");
    progress.className = "save-progress";
    const bar = document.createElement("progress");
    bar.max = 100;
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "save-cancel";
    cancel.textContent = "中止";
    cancel.addEventListener("click", () => this.cancel(save));
    progress.append(bar, cancel);
    root.append(head, line, progress);
    const view = { root, toast, head, name, status, open, reveal, progress, bar, cancel };
    save.views.add(view);
    this.render(save, view);
    return view;
  }

  render(save, view) {
    const running = RUNNING.has(save.state);
    // Without a name until the export has written the file.
    view.name.textContent = save.name ?? `${FORMATS[save.format]} ${running ? "を書き出しています" : "の保存"}`;
    view.name.title = save.name ?? "";
    // A toast's end says the name in its text.
    view.head.hidden = view.toast && !running;
    view.status.textContent = saveText(save, view.toast);
    const actions = save.state === "saved";
    view.open.hidden = !actions;
    view.reveal.hidden = !actions;
    view.progress.hidden = !running;
    const percent = savePercent(save);
    if (percent === null) view.bar.removeAttribute("value");
    else view.bar.value = percent;
    // A browser's transfer cannot be cancelled: its save ends as it starts.
    view.cancel.hidden = !running;
    view.cancel.disabled = save.cancelling;
  }

  update(save) {
    for (const view of save.views) this.render(save, view);
    this.renderRing();
  }

  // ---- the history ----

  // The window's button in the title bar, left of the OS caption buttons,
  // shown from the first save; null without a title bar.
  titleButton() {
    const bar = document.getElementById("titlebar");
    if (bar === null) return null;
    const button = iconButton("titlebar-saves", "history", "保存の履歴");
    button.hidden = true;
    button.insertAdjacentHTML(
      "afterbegin",
      '<svg class="saves-ring" viewBox="0 0 24 24" aria-hidden="true"><circle class="saves-ring-track" cx="12" cy="12" r="10"/><circle class="saves-ring-value" cx="12" cy="12" r="10" pathLength="100"/></svg>',
    );
    button.addEventListener("click", () => (this.panel ? this.closeHistory() : this.openHistory(button)));
    bar.append(button);
    return button;
  }

  // The ring of the title bar's button: the mean bar of the saves running;
  // it turns while only bars without a value run.
  renderRing() {
    if (this.button === null) return;
    this.button.hidden = this.empty;
    const running = this.saves.filter((s) => RUNNING.has(s.state));
    const percents = running.map(savePercent).filter((p) => p !== null);
    const ring = this.button.querySelector(".saves-ring");
    ring.classList.toggle("running", running.length > 0);
    ring.classList.toggle("spinning", running.length > 0 && percents.length === 0);
    const mean = percents.length ? percents.reduce((a, b) => a + b, 0) / percents.length : 25;
    ring.querySelector(".saves-ring-value").style.strokeDasharray = `${mean} 100`;
    this.button.dataset.percent = percents.length ? String(Math.round(mean)) : "";
  }

  // Opens the history under `anchor`: the title bar's button, or in a
  // browser the mode bar's save button.
  openHistory(anchor) {
    this.closeHistory();
    const panel = document.createElement("div");
    panel.className = "saves-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "保存の履歴");
    const head = document.createElement("div");
    head.className = "saves-panel-heading";
    head.textContent = "保存の履歴";
    const list = document.createElement("div");
    list.className = "saves-list";
    panel.append(head, list);
    document.body.append(panel);
    this.panel = panel;
    this.panelList = list;
    this.panelAnchor = anchor;
    anchor.setAttribute("aria-expanded", "true");
    this.refreshHistory();
    const box = anchor.getBoundingClientRect();
    const rect = panel.getBoundingClientRect();
    panel.style.left = `${Math.max(4, Math.min(box.right - rect.width, window.innerWidth - rect.width - 4))}px`;
    panel.style.top = `${box.bottom + 4}px`;
  }

  closeHistory() {
    if (this.panel === null) return;
    for (const save of this.saves) {
      for (const view of save.views) if (!view.toast) save.views.delete(view);
    }
    this.panel.remove();
    this.panel = null;
    this.panelAnchor?.setAttribute("aria-expanded", "false");
    this.panelAnchor = null;
  }

  // Lists the saves in the open history again; a new save goes on top.
  refreshHistory() {
    this.renderRing();
    if (this.panel === null) return;
    for (const save of this.saves) {
      for (const view of save.views) if (!view.toast) save.views.delete(view);
    }
    this.panelList.replaceChildren(...this.saves.map((save) => this.view(save, false).root));
  }
}
