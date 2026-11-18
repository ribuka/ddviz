// The menu of an axis column, opened by a right click on the tick labels of
// its axis (plotly's, or those of the strips of a grid that scrolls,
// `sticky.js`): "対数表示" toggles its log10 axis, "向きを反転" its direction
// (`axisdirection.js`), and "フィルタで除外された水準も軸に残す" whether a
// categorical column keeps the levels of every row as its bands
// (`axislevels.js`). A column that is not a number or a duration shows
// "対数表示" grayed out, one that is not categorical the levels' item; the
// band of an empty X, which has no column, shows them all grayed out.
import { menuHeading, menuItem, Popup } from "./popup.js";

const popup = new Popup();

// Returns a check item of the menu: `checked` shows its state, `onPick` gets
// the state picked.
function item(text, checked, enabled, onPick) {
  const pick = () => {
    popup.close();
    onPick(!checked);
  };
  return menuItem(text, pick, { checked, disabled: !enabled });
}

// Opens the menu at a right click for the column `column` of `axis` ("x"
// or "y"). `log` is whether it is on a log axis, `loggable` whether it may
// be; `onLog` gets the scale picked (true for log). `reversed` is whether
// the axis is reversed; `onReverse` gets the direction picked (true for
// reversed). `keepLevels` is whether it keeps the levels of every row,
// `categorical` whether it may; `onKeepLevels` gets the setting picked.
export function openAxisMenu(
  event,
  { axis, column, log, loggable, onLog, reversed, onReverse, keepLevels, categorical, onKeepLevels },
) {
  const menu = document.createElement("div");
  menu.className = "scale-menu axis-menu";
  const hasColumn = column !== undefined && column !== null;
  menu.append(
    menuHeading(`${axis.toUpperCase()} 軸: ${column ?? ""}`),
    item("対数表示", log, loggable && hasColumn, onLog),
    item("向きを反転", reversed, hasColumn, onReverse),
    item("フィルタで除外された水準も軸に残す", keepLevels, categorical && hasColumn, onKeepLevels),
  );
  popup.open(menu, event);
}
