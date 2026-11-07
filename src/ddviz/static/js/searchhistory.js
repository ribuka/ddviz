// The search history of the column list (`/api/search-history`): the server
// keeps the keywords of each input across runs, newest first. A keyword goes
// in when a column it found is placed on a role or the filter pane
// (`remember`), not while typing: the search runs on every pause, so the
// words on the way would fill the history.
// Focusing the search box opens the keywords under it; picking one puts it
// in the box and searches. × removes one, and the last row removes them all.
// ↓ and ↑ move through the keywords and Enter picks one; typing or Escape
// closes the list, and ↓ opens it again.

export function attachSearchHistory(input, onPick) {
  let menu = null;
  let words = [];
  // The keyword ↓ and ↑ have moved to, or -1.
  let active = -1;
  // Generation of the latest opening, so that an older answer is dropped.
  let generation = 0;

  async function request(method, query = "", body = undefined) {
    const response = await fetch(`/api/search-history${query}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new Error(await response.text());
    return (await response.json()).words;
  }

  async function open() {
    const mine = ++generation;
    let found;
    try {
      found = await request("GET");
    } catch {
      return;
    }
    if (mine !== generation || document.activeElement !== input) return;
    words = found;
    active = -1;
    render();
  }

  function close() {
    generation++;
    menu?.remove();
    menu = null;
    active = -1;
  }

  function pick(word) {
    close();
    input.value = word;
    onPick();
  }

  async function change(method, query) {
    try {
      words = await request(method, query);
    } catch {
      return;
    }
    active = Math.min(active, words.length - 1);
    if (document.activeElement === input) render();
  }

  function render() {
    menu?.remove();
    menu = null;
    if (!words.length) return;
    menu = document.createElement("div");
    menu.className = "scale-menu search-history";
    // Keep the focus in the box, so that its blur does not close the list.
    menu.addEventListener("pointerdown", (event) => event.preventDefault());
    const heading = document.createElement("div");
    heading.className = "scale-menu-heading";
    heading.textContent = "検索の履歴";
    menu.append(heading);
    words.forEach((word, i) => {
      const row = document.createElement("div");
      row.className = "search-history-row";
      row.classList.toggle("active", i === active);
      const text = document.createElement("button");
      text.type = "button";
      text.className = "search-history-word";
      text.textContent = word;
      text.title = word;
      text.addEventListener("click", () => pick(word));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "search-history-remove";
      remove.textContent = "×";
      remove.title = "履歴から消す";
      remove.addEventListener("click", () => change("DELETE", `?${new URLSearchParams({ word })}`));
      row.append(text, remove);
      menu.append(row);
    });
    const separator = document.createElement("div");
    separator.className = "scale-menu-separator";
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "scale-menu-item search-history-clear";
    clear.textContent = "履歴をすべて消す";
    clear.addEventListener("click", () => change("DELETE"));
    menu.append(separator, clear);
    document.body.append(menu);
    const rect = input.getBoundingClientRect();
    menu.style.left = `${rect.left}px`;
    menu.style.top = `${rect.bottom + 2}px`;
    menu.style.width = `${Math.max(rect.width, 170)}px`;
  }

  input.addEventListener("focus", open);
  input.addEventListener("blur", close);
  input.addEventListener("input", close);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu) {
      event.preventDefault();
      close();
    } else if (event.key === "ArrowDown" && !menu) {
      event.preventDefault();
      open();
    } else if ((event.key === "ArrowDown" || event.key === "ArrowUp") && menu) {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      active = (active + step + words.length + 1) % (words.length + 1);
      if (active === words.length) active = -1;
      render();
    } else if (event.key === "Enter" && menu && active >= 0) {
      event.preventDefault();
      pick(words[active]);
    }
  });

  // Puts the keyword in the box first in the history; a blank one is not kept.
  return function remember() {
    if (!input.value.trim()) return;
    request("POST", "", { word: input.value }).catch(() => {});
  };
}
