// The menu of the mode bar's download button: save the rows of the plot
// (`ddviz.compute.tasks.plotdata`) as a CSV or a Parquet file. Radios pick
// the rows (drawn, or every row the filter keeps) and the columns (drawn, or
// all), kept by the page until it is reloaded. A format closes the menu and
// starts the save (`saves.js`), whose progress and end show in a toast; no
// format while an export runs. A click outside or Esc closes the menu. In a
// browser, the menu's last item opens the history of the saves (in the
// window, the title bar's button does).
import { Popup } from "./popup.js";

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

// The menu. A press on its button does not close it: the button's click
// opens it again (`openDataMenu` closes it first).
const popup = new Popup();

function close() {
  popup.close();
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

function separator() {
  const line = document.createElement("div");
  line.className = "scale-menu-separator";
  return line;
}

// Opens the menu under `anchor` (the mode bar's button). `task` returns the
// task of the overview drawn, or null without a plot; `saves` runs the saves
// (`saves.js`).
export function openDataMenu(anchor, task, saves) {
  close();
  saves.closeHistory();
  const menu = document.createElement("div");
  menu.className = "scale-menu data-menu";
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = "データを保存";
  menu.append(head, ...CHOICES.map(radioGroup), separator());
  for (const [format, text] of FORMATS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scale-menu-item";
    button.textContent = text;
    button.disabled = saves.running;
    button.addEventListener("click", () => {
      close();
      saves.start(task(), format, { ...picked });
    });
    menu.append(button);
  }
  if (saves.running) {
    const note = document.createElement("div");
    note.className = "data-menu-note";
    note.textContent = "書き出しが終わると保存できます";
    menu.append(note);
  }
  if (!saves.desktop) {
    const history = document.createElement("button");
    history.type = "button";
    history.className = "scale-menu-item";
    history.textContent = "保存の履歴…";
    history.disabled = saves.empty;
    history.addEventListener("click", () => {
      close();
      saves.openHistory(anchor);
    });
    menu.append(separator(), history);
  }
  popup.openUnder(menu, anchor, { align: "right", gap: 4 });
}
