// The left and bottom margins of a figure: the room its y tick labels, and
// its x tick labels at an angle set, need. The page measures the labels of
// the figure drawn, as they are drawn, and asks the server for a figure of
// those margins (`ddviz.shared.layout.left_margin` and `bottom_margin`,
// whose bounds `fitMargin` and `fitBottom` repeat so that a margin that
// cannot grow is not asked for again). Only the labels of the outer panels
// count, of every panel row and column (also those scrolled out of sight).
// The left margin leaves out the labels of a categorical axis, which cuts
// them to the room of `MARGIN_LEFT` (`bandticks.js`), unless they are at an
// angle set. The bottom margin counts only the labels at an angle set:
// plotly's own fit `MARGIN_BOTTOM`.

// As `ddviz.shared.layout`.
export const MARGIN_LEFT = 50;
export const MARGIN_BOTTOM = 30;
const MARGIN_RIGHT = 30;
const MARGIN_TOP = 54;
const SCROLLBAR = 17;
// Room in pixels left between the figure's edge and the farthest label.
const EDGE_PAD = 2;

// Returns the left margin of an area `width` pixels wide for the margin
// `wanted`: at least `MARGIN_LEFT`, at most one that leaves a pixel of the
// area between it, the right margin and the scroll bar.
export function fitMargin(wanted, width) {
  return Math.max(MARGIN_LEFT, Math.min(wanted, width - MARGIN_RIGHT - SCROLLBAR - 1));
}

// Returns the bottom margin of an area `height` pixels high for the margin
// `wanted`: at least `MARGIN_BOTTOM`, at most one that leaves a pixel of
// the area between it, the top margin and the scroll bar.
export function fitBottom(wanted, height) {
  return Math.max(MARGIN_BOTTOM, Math.min(wanted, height - MARGIN_TOP - SCROLLBAR - 1));
}

// Returns the left margin the y tick labels of the figure drawn in `gd`
// (of `meta`) need, in whole pixels, at least `MARGIN_LEFT`; null without a
// figure. A grid that fits has plotly's labels (the SVG text of each y
// axis's `y<n>tick` groups, whose box holds every line and superscript,
// turned as drawn); one that scrolls has them in the left strip of
// `sticky` (`StickyLabels.labelsWidth`), which is the margin's width.
// `angled(meta, role, index)` tells whether an axis column's labels are at
// an angle set: a categorical one then counts.
export function neededMargin(gd, meta, sticky, angled = () => false) {
  const full = gd._fullLayout;
  if (!full || !meta) return null;
  let room = 0;
  if (meta.scroll) {
    room = sticky.labelsWidth();
  } else {
    const left = gd.getBoundingClientRect().left;
    meta.panels.forEach((panel, i) => {
      if (i % meta.ncol !== 0 || (meta.y_categorical[panel.y] && !angled(meta, "y", panel.y))) return;
      const texts = gd.querySelectorAll(`.${panel.yaxis}tick text`);
      for (const text of texts) {
        const box = text.getBoundingClientRect();
        if (box.width > 0) room = Math.max(room, full.margin.l - (box.left - left));
      }
    });
  }
  return Math.max(MARGIN_LEFT, Math.ceil(room + EDGE_PAD));
}

// Returns the bottom margin the x tick labels of the figure drawn in `gd`
// (of `meta`) at an angle set (`angled`, as `neededMargin`) need, in whole
// pixels, at least `MARGIN_BOTTOM`; null without a figure. Only the bottom
// panel of each panel column shows them: plotly's labels when the grid
// fits, the bottom strip of `sticky` (`StickyLabels.labelsHeight`) when it
// scrolls.
export function neededBottom(gd, meta, sticky, angled = () => false) {
  const full = gd._fullLayout;
  if (!full || !meta) return null;
  let room = 0;
  if (meta.scroll) {
    room = sticky.labelsHeight();
  } else {
    const bottom = gd.getBoundingClientRect().top + full.height - full.margin.b;
    const count = meta.panels.length;
    meta.panels.forEach((panel, i) => {
      if (i + meta.ncol < count || !angled(meta, "x", panel.x)) return;
      for (const text of gd.querySelectorAll(`.${panel.xaxis}tick text`)) {
        const box = text.getBoundingClientRect();
        if (box.height > 0) room = Math.max(room, box.bottom - bottom);
      }
    });
  }
  return Math.max(MARGIN_BOTTOM, Math.ceil(room + EDGE_PAD));
}
