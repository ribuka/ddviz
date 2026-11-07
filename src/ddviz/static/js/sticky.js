// Tick labels and facet labels of a grid that scrolls, in strips along the
// edges of the area it scrolls in. The grid is laid out as one that fits (its
// panels one pixel apart, labels on the outer panels only), but its outer
// panels scroll out of sight: the strips keep the y ticks of each panel row
// on the left, the x ticks of each panel column at the bottom, and the facet
// labels at the top and on the right, following the scroll and the axes.
// Unscrolled, the strips lie on the figure's margins, where a grid that fits
// has its labels. plotly draws none of them (`ddviz.server.figure`). The
// mode bar, at the figure's top right, follows the scroll the same way and
// stays at the top right of the area, above the top strip.

// Gap in pixels between a y tick label and the plot area's edge.
const TICK_GAP = 4;

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

export class StickyLabels {
  constructor(scroller, gd) {
    this.scroller = scroller;
    this.gd = gd;
    this.meta = null;
    this.root = document.createElement("div");
    this.root.className = "sticky-labels";
    this.root.hidden = true;
    this.strips = {};
    for (const side of ["top", "bottom", "left", "right"]) {
      const strip = document.createElement("div");
      strip.className = `sticky-strip ${side}`;
      this.root.append(strip);
      this.strips[side] = strip;
    }
    // Under the table and the notices that later siblings of the scroller hold.
    scroller.after(this.root);
    scroller.addEventListener("scroll", () => this.draw(), { passive: true });
  }

  // Redraws on every change of the axes (also during a pan drag). Call after
  // each `Plotly.newPlot`, which drops plotly's handlers.
  attach() {
    const draw = () => this.draw();
    for (const event of ["plotly_afterplot", "plotly_relayout", "plotly_relayouting"]) {
      this.gd.on(event, draw);
    }
    this.draw();
  }

  // Shows the labels of a result's grid when it scrolls (its meta), or none.
  set(meta) {
    this.meta = meta;
    this.draw();
  }

  // Returns the axis whose tick labels the left or bottom strip shows at a
  // point (client coordinates), as `{axis: "x" | "y", panel}` (the panel's
  // meta), or null. The strips let the pointer through to the plot below,
  // so the page asks them where an axis's labels are (`axisdialog.js`).
  // The left strip's axis reaches left past the strip, over the gap up to
  // `from` (exclusive; client coordinates), as the margin of a grid that
  // fits does (`yMarginAt`).
  axisAt(clientX, clientY, from = Infinity) {
    const { meta } = this;
    const full = this.gd._fullLayout;
    if (!this.shown || !meta || !full) return null;
    const inside = (strip, left = Infinity) => {
      const r = strip.getBoundingClientRect();
      const after = clientX >= r.left || clientX > left;
      return after && clientX <= r.right && clientY >= r.top && clientY <= r.bottom;
    };
    const origin = this.gd.getBoundingClientRect();
    const { ncol } = meta;
    const count = meta.panels.length;
    if (inside(this.strips.left, from)) {
      const panel = meta.panels.find((p, i) => {
        const ya = full[axisKey(p.yaxis)];
        const top = origin.top + ya._offset;
        return i % ncol === 0 && clientY >= top && clientY <= top + ya._length;
      });
      return panel ? { axis: "y", panel } : null;
    }
    if (inside(this.strips.bottom)) {
      const panel = meta.panels.find((p, i) => {
        const xa = full[axisKey(p.xaxis)];
        const left = origin.left + xa._offset;
        return i + ncol >= count && clientX >= left && clientX <= left + xa._length;
      });
      return panel ? { axis: "x", panel } : null;
    }
    return null;
  }

  // Whether the strips are shown: the grid scrolls.
  get shown() {
    return !this.root.hidden;
  }

