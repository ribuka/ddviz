// The column list: the server searches the names (`GET /api/columns`) and
// returns the first matches with their count, so a data set of 100,000
// columns never sends them all; how many it returns is `columns.max_listed`
// of config/settings.toml. Each listed column can be dragged to a role.
// Each shows its rows with a value, which the server counts after Load, over
// a bar as long as their share of the rows; until then the list asks again
// every second, and the controls that filter and sort by the share wait.
// "Sort by" opens a menu of Name (natural order) and Count (most values
// first); the order in use is checked, and picking it again goes back to the
// file order.
// An answer that lists the same columns as shown updates their shares in
// place: a replaced item under the pointer between its mouse down and its
// `dragstart` makes Chrome drop the drag.
import { beginDrag } from "./builder.js";

const SEARCH_DELAY_MS = 150;
const PENDING_RETRY_MS = 1000;

export function attachColumnList(root) {
  const input = root.querySelector(".column-search");
  const kinds = root.querySelectorAll("[data-kind]");
  const hideEmpty = root.querySelector(".column-hide-empty");
  const minShare = root.querySelector(".column-min-share");
  const orderButton = root.querySelector(".column-order");
  const count = root.querySelector(".column-count");
  const list = root.querySelector(".column-list");
  let kind = null;
  // "file", "name" or "count" (`ddviz.server.columns.ORDERS`).
  let order = "file";
  let sharesDone = false;
  let timer = null;
  // Generation of the latest search, so that an older answer is dropped.
  let generation = 0;

  async function search() {
    clearTimeout(timer);
    const mine = ++generation;
    const query = new URLSearchParams({ q: input.value });
    if (kind) query.set("kind", kind);
    const min = Number(minShare.value);
    if (min > 0) query.set("min_share", min / 100);
    else if (hideEmpty.checked) query.set("min_share", 0);
    if (order !== "file") query.set("order", order);
    const response = await fetch(`/api/columns?${query}`);
    if (mine !== generation) return;
    if (!response.ok) {
      count.textContent = `エラー: ${await response.text()}`;
      return;
    }
    const found = await response.json();
    const shown = found.matched > found.columns.length ? `、上位 ${found.columns.length} 件を表示` : "";
    const shares = { pending: "（非 null の行数を計算中）", failed: "（非 null の行数は求められませんでした）" }[found.shares] ?? "";
    count.textContent = `${found.total.toLocaleString()} 列中 ${found.matched.toLocaleString()} 件${shown}${shares}`;
    sharesDone = found.shares === "done";
    for (const control of [hideEmpty, minShare]) control.disabled = !sharesDone;
    const countItem = sortMenu?.querySelector('[data-order="count"]');
    if (countItem) countItem.disabled = !sharesDone;
    showColumns(list, found);
    if (found.shares === "pending") timer = setTimeout(search, PENDING_RETRY_MS);
  }

  function searchSoon() {
    clearTimeout(timer);
    timer = setTimeout(search, SEARCH_DELAY_MS);
  }

  input.addEventListener("input", searchSoon);
  minShare.addEventListener("input", searchSoon);
  hideEmpty.addEventListener("change", search);
  orderButton.addEventListener("click", () => {
    if (closeSortMenu()) return;
    openSortMenu(orderButton, order, sharesDone, (picked) => {
      order = picked === order ? "file" : picked;
      orderButton.classList.toggle("on", order !== "file");
      search();
    });
  });
  for (const button of kinds) {
    button.addEventListener("click", () => {
      kind = button.dataset.kind || null;
      for (const other of kinds) other.classList.toggle("on", other === button);
      search();
    });
  }
  return search();
}

// The open "Sort by" menu, or null.
let sortMenu = null;

// Closes the "Sort by" menu; tells whether it was open.
function closeSortMenu() {
  const wasOpen = sortMenu !== null;
  sortMenu?.remove();
  sortMenu = null;
  return wasOpen;
}

window.addEventListener("pointerdown", (event) => {
  if (sortMenu && !sortMenu.contains(event.target) && !event.target.closest?.(".column-order")) {
    closeSortMenu();
  }
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeSortMenu();
});

// Opens the "Sort by" menu under `button`. Count waits for the non-null
// values, as the share filters do; `pick` gets "name" or "count".
function openSortMenu(button, order, sharesDone, pick) {
  const menu = document.createElement("div");
  menu.className = "scale-menu sort-menu";
  for (const [key, text, title] of [
    ["name", "Name", "列名の順（数字は値の順）"],
    ["count", "Count", "非 null の行数が多い順"],
  ]) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scale-menu-item";
    row.dataset.order = key;
    row.classList.toggle("checked", order === key);
    row.textContent = text;
    row.title = order === key ? `${title}（もう一度押すと元の順に戻す）` : title;
    row.disabled = key === "count" && !sharesDone;
    row.addEventListener("click", () => {
      closeSortMenu();
      pick(key);
    });
    menu.append(row);
  }
  document.body.append(menu);
  const rect = button.getBoundingClientRect();
  const width = menu.getBoundingClientRect().width;
  menu.style.left = `${Math.max(4, Math.min(rect.left, window.innerWidth - width - 4))}px`;
  menu.style.top = `${rect.bottom + 2}px`;
  sortMenu = menu;
}

// A count of rows in the narrow share column: up to 3 significant digits
// with K, M or B, cut rather than rounded. A count short of the rows that
// still reads as them gets "<", so that only a column of no nulls shows them.
const COMPACT = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumSignificantDigits: 3,
  roundingMode: "trunc",
});

function compactCount(count, rows) {
  const text = COMPACT.format(count);
  return count < rows && text === COMPACT.format(rows) ? `<${text}` : text;
}

// Show the answer's columns, keeping the items when they are the same columns
// in the same order (the answers while the shares are counted).
function showColumns(list, found) {
  const items = [...list.children];
  const same =
    items.length === found.columns.length &&
    items.every((item, i) => item.dataset.name === found.columns[i].name);
  if (!same) {
    list.replaceChildren(...found.columns.map(columnItem));
  }
  found.columns.forEach((column, i) => showShare(list.children[i], column, found.shares, found.rows));
}

function columnItem(column) {
  const item = document.createElement("div");
  item.className = "column";
  item.draggable = true;
  item.dataset.name = column.name;
  const type = document.createElement("span");
  type.className = `column-type ${column.numeric ? "numeric" : "categorical"}`;
  // A temporal column is numeric (`ddviz.compute.temporal`), marked apart.
  type.textContent = column.temporal ? "◷" : column.numeric ? "#" : "A";
  const name = document.createElement("span");
  name.className = "column-name";
  name.textContent = column.name;
  const share = document.createElement("span");
  share.className = "column-share";
  item.append(type, name, share);
  item.addEventListener("dragstart", (event) => {
    beginDrag({ name: column.name, numeric: column.numeric, temporal: column.temporal });
    event.dataTransfer.setData("text/plain", column.name);
    event.dataTransfer.effectAllowed = "copyMove";
  });
  return item;
}

function showShare(item, column, sharesState, rows) {
  const share = item.querySelector(".column-share");
  if (column.nonnull === null) {
    share.classList.add("unknown");
    share.textContent = sharesState === "pending" ? "…" : "?";
    share.style.removeProperty("--share");
    item.title = `${column.name}（${column.dtype}）`;
  } else {
    share.classList.remove("unknown");
    share.textContent = compactCount(column.nonnull, rows);
    share.style.setProperty("--share", `${column.share * 100}%`);
    item.title = `${column.name}（${column.dtype}、非 null ${column.nonnull.toLocaleString()} 行）`;
  }
}
