// The menu of the Color, Symbol, Group X and Group Y zones: a right click on
// the zone (its label, its chip or the room around them) while it holds a
// column opens it. The Wrap zone has the setting in its form (wrapmenu.js).
//
// - "Show null rows", checked when the zone draws the rows whose value is
//   null or NaN as a level of their own (`ddviz.shared.missing`). Each zone
//   keeps its setting, true until changed, whatever column it holds; a reload
//   sets them true again (`POST /api/plot`'s `show_null_rows`).
// - "フィルタで除外された水準も凡例に残す", on the Color zone alone while it holds
//   a categorical column: checked, the color levels are those of every row,
//   the ones the local filter leaves without rows staying in the legend;
//   unchecked (the default), they are those of the rows of the filter
//   (`POST /api/plot`'s `keep_unfiltered_color_levels`). The page keeps it
//   whatever column the zone holds, off again after a reload.
//
// The menu closes and stays in the window as the other right-click menus
// (smoothmenu.js).
import { menuItem, Popup } from "./popup.js";

export const NULL_ROLES = ["color", "symbol", "row", "col"];
export const KEEP_LEVELS_TEXT = "フィルタで除外された水準も凡例に残す";

const popup = new Popup();

// Returns a checked item `name` of the menu, which closes it and calls `pick`.
function item(name, text, checked, pick) {
  const row = menuItem(
    text,
    () => {
      popup.close();
      pick();
    },
    { checked },
  );
  row.dataset.item = name;
  return row;
}

// Attaches the menu to the zones `[data-role]` of `NULL_ROLES` in `root`.
// `hasColumn(role)` tells whether a zone holds a column, `showNullRows` maps
// each role to its setting and `onNullRows(role)` runs after one changed.
// `categoricalColor()` tells whether the Color zone holds a categorical
// column, `keepLevels()` returns the setting of keeping the levels left out
// by the filter, and `onKeepLevels()` turns it the other way.
export function attachZoneMenu(root, { hasColumn, showNullRows, onNullRows, categoricalColor, keepLevels, onKeepLevels }) {
  for (const role of NULL_ROLES) {
    const zone = root.querySelector(`.zone[data-role="${role}"]`);
    zone.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      popup.close();
      if (!hasColumn(role)) return;
      const menu = document.createElement("div");
      menu.className = "scale-menu zone-menu";
      menu.append(
        item("null-rows", "Show null rows", showNullRows[role], () => {
          showNullRows[role] = !showNullRows[role];
          onNullRows(role);
        }),
      );
      if (role === "color" && categoricalColor()) {
        menu.append(item("keep-levels", KEEP_LEVELS_TEXT, keepLevels(), onKeepLevels));
      }
      popup.open(menu, event);
    });
  }
}
