// The menu of the mode bar's download button: save the plot's data, the bins of
// its overview (`ddviz.server.plotdata`), as a CSV or a Parquet file. The
// server writes the file and names it; a click outside or Esc closes the menu,
// and a failure is shown in it, which stays open.

const FORMATS = [
  ["csv", "CSV"],
  ["parquet", "Parquet"],
];

let open = null;

function close() {
  open?.remove();
  open = null;
}

window.addEventListener("pointerdown", (event) => {
  if (open && !open.contains(event.target)) close();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") close();
});

// Returns the file name in a `Content-Disposition` header, or `fallback`. The
// server gives a name of other characters than ASCII as `filename*`.
function headerName(response, fallback) {
  const header = response.headers.get("Content-Disposition") ?? "";
  const encoded = /filename\*=utf-8''([^;]+)/i.exec(header);
  if (encoded) return decodeURIComponent(encoded[1]);
  return /filename="([^"]+)"/.exec(header)?.[1] ?? fallback;
}

// Saves a blob as a downloaded file named `name`.
function saveFile(blob, name) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60_000);
}

// Opens the menu under `anchor` (the mode bar's button). `task` returns the
// task of the overview drawn, or null without a plot.
export function openDataMenu(anchor, task) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu data-menu";
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = "データを保存（全体図のビン）";
  menu.append(head);
  const error = document.createElement("div");
  error.className = "data-menu-error";
  error.hidden = true;
  const buttons = FORMATS.map(([format, text]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scale-menu-item";
    button.textContent = text;
    button.addEventListener("click", async () => {
      for (const b of buttons) b.disabled = true;
      error.hidden = true;
      try {
        const id = task();
        if (id === null) throw new Error("グラフがありません");
        const response = await fetch(`/api/plot-data/${id}?format=${format}`);
        if (!response.ok) {
          const text = await response.text();
          let detail = text;
          try {
            detail = JSON.parse(text).detail ?? text;
          } catch {}
          throw new Error(response.status === 404 ? "図が新しくなりました。もう一度選んでください" : detail);
        }
        saveFile(await response.blob(), headerName(response, `ddviz.${format}`));
        close();
      } catch (failure) {
        error.textContent = `保存できませんでした：${failure.message}`;
        error.hidden = false;
      } finally {
        for (const b of buttons) b.disabled = false;
      }
    });
    menu.append(button);
    return button;
  });
  menu.append(error);
  document.body.append(menu);
  const box = anchor.getBoundingClientRect();
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(box.right - rect.width, window.innerWidth - rect.width - 4))}px`;
  menu.style.top = `${Math.min(box.bottom + 4, window.innerHeight - rect.height - 4)}px`;
  open = menu;
}
