// The menu of the Color and Symbol zones: a right click on the zone (its
// label, its chip or the room around them) while it holds a column opens
// "Show null rows", checked when the zone draws the rows whose value is null
// or NaN as a level of their own (`ddviz.shared.missing`). Each zone keeps
// its setting, true until changed, whatever column it holds; a reload sets
// both true again (`POST /api/plot`'s `show_null_rows`). The menu closes and
// stays in the window as the other right-click menus (smoothmenu.js).

export const NULL_ROLES = ["color", "symbol"];

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

// Attaches the menu to the zones `[data-role]` of `NULL_ROLES` in `root`.
// `hasColumn(role)` tells whether a zone holds a column, `settings` maps each
// role to its setting, and `onChange(role)` runs after a setting changed.
export function attachNullMenu(root, hasColumn, settings, onChange) {
  for (const role of NULL_ROLES) {
    const zone = root.querySelector(`.zone[data-role="${role}"]`);
    zone.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      close();
      if (!hasColumn(role)) return;
      const menu = document.createElement("div");
      menu.className = "scale-menu null-menu";
      const row = document.createElement("button");
      row.type = "button";
      row.className = "scale-menu-item";
      row.classList.toggle("checked", settings[role]);
      row.textContent = "Show null rows";
      row.addEventListener("click", () => {
        close();
        settings[role] = !settings[role];
        onChange(role);
      });
      menu.append(row);
      document.body.append(menu);
      const { innerWidth, innerHeight } = window;
      const rect = menu.getBoundingClientRect();
      menu.style.left = `${Math.max(4, Math.min(event.clientX, innerWidth - rect.width - 4))}px`;
      menu.style.top = `${Math.max(4, Math.min(event.clientY, innerHeight - rect.height - 4))}px`;
      open = menu;
    });
  }
}