  // Returns the room in pixels the y tick labels of the left strip take
  // from the plot area's edge, of every panel row, whole and not cut by the
  // strip: their widest, with the gap that sets them off the edge. The
  // labels of a categorical axis leave it out (`leftmargin.js`).
  labelsWidth() {
    let widest = 0;
    for (const span of this.strips.left.querySelectorAll(".tick.y[data-measured]")) {
      widest = Math.max(widest, span.getBoundingClientRect().width);
    }
    return widest ? widest + TICK_GAP : 0;
  }

  draw() {
    const { meta } = this;
    const full = this.gd._fullLayout;
    const on = Boolean(meta?.scroll && full);
    this.root.hidden = !on;
    const modeBar = this.gd.querySelector(".modebar-container");
    if (!on) {
      if (modeBar) modeBar.style.transform = "";
      return;
    }
    const { l, r, t, b } = full.margin;
    const width = this.scroller.clientWidth;
    const height = this.scroller.clientHeight;
    const sx = this.scroller.scrollLeft;
    const sy = this.scroller.scrollTop;
    if (modeBar) {
      modeBar.style.transform = `translate(${sx + width - full.width}px, ${sy}px)`;
    }
    const place = (strip, left, top, w, h) => {
      Object.assign(strip.style, { left: `${left}px`, top: `${top}px`, width: `${w}px`, height: `${h}px` });
    };
    const { top, bottom, left, right } = this.strips;
    place(top, 0, 0, width, t);
    place(bottom, 0, height - b, width, b);
    place(left, 0, t, l, height - t - b);
    place(right, width - r, t, r, height - t - b);

    const ncol = meta.ncol;
    const count = meta.panels.length;
    // Positions inside a strip: figure pixels less the scroll and the strip's origin.
    const yTicks = [];
    const xTicks = [];
    meta.panels.forEach((panel, p) => {
      if (p % ncol === 0) {
        const ya = full[axisKey(panel.yaxis)];
        const measured = !meta.y_categorical[panel.y];
        for (const tick of ya?._vals ?? []) {
          // Minor ticks (the axis dialog's) have no labels.
          if (tick.minor) continue;
          const y = ya._offset + ya.l2p(tick.x) - sy - t;
          const span = label("tick y", tick.text, { right: `${TICK_GAP}px`, top: `${y}px` }, true);
          if (measured) span.dataset.measured = "";
          yTicks.push(span);
        }
      }
      // The bottom panel of each panel column: a wrapped grid may leave
      // the cells below it empty.
      if (p + ncol >= count) {
        const xa = full[axisKey(panel.xaxis)];
        for (const tick of xa?._vals ?? []) {
          if (tick.minor) continue;
          const x = xa._offset + xa.l2p(tick.x) - sx;
          xTicks.push(label("tick x", tick.text, { left: `${x}px`, top: "3px" }, true));
        }
      }
    });
    const size = full._size;
    const cols = [];
    const rows = [];
    for (const a of meta.facet_labels) {
      if (a.textangle === 90) {
        const y = size.t + (1 - a.y) * size.h - sy - t;
        rows.push(facetLabel("facet row", a, { left: "4px", top: `${y}px` }));
      } else {
        const x = size.l + a.x * size.w - sx;
        cols.push(facetLabel("facet col", a, { left: `${x}px`, bottom: "2px" }));
      }
    }
    left.replaceChildren(...yTicks);
    bottom.replaceChildren(...xTicks);
    top.replaceChildren(...cols);
    right.replaceChildren(...rows);
  }
}

// Returns a facet label's element. One cut to fit its panels
// (`ddviz.server.labeltext`) has its whole text as its tooltip, as plotly's
// hover text has it when the grid fits; it takes the pointer (app.css).
function facetLabel(className, a, style) {
  const span = label(className, a.text, style);
  if (a.hovertext) span.title = a.hovertext;
  return span;
}

// Returns a label element. A tick's text is plotly's, made from a number, and
// may hold markup such as <sup>; a facet label holds the data's levels, so it
// is set as text.
function label(className, text, style, markup = false) {
  const span = document.createElement("span");
  span.className = className;
  if (markup) span.innerHTML = text;
  else span.textContent = text;
  Object.assign(span.style, style);
  return span;
}
