// The left margin of a figure: the room its y tick labels need. The page
// measures the labels of the figure drawn, as they are drawn, and asks the
// server for a figure of that margin (`ddviz.shared.layout.left_margin`,
// whose bounds `fitMargin` repeats so that a margin that cannot grow is not
// asked for again). Only the labels of the panels of the left column count,
// of every panel row (also those scrolled out of sight), and only those of
// an axis that is not categorical: a categorical axis cuts its labels to
// the room of `MARGIN_LEFT` (`bandticks.js`).

// As `ddviz.shared.layout`.
export const MARGIN_LEFT = 50;
const MARGIN_RIGHT = 30;
const SCROLLBAR = 17;
// Room in pixels left between the figure's left edge and the widest label.
const EDGE_PAD = 2;

// Returns the left margin of an area `width` pixels wide for the margin
// `wanted`: at least `MARGIN_LEFT`, at most one that leaves a pixel of the
// area between it, the right margin and the scroll bar.
export function fitMargin(wanted, width) {
  return Math.max(MARGIN_LEFT, Math.min(wanted, width - MARGIN_RIGHT - SCROLLBAR - 1));
}

// Returns the left margin the y tick labels of the figure drawn in `gd`
// (of `meta`) need, in whole pixels, at least `MARGIN_LEFT`; null without a
// figure. A grid that fits has plotly's labels (the SVG text of each y
// axis's `y<n>tick` groups, whose box holds every line and superscript);
// one that scrolls has them in the left strip of `sticky`
// (`StickyLabels.labelsWidth`), which is the margin's width.
export function neededMargin(gd, meta, sticky) {
  const full = gd._fullLayout;
  if (!full || !meta) return null;
  let room = 0;
  if (meta.scroll) {
    room = sticky.labelsWidth();
  } else {
    const left = gd.getBoundingClientRect().left;
    meta.panels.forEach((panel, i) => {
      if (i % meta.ncol !== 0 || meta.y_categorical[panel.y]) return;
      const texts = gd.querySelectorAll(`.${panel.yaxis}tick text`);
      for (const text of texts) {
        const box = text.getBoundingClientRect();
        if (box.width > 0) room = Math.max(room, full.margin.l - (box.left - left));
      }
    });
  }
  return Math.max(MARGIN_LEFT, Math.ceil(room + EDGE_PAD));
}
