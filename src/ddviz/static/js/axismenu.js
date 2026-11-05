// The menu of an axis column, opened by a right click on the tick labels of
// its axis (plotly's, or those of the strips of a grid that scrolls,
// `sticky.js`): "対数表示" toggles its log10 axis, "向きを反転" its direction
// (`axisdirection.js`). A column that is not a number or a duration shows
// "対数表示" grayed out; the band of an empty X, which has no column, shows
// both grayed out.

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

// Returns a check item of the menu: `checked` shows its state, `onPick` gets
// the state picked.
function item(text, checked, enabled, onPick) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "scale-menu-item";
  row.classList.toggle("checked", checked);
  row.textContent = text;
  row.disabled = !enabled;
  row.addEventListener("click", () => {
    close();
    onPick(!checked);
  });
  return row;
}

// Opens the menu at a right click for the column `column` of `axis` ("x"
// or "y"). `log` is whether it is on a log axis, `loggable` whether it may
// be; `onLog` gets the scale picked (true for log). `reversed` is whether
// the axis is reversed; `onReverse` gets the direction picked (true for
// reversed).
export function openAxisMenu(event, { axis, column, log, loggable, onLog, reversed, onReverse }) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu axis-menu";
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = `${axis.toUpperCase()} 軸: ${column ?? ""}`;
  const hasColumn = column !== undefined && column !== null;
  menu.append(
    head,
    item("対数表示", log, loggable && hasColumn, onLog),
    item("向きを反転", reversed, hasColumn, onReverse),
  );
  document.body.append(menu);
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(event.clientX, innerWidth - rect.width - 4))}px`;
  menu.style.top = `${Math.max(4, Math.min(event.clientY, innerHeight - rect.height - 4))}px`;
  open = menu;
}
