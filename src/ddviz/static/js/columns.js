// The column list: the server searches the names (`GET /api/columns`) and
// returns the first matches with their count, so a data set of 100,000
// columns never sends them all. Each listed column can be dragged to a role.
// Each shows its rows with a value, which the server counts after Load, over
// a bar as long as their share of the rows; until then the list asks again
// every second, and the controls that filter and sort by the share wait.
import { beginDrag } from "./builder.js";

const LIMIT = 200;
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
  let byShare = false;
  let timer = null;
  // Generation of the latest search, so that an older answer is dropped.
  let generation = 0;

  async function search() {
    clearTimeout(timer);
    const mine = ++generation;
    const query = new URLSearchParams({ q: input.value, limit: LIMIT });
    if (kind) query.set("kind", kind);
    const min = Number(minShare.value);
    if (min > 0) query.set("min_share", min / 100);
    else if (hideEmpty.checked) query.set("min_share", 0);
    if (byShare) query.set("order", "nonnull");
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
    for (const control of [hideEmpty, minShare, orderButton]) control.disabled = found.shares !== "done";
    list.replaceChildren(...found.columns.map((c) => columnItem(c, found.shares, found.rows)));
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
    byShare = !byShare;
    orderButton.classList.toggle("on", byShare);
    search();
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

function columnItem(column, sharesState, rows) {
  const item = document.createElement("div");
  item.className = "column";
  item.draggable = true;
  const type = document.createElement("span");
  type.className = `column-type ${column.numeric ? "numeric" : "categorical"}`;
  // A temporal column is numeric (`ddviz.compute.temporal`), marked apart.
  type.textContent = column.temporal ? "◷" : column.numeric ? "#" : "A";
  const name = document.createElement("span");
  name.className = "column-name";
  name.textContent = column.name;
  const share = document.createElement("span");
  share.className = "column-share";
  if (column.nonnull === null) {
    share.classList.add("unknown");
    share.textContent = sharesState === "pending" ? "…" : "?";
    item.title = `${column.name}（${column.dtype}）`;
  } else {
    share.textContent = compactCount(column.nonnull, rows);
    share.style.setProperty("--share", `${column.share * 100}%`);
    item.title = `${column.name}（${column.dtype}、非 null ${column.nonnull.toLocaleString()} 行）`;
  }
  item.append(type, name, share);
  item.addEventListener("dragstart", (event) => {
    beginDrag({ name: column.name, numeric: column.numeric, temporal: column.temporal });
    event.dataTransfer.setData("text/plain", column.name);
    event.dataTransfer.effectAllowed = "copyMove";
  });
  return item;
}
