// The left pane (the column list and the filter pane): ◀ folds it to the left
// into a strip that keeps the filter's conditions in sight, and the strip
// opens it again; its right edge drags to change its width. Either changes
// the plot area's size, which app.js aggregates again once it settles.
const MIN_WIDTH = 160;
const MAX_WIDTH = 600;

export class LeftPane {
  constructor(root) {
    this.root = root;
    this.strip = root.querySelector("#left-strip");
    this.text = this.strip.querySelector(".strip-text");
    root.querySelector(".left-close").addEventListener("click", () => this.setCollapsed(true));
    this.strip.addEventListener("click", () => this.setCollapsed(false));
    this.attachResize(root.querySelector(".left-resize"));
    this.setFilter(0, "");
  }

  setCollapsed(collapsed) {
    this.root.classList.toggle("collapsed", collapsed);
  }

  // Shows the filter's conditions on the strip: `count` filters, `text` in words.
  setFilter(count, text) {
    this.text.textContent = count ? `フィルタ ${count}：${text}` : "列・フィルタ";
    this.strip.classList.toggle("filtered", count > 0);
    this.strip.title = count ? `列とフィルタの欄を開く\nフィルタ：${text}` : "列とフィルタの欄を開く";
  }

  attachResize(handle) {
    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      const startX = event.clientX;
      const startWidth = this.root.offsetWidth;
      const move = (e) => {
        const width = Math.min(Math.max(startWidth + e.clientX - startX, MIN_WIDTH), MAX_WIDTH);
        this.root.style.width = `${width}px`;
      };
      const up = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });
  }
}
