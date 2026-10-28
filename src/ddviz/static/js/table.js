// Table of the selected rows, in a drawer over the bottom of the plot area.
// The drawer lies over the figure and never changes the plot area's size,
// so opening it or dragging its edge aggregates nothing.
//
// The table has a page of rows (the server's page size) and every column of
// the data: the plot's columns first. Only the columns in view are fetched,
// a chunk at a time: the server reads a page of a chunk's columns in a
// worker (`GET /api/table`), from the column cache or from the source.

const COLUMN_WIDTH = 120;
const INDEX_WIDTH = 90;
// Columns fetched together, and kept around the ones in view.
const CHUNK = 50;
const SCROLL_SETTLE_MS = 120;
const MIN_HEIGHT = 80;
// Heights of the drawer, lowest first: its header only, the height it was
// given (by dragging its edge), and the whole plot area. ▲ and ▼ step
// through them.
const STATES = ["collapsed", "open", "maximized"];
const TITLES = {
  up: { collapsed: "表を開く", open: "描画領域いっぱいに広げる" },
  down: { open: "表を畳む", maximized: "元の高さに戻す" },
};

function formatValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number" && !Number.isInteger(value)) return String(Number(value.toPrecision(6)));
  return String(value);
}

export class SelectionTable {
  constructor(root) {
    this.root = root;
    this.title = root.querySelector(".table-title");
    this.pager = root.querySelector(".table-pager");
    this.scroll = root.querySelector(".table-scroll");
    this.inner = root.querySelector(".table-inner");
    this.grid = root.querySelector(".table-grid");
    this.up = root.querySelector(".table-up");
    this.down = root.querySelector(".table-down");
    this.state = "open";
    this.rows = 0;
    this.offset = 0;
    this.pageSize = 100;
    this.totalColumns = 0;
    this.plotColumns = 0;
    // Fetched chunks of the current page: chunk index -> response, or a
    // promise while it is fetched.
    this.chunks = new Map();
    // Bumped by every new selection or page, so that late answers are dropped.
    this.generation = 0;
    this.timer = null;
    this.scroll.addEventListener("scroll", () => {
      clearTimeout(this.timer);
      this.render();
      this.timer = setTimeout(() => this.fetchInView(), SCROLL_SETTLE_MS);
    });
    root.querySelector(".table-prev").addEventListener("click", () => this.page(-1));
    root.querySelector(".table-next").addEventListener("click", () => this.page(1));
    this.up.addEventListener("click", () => this.step(1));
    this.down.addEventListener("click", () => this.step(-1));
    this.attachResize(root.querySelector(".table-resize"));
  }

