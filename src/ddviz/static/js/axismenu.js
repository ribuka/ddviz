// The menu of an axis column, opened by a right click on the tick labels of
// its axis (plotly's, or those of the strips of a grid that scrolls,
// `sticky.js`): "対数表示" toggles its log10 axis. A column that is not a
// number or a duration shows the item grayed out.

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

// Opens the menu at a right click for the column `column` of `axis` ("x"
// or "y"). `log` is whether it is on a log axis, `loggable` whether it may
// be; `onLog` gets the scale picked (true for log).
export function openAxisMenu(event, { axis, column, log, loggable, onLog }) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu axis-menu";
  const head = document.createElement("div");
  head.className = "scale-menu-heading";
  head.textContent = `${axis.toUpperCase()} 軸: ${column}`;
  const row = document.createElement("button");
  row.type = "button";
  row.className = "scale-menu-item";
  row.classList.toggle("checked", log);
  row.textContent = "対数表示";
  row.disabled = !loggable;
  row.addEventListener("click", () => {
    close();
    onLog(!log);
  });
  menu.append(head, row);
  document.body.append(menu);
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(event.clientX, innerWidth - rect.width - 4))}px`;
  menu.style.top = `${Math.max(4, Math.min(event.clientY, innerHeight - rect.height - 4))}px`;
  open = menu;
}
