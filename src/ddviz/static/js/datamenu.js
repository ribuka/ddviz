// The menu of the mode bar's download button: save the rows of the plot
// (`ddviz.compute.tasks.plotdata`) as a CSV or a Parquet file. Radios pick
// the rows (drawn, or every row the filter keeps) and the columns (drawn, or
// all), kept by the page until it is reloaded. A format writes the file on
// the server under a cover with its progress (`exportProgress`, fed by
// /api/events), then fetches it as a plain download, so that the page never
// holds the file. A click outside or Esc closes the menu, and a failure is
// shown in it, which stays open.

const FORMATS = [
  ["csv", "CSV"],
  ["parquet", "Parquet"],
];
const CHOICES = [
  {
    key: "rows",
    heading: "Rows",
    options: [
      ["drawn", "Drawn rows"],
      ["filtered", "All filtered rows"],
    ],
  },
  {
    key: "columns",
    heading: "Columns",
    options: [
      ["drawn", "Drawn columns"],
      ["all", "All columns"],
    ],
  },
];

// The rows and columns picked, until the page is reloaded.
const picked = { rows: "drawn", columns: "drawn" };

let open = null;

function close() {
  open?.remove();
  open = null;
}

const cover = document.getElementById("exporting");
const coverText = document.getElementById("exporting-text");
const coverBar = document.getElementById("exporting-bar");
// Token of the export running, which its progress messages carry.
let running = null;

// The menu stays open while its export runs, to show a failure.
window.addEventListener("pointerdown", (event) => {
  if (open && running === null && !open.contains(event.target)) close();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && running === null) close();
});

function showCover() {
  coverText.textContent = "書き出す行を数えています…";
  coverBar.removeAttribute("value");
  cover.hidden = false;
}

// Shows the progress of the export running (a message of /api/events with
// `export`); those of another export are left out.
export function exportProgress(message) {
  if (message.export !== running || message.total === undefined) return;
  coverText.textContent = `データを書き出しています（${message.done.toLocaleString()} / ${message.total.toLocaleString()} 行）`;
  coverBar.max = Math.max(message.total, 1);
  coverBar.value = message.done;
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

// Fetches a written file as a download: a browser saves it, the window
// (WebView2) asks where with the OS dialog.
function download(file) {
  const link = document.createElement("a");
  link.href = `/api/plot-data/file/${file}`;
  link.download = "";
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
}

// Returns a group of radios of a choice, which change `picked` and keep the
// menu open.
function radioGroup(choice) {
  const group = document.createElement("div");
  group.className = "data-menu-group";
  group.setAttribute("role", "radiogroup");
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.id = `data-menu-${choice.key}`;
  head.textContent = choice.heading;
  group.setAttribute("aria-labelledby", head.id);
  group.append(head);
  const radios = choice.options.map(([value, text]) => {
    const radio = document.createElement("button");
    radio.type = "button";
    radio.className = "scale-menu-item data-menu-radio";
    radio.setAttribute("role", "radio");
    radio.textContent = text;
    radio.dataset.value = value;
    radio.addEventListener("click", () => {
      picked[choice.key] = value;
      for (const r of radios) r.setAttribute("aria-checked", String(r === radio));
    });
    radio.setAttribute("aria-checked", String(picked[choice.key] === value));
    group.append(radio);
    return radio;
  });
  return group;
}

// Opens the menu under `anchor` (the mode bar's button). `task` returns the
// task of the overview drawn, or null without a plot.
export function openDataMenu(anchor, task) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu data-menu";
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = "データを保存";
  menu.append(head, ...CHOICES.map(radioGroup));
  const separator = document.createElement("div");
  separator.className = "scale-menu-separator";
  menu.append(separator);
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
        running = crypto.randomUUID();
        showCover();
        const response = await fetch(`/api/plot-data/${id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ format, ...picked, export: running }),
        });
        if (!response.ok) {
          throw new Error(response.status === 404 ? "図が新しくなりました。もう一度選んでください" : await detail(response));
        }
        download((await response.json()).file);
        close();
      } catch (failure) {
        error.textContent = `保存できませんでした：${failure.message}`;
        error.hidden = false;
      } finally {
        running = null;
        cover.hidden = true;
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
