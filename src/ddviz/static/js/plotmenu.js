// The menu of the plot area, opened by a right click anywhere on the plot
// (panels, axes, facet labels; not the mode bar): the drag modes and Reset
// axes of the mode bar, nearer to the mouse. Each item clicks the mode bar's
// own button, so that it does what that button does; the drag mode in use is
// checked.

// The mode bar's buttons (`data-attr`, `data-val`), as plotly draws them.
const MODES = [
  ["zoom", "Zoom"],
  ["pan", "Pan"],
  ["select", "Box Select"],
];
const RESET = '.modebar-btn[data-attr="zoom"][data-val="reset"]';

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

// Opens the menu at a right click on `gd`, a plot drawn with the mode bar.
export function openPlotMenu(event, gd) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu plot-menu";
  const item = (text, checked, selector) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scale-menu-item";
    row.classList.toggle("checked", checked);
    row.textContent = text;
    row.addEventListener("click", () => {
      close();
      gd.querySelector(selector)?.click();
    });
    menu.append(row);
  };
  const mode = gd._fullLayout.dragmode;
  for (const [key, text] of MODES) {
    item(text, mode === key, `.modebar-btn[data-attr="dragmode"][data-val="${key}"]`);
  }
  const gap = document.createElement("div");
  gap.className = "scale-menu-separator";
  menu.append(gap);
  item("Reset axes", false, RESET);
  document.body.append(menu);
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(event.clientX, innerWidth - rect.width - 4))}px`;
  menu.style.top = `${Math.max(4, Math.min(event.clientY, innerHeight - rect.height - 4))}px`;
  open = menu;
}
