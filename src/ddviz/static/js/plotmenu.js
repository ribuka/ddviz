// The menu of the plot area, opened by a right click anywhere on the plot
// (panels, axes, facet labels; not the mode bar): the drag modes and Reset
// axes of the mode bar, nearer to the mouse. Each item clicks the mode bar's
// own button, so that it does what that button does; the drag mode in use is
// checked.
import { menuItem, menuSeparator, Popup } from "./popup.js";

// The mode bar's buttons (`data-attr`, `data-val`), as plotly draws them.
const MODES = [
  ["zoom", "Zoom"],
  ["pan", "Pan"],
  ["select", "Box Select"],
];
const RESET = '.modebar-btn[data-attr="zoom"][data-val="reset"]';
const COPY_IMAGE = "Copy graph image";

const popup = new Popup();

// Opens the menu at a right click on `gd`, a plot drawn with the mode bar;
// `imageCopy` is the page's `PlotImageCopy`.
export function openPlotMenu(event, gd, imageCopy) {
  const menu = document.createElement("div");
  menu.className = "scale-menu plot-menu";
  const item = (text, checked, selector) => {
    const pick = () => {
      popup.close();
      gd.querySelector(selector)?.click();
    };
    menu.append(menuItem(text, pick, { checked }));
  };
  const mode = gd._fullLayout.dragmode;
  for (const [key, text] of MODES) {
    item(text, mode === key, `.modebar-btn[data-attr="dragmode"][data-val="${key}"]`);
  }
  menu.append(menuSeparator());
  item("Reset axes", false, RESET);
  menu.append(menuSeparator());
  const copy = () => {
    popup.close();
    imageCopy.copy();
  };
  menu.append(menuItem(COPY_IMAGE, copy, { disabled: !imageCopy.available() }));
  popup.open(menu, event);
}
