// The column list: the server searches the names (`GET /api/columns`) and
// returns the first matches with their count, so a data set of 100,000
// columns never sends them all. Each listed column can be dragged to a role.
import { beginDrag } from "./builder.js";

const LIMIT = 200;
const SEARCH_DELAY_MS = 150;

export function attachColumnList(root) {
  const input = root.querySelector(".column-search");
  const kinds = root.querySelectorAll("[data-kind]");
  const count = root.querySelector(".column-count");
  const list = root.querySelector(".column-list");
  let kind = null;
  let timer = null;
  // Generation of the latest search, so that an older answer is dropped.
  let generation = 0;

  async function search() {
    const mine = ++generation;
    const query = new URLSearchParams({ q: input.value, limit: LIMIT });
    if (kind) query.set("kind", kind);
    const response = await fetch(`/api/columns?${query}`);
    if (mine !== generation) return;
    if (!response.ok) {
      count.textContent = `エラー: ${await response.text()}`;
      return;
    }
    const found = await response.json();
    const shown = found.matched > found.columns.length ? `、上位 ${found.columns.length} 件を表示` : "";
    count.textContent = `${found.total.toLocaleString()} 列中 ${found.matched.toLocaleString()} 件${shown}`;
    list.replaceChildren(...found.columns.map(columnItem));
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(search, SEARCH_DELAY_MS);
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

function columnItem(column) {
  const item = document.createElement("div");
  item.className = "column";
  item.draggable = true;
  item.title = `${column.name}（${column.dtype}）`;
  const type = document.createElement("span");
  type.className = `column-type ${column.numeric ? "numeric" : "categorical"}`;
  type.textContent = column.numeric ? "#" : "A";
  const name = document.createElement("span");
  name.className = "column-name";
  name.textContent = column.name;
  item.append(type, name);
  item.addEventListener("dragstart", (event) => {
    beginDrag({ name: column.name, numeric: column.numeric });
    event.dataTransfer.setData("text/plain", column.name);
    event.dataTransfer.effectAllowed = "copyMove";
  });
  return item;
}