  // Drags the drawer's top edge; the drawer covers more or less of the plot.
  attachResize(handle) {
    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      const startY = event.clientY;
      const startHeight = this.root.offsetHeight;
      // Dragging the edge of a maximized table sizes it from there.
      this.root.style.height = `${startHeight}px`;
      this.setState("open");
      const limit = this.root.parentElement.clientHeight;
      const move = (e) => {
        const height = Math.min(Math.max(startHeight + startY - e.clientY, MIN_HEIGHT), limit);
        this.root.style.height = `${height}px`;
        this.render();
      };
      const up = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        this.fetchInView();
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });
  }

  // Raises (1) or lowers (-1) the drawer by one of `STATES`.
  step(by) {
    const i = STATES.indexOf(this.state) + by;
    if (i >= 0 && i < STATES.length) this.setState(STATES[i]);
  }

  // The drawer covers more or less of the plot area, which keeps its size,
  // so nothing is aggregated again.
  setState(state) {
    this.state = state;
    this.root.classList.toggle("collapsed", state === "collapsed");
    this.root.classList.toggle("maximized", state === "maximized");
    this.up.disabled = state === "maximized";
    this.down.disabled = state === "collapsed";
    this.up.title = TITLES.up[state] ?? "";
    this.down.title = TITLES.down[state] ?? "";
    this.render();
    this.fetchInView();
  }

  // Shows a new selection of `rows` rows from its first page; null hides the table.
  show(rows) {
    this.generation++;
    this.chunks.clear();
    if (rows === null) {
      this.root.hidden = true;
      return;
    }
    this.rows = rows;
    this.offset = 0;
    this.root.hidden = false;
    this.scroll.scrollLeft = 0;
    this.scroll.scrollTop = 0;
    this.updateTitle();
    this.fetchInView();
  }

  page(step) {
    const offset = this.offset + step * this.pageSize;
    if (offset < 0 || offset >= this.rows) return;
    this.generation++;
    this.chunks.clear();
    this.offset = offset;
    this.scroll.scrollTop = 0;
    this.updateTitle();
    this.fetchInView();
  }

  updateTitle() {
    this.title.textContent = `選んだ行：${this.rows.toLocaleString()} 行`;
    const last = Math.min(this.offset + this.pageSize, this.rows);
    this.pager.textContent = this.rows ? `${(this.offset + 1).toLocaleString()}–${last.toLocaleString()}` : "0";
    this.root.querySelector(".table-prev").disabled = this.offset === 0;
    this.root.querySelector(".table-next").disabled = last >= this.rows;
  }

  // Returns the chunks of the columns in view.
  chunksInView() {
    const first = Math.max(Math.floor((this.scroll.scrollLeft - INDEX_WIDTH) / COLUMN_WIDTH), 0);
    const count = Math.ceil(this.scroll.clientWidth / COLUMN_WIDTH) + 1;
    const last = this.totalColumns ? Math.min(first + count, this.totalColumns - 1) : first + count;
    const chunks = [];
    for (let c = Math.floor(first / CHUNK); c <= Math.floor(last / CHUNK); c++) chunks.push(c);
    return { first, last, chunks };
  }

  async fetchInView() {
    if (this.root.hidden || this.root.classList.contains("collapsed")) return;
    const { chunks } = this.chunksInView();
    await Promise.all(chunks.map((c) => this.fetchChunk(c)));
  }

  async fetchChunk(chunk) {
    if (this.chunks.has(chunk)) return this.chunks.get(chunk);
    const mine = this.generation;
    const query = new URLSearchParams({ offset: this.offset, col_offset: chunk * CHUNK, col_limit: CHUNK });
    const pending = fetch(`/api/table?${query}`).then(async (response) => {
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    });
    this.chunks.set(chunk, pending);
    this.render();
    try {
      const body = await pending;
      if (mine !== this.generation) return null;
      this.chunks.set(chunk, body);
      this.pageSize = body.page_size;
      this.totalColumns = body.total_columns;
      this.plotColumns = body.plot_columns;
      this.index = body.index;
      this.updateTitle();
      this.render();
      return body;
    } catch (error) {
      if (mine === this.generation) this.chunks.delete(chunk);
      // A newer page or column chunk killed the worker of this one.
      if (!String(error).startsWith("Error: 409")) console.error(error);
      return null;
    }
  }

  // Draws the columns in view from the fetched chunks; the others are
  // blank. The inner element has the width of every column, so the scroll
  // bar spans the whole table.
  render() {
    const rows = this.index?.length ?? 0;
    this.inner.style.width = `${INDEX_WIDTH + this.totalColumns * COLUMN_WIDTH}px`;
    const { first, last } = this.chunksInView();
    const cells = [];
    // The header and the row index stay in view: they move with the scroll.
    const top = this.scroll.scrollTop;
    const header = [`<div class="tc th ti" style="top:${top}px;left:${this.scroll.scrollLeft}px">行番号</div>`];
    for (let c = first; c <= last && c < this.totalColumns; c++) {
      const chunk = this.chunks.get(Math.floor(c / CHUNK));
      const column = chunk && !(chunk instanceof Promise) ? chunk.columns[c % CHUNK] : null;
      const left = INDEX_WIDTH + c * COLUMN_WIDTH;
      const plot = c < this.plotColumns ? " plot" : "";
      const name = column ? column.name : "…";
      const title = column ? `${column.name}（${column.dtype}）` : "";
      header.push(`<div class="tc th${plot}" style="top:${top}px;left:${left}px" title="${escapeHtml(title)}">${escapeHtml(name)}</div>`);
      if (!column) continue;
      column.values.forEach((value, r) => {
        const text = formatValue(value);
        const numeric = typeof value === "number" ? " num" : "";
        cells.push(`<div class="tc${numeric}${plot}" style="left:${left}px;top:${(r + 1) * 24}px" title="${escapeHtml(text)}">${escapeHtml(text)}</div>`);
      });
    }
    const index = (this.index ?? []).map(
      (i, r) => `<div class="tc ti" style="left:${this.scroll.scrollLeft}px;top:${(r + 1) * 24}px">${i}</div>`,
    );
    this.inner.style.height = `${(rows + 1) * 24}px`;
    this.grid.innerHTML = cells.join("") + index.join("") + header.join("");
  }
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}
