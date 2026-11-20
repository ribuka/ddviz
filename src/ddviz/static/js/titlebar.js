// The desktop window's title bar: the app menu (…) and the title, in the
// row of the OS caption buttons (docs/spec.md, "アプリメニュー").
//
// A plain script without imports: the desktop embeds it in its own pages
// (the chooser, the loading page), which the UI server does not serve. It
// draws only under <html class="desktop">, which the desktop's pages and the
// UI server started by the window (`create_app(desktop=True)`) carry, so the
// page in a browser (`--port`) has no title bar. It must run once <body>
// exists and before the page's content, so the row is there from the first
// paint: the first child of <body>.
//
// `<html data-screen>` says which screen this is: `New` is enabled on
// "graph" only, `Preferences…` on "chooser" and "graph" (not while starting
// or closing the data, "loading"). `描画設定を保存…` is enabled on "graph"
// while the page can save its drawing settings (`window.ddvizCanSaveDrawFile`
// of app.js: a figure drawn, no plot in flight), whose file the page gives
// (`window.ddvizDrawFile`) and the window saves where the user picks.
// `Data → 結合…` (Ctrl+J, which the page takes) is enabled on "graph" while
// the page can open its join dialog (`window.ddvizCanJoin` of app.js), which
// it opens (`window.ddvizOpenJoin`); the dialog's OS dialogs come through
// `window.ddvizChooseJoin`. The commands go to the window through
// pywebview's JS API, called from `call` alone. `Preferences…` opens the
// dialog of preferences.js, which the page loads before this script; on the
// graph's page the dialog then calls `window.ddvizApplySettings` (app.js).
(() => {
  const root = document.documentElement;
  if (!root.classList.contains("desktop")) return;

  // The caption's geometry from the window (`ddviz.desktop.titlebar`):
  // `window.ddvizCaption` is [buttons' width, row's height] in physical
  // pixels, set when the document was created, or later for a page loaded
  // before the window knew it. titlebar.css hides the page until it is
  // applied, so the row does not change height under the page; a window
  // that never tells it (off Windows) shows the defaults after a second.
  function applyCaption() {
    const caption = window.ddvizCaption;
    if (!caption) return;
    root.style.setProperty("--caption-buttons-width", `${caption[0] / devicePixelRatio}px`);
    root.style.setProperty("--caption-row", `${caption[1] / devicePixelRatio}px`);
    root.classList.add("caption-known");
  }
  window.ddvizCaptionChanged = applyCaption;
  applyCaption();
  setTimeout(() => root.classList.add("caption-known"), 1000);

  const MENU = [
    {
      label: "File",
      items: [
        { command: "new", label: "New" },
        { command: "save-draw-file", label: "描画設定を保存…" },
        { command: "quit", label: "Quit" },
      ],
    },
    { label: "Edit", items: [{ command: "preferences", label: "Preferences…" }] },
    { label: "Data", items: [{ command: "join", label: "結合…", shortcut: "Ctrl+J" }] },
    { label: "Help", items: [{ command: "version", label: "Version" }] },
  ];
  const NEW_CONFIRM =
    "現在のグラフ設定とフィルタを破棄し、Parquet 選択画面に戻ります。\n" +
    "This discards the current graph settings and filters and returns to the Parquet file selection.";
  const NEW_DISCARD = "Discard and Start Over";
  const NEW_CANCEL = "Cancel";

  // The window's API, once pywebview has injected it.
  const api = new Promise((resolve) => {
    const ready = () => resolve(window.pywebview.api);
    if (window.pywebview?.api?.quit) ready();
    else window.addEventListener("pywebviewready", ready, { once: true });
  });

  // Calls the window's `name` (`ddviz.desktop.window._Api`); the only place
  // that reaches pywebview.
  async function call(name, ...args) {
    return (await api)[name](...args);
  }

  // The join dialog's `ファイル…` and `フォルダ…` (joindialog.js): the paths
  // chosen with the OS dialog, `kind` `"files"` or `"folder"`, or null.
  window.ddvizChooseJoin = (kind) => call("choose_join", kind);

  function enabled(command) {
    const screen = root.dataset.screen;
    if (command === "new") return screen === "graph";
    if (command === "save-draw-file") return screen === "graph" && Boolean(window.ddvizCanSaveDrawFile?.());
    if (command === "join") return screen === "graph" && Boolean(window.ddvizCanJoin?.());
    if (command === "preferences") return screen === "graph" || screen === "chooser";
    return true;
  }

  const bar = document.createElement("header");
  bar.id = "titlebar";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "titlebar-menu";
  button.textContent = "…";
  button.title = "メニュー";
  button.setAttribute("aria-label", "メニュー");
  button.setAttribute("aria-haspopup", "menu");
  button.setAttribute("aria-expanded", "false");
  const title = document.createElement("span");
  title.className = "titlebar-title";
  title.textContent = document.title;
  bar.append(button, title);
  document.body.prepend(bar);

  // The open menu and submenu (null when closed), and the submenu's parent item.
  let menu = null;
  let submenu = null;
  let parent = null;

  function menuItem(label, disabled) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "titlebar-item";
    item.setAttribute("role", "menuitem");
    item.textContent = label;
    item.disabled = disabled;
    return item;
  }

  function panel() {
    const element = document.createElement("div");
    element.className = "titlebar-popup";
    element.setAttribute("role", "menu");
    document.body.append(element);
    return element;
  }

  function items(element) {
    return Array.from(element.querySelectorAll(".titlebar-item:not(:disabled)"));
  }

  function openMenu() {
    closeAll(false);
    menu = panel();
    for (const entry of MENU) {
      const item = menuItem(entry.label, entry.items === null);
      if (entry.items !== null) {
        item.classList.add("has-submenu");
        item.setAttribute("aria-haspopup", "menu");
        item.addEventListener("click", () => openSubmenu(item, entry.items));
      }
      menu.append(item);
    }
    const box = button.getBoundingClientRect();
    menu.style.left = `${box.left}px`;
    menu.style.top = `${box.bottom}px`;
    button.setAttribute("aria-expanded", "true");
    items(menu)[0]?.focus();
  }

  // Opens `entries` beside `item`: on the right, or on the left when the
  // right has no room.
  function openSubmenu(item, entries) {
    closeSubmenu(false);
    submenu = panel();
    parent = item;
    item.setAttribute("aria-expanded", "true");
    for (const entry of entries) {
      const sub = menuItem(entry.label, !enabled(entry.command));
      if (entry.shortcut) {
        const keys = document.createElement("span");
        keys.className = "titlebar-shortcut";
        keys.textContent = entry.shortcut;
        sub.append(keys);
      }
      sub.addEventListener("click", () => run(entry.command));
      submenu.append(sub);
    }
    const box = item.getBoundingClientRect();
    const outer = menu.getBoundingClientRect();
    const width = submenu.offsetWidth;
    const left = outer.right + width <= innerWidth ? outer.right : outer.left - width;
    submenu.style.left = `${Math.max(0, left)}px`;
    submenu.style.top = `${box.top}px`;
    items(submenu)[0]?.focus();
  }

  function closeSubmenu(focusParent) {
    if (submenu === null) return;
    submenu.remove();
    submenu = null;
    parent.setAttribute("aria-expanded", "false");
    if (focusParent) parent.focus();
    parent = null;
  }

  function closeAll(focusButton) {
    closeSubmenu(false);
    if (menu !== null) {
      menu.remove();
      menu = null;
      button.setAttribute("aria-expanded", "false");
    }
    if (focusButton) button.focus();
  }

  // Moves the focus by `step` among the enabled items of `element`.
  function move(element, step) {
    const list = items(element);
    if (list.length === 0) return;
    const at = list.indexOf(document.activeElement);
    list[(at + step + list.length) % list.length].focus();
  }

  button.addEventListener("click", () => {
    if (menu === null) openMenu();
    else closeAll(true);
  });

  document.addEventListener(
    "keydown",
    (event) => {
      if (menu === null) return;
      const inSubmenu = submenu !== null && submenu.contains(document.activeElement);
      const current = inSubmenu ? submenu : menu;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        move(current, event.key === "ArrowDown" ? 1 : -1);
      } else if (event.key === "ArrowRight" && !inSubmenu) {
        if (!document.activeElement.classList.contains("has-submenu")) return;
        document.activeElement.click();
      } else if (event.key === "ArrowLeft" && inSubmenu) {
        closeSubmenu(true);
      } else if (event.key === "Escape") {
        if (inSubmenu) closeSubmenu(true);
        else closeAll(true);
      } else if (event.key === "Tab") {
        closeAll(true);
      } else {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
    },
    true,
  );

  document.addEventListener(
    "pointerdown",
    (event) => {
      if (menu === null) return;
      const inside = [button, menu, submenu].some((e) => e?.contains(event.target));
      if (!inside) closeAll(false);
    },
    true,
  );

  async function run(command) {
    closeAll(false);
    if (command === "new") {
      const choice = await ask(NEW_CONFIRM, [NEW_DISCARD, NEW_CANCEL], NEW_CANCEL, NEW_DISCARD);
      if (choice === NEW_DISCARD) await call("new");
    } else if (command === "save-draw-file") {
      await saveDrawFile();
    } else if (command === "join") {
      window.ddvizOpenJoin();
      return;
    } else if (command === "quit") {
      await call("quit");
    } else if (command === "version") {
      await ask(`ddviz ${await call("version")}`, ["OK"], "OK");
    } else if (command === "preferences") {
      await preferences();
      button.focus();
      return;
    }
    if (document.activeElement === document.body) button.focus();
  }

  // Saves the graph's drawing settings to a file the window asks for with
  // the OS dialog: the page (app.js) gives the file's content and shows the
  // result.
  async function saveDrawFile() {
    let result;
    try {
      const text = await window.ddvizDrawFile();
      if (text === null) return;
      result = await call("save_draw_file", text);
    } catch (error) {
      result = { error: error?.message ?? String(error) };
    }
    window.ddvizDrawFileSaved(result);
  }

  // Opens the Preferences dialog with the values in effect; it saves
  // through the window and, on the graph's page, redraws through app.js.
  async function preferences() {
    let state;
    try {
      state = await call("settings");
    } catch (error) {
      await ask(`設定を読み込めませんでした：${error?.message ?? error}`, ["OK"], "OK");
      return;
    }
    await window.ddvizPreferences.open({
      state,
      save: (changes) => call("save_settings", changes),
      apply: window.ddvizApplySettings,
    });
  }

  // Shows `text` with `labels` as buttons and the focus on `initial`; the
  // button labelled `danger`, if given, is drawn red as an action that cannot
  // be undone. Resolves to the label chosen, or null on Esc.
  function ask(text, labels, initial, danger) {
    return new Promise((resolve) => {
      const backdrop = document.createElement("div");
      backdrop.className = "titlebar-backdrop";
      const box = document.createElement("div");
      box.className = "titlebar-dialog";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      const message = document.createElement("p");
      message.textContent = text;
      const row = document.createElement("div");
      row.className = "titlebar-dialog-buttons";
      const buttons = labels.map((label) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = label;
        if (label === danger) b.classList.add("danger");
        b.addEventListener("click", () => done(label));
        return b;
      });
      row.append(...buttons);
      box.append(message, row);
      backdrop.append(box);
      document.body.append(backdrop);
      const keys = (event) => {
        if (event.key === "Escape") {
          done(null);
        } else if (event.key === "Tab") {
          const at = buttons.indexOf(document.activeElement);
          const step = event.shiftKey ? -1 : 1;
          buttons[(at + step + buttons.length) % buttons.length].focus();
        } else {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
      };
      document.addEventListener("keydown", keys, true);
      buttons[labels.indexOf(initial)].focus();

      function done(label) {
        document.removeEventListener("keydown", keys, true);
        backdrop.remove();
        resolve(label);
      }
    });
  }
})();
