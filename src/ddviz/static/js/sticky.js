// Tick labels and facet labels of a grid that scrolls, in strips along the
// edges of the area it scrolls in. The grid is laid out as one that fits (its
// panels one pixel apart, labels on the outer panels only), but its outer
// panels scroll out of sight: the strips keep the y ticks of each panel row
// on the left, the x ticks of each panel column at the bottom, and the facet
// labels at the top and on the right, following the scroll and the axes.
// Unscrolled, the strips lie on the figure's margins, where a grid that fits
// has its labels. plotly draws none of them (`ddviz.figure`).

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

  draw() {
    const { meta } = this;
    const full = this.gd._fullLayout;
    const on = Boolean(meta?.scroll && full);
    this.root.hidden = !on;
    if (!on) return;
    const { l, r, t, b } = full.margin;
    const width = this.scroller.clientWidth;
    const height = this.scroller.clientHeight;
    const sx = this.scroller.scrollLeft;
    const sy = this.scroller.scrollTop;
    const place = (strip, left, top, w, h) => {
      Object.assign(strip.style, { left: `${left}px`, top: `${top}px`, width: `${w}px`, height: `${h}px` });
    };
    const { top, bottom, left, right } = this.strips;
    place(top, 0, 0, width, t);
    place(bottom, 0, height - b, width, b);
    place(left, 0, t, l, height - t - b);
    place(right, width - r, t, r, height - t - b);

    const ncol = meta.ncol;
    const nrow = meta.panels.length / ncol;
    // Positions inside a strip: figure pixels less the scroll and the strip's origin.
    const yTicks = [];
    const xTicks = [];
    meta.panels.forEach((panel, p) => {
      if (p % ncol === 0) {
        const ya = full[axisKey(panel.yaxis)];
        for (const tick of ya?._vals ?? []) {
          const y = ya._offset + ya.l2p(tick.x) - sy - t;
          yTicks.push(label("tick y", tick.text, { right: "4px", top: `${y}px` }, true));
        }
      }
      if (p >= (nrow - 1) * ncol) {
        const xa = full[axisKey(panel.xaxis)];
        for (const tick of xa?._vals ?? []) {
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
        rows.push(label("facet row", a.text, { left: "4px", top: `${y}px` }));
      } else {
        const x = size.l + a.x * size.w - sx;
        cols.push(label("facet col", a.text, { left: `${x}px`, bottom: "2px" }));
      }
    }
    left.replaceChildren(...yTicks);
    bottom.replaceChildren(...xTicks);
    top.replaceChildren(...cols);
    right.replaceChildren(...rows);
  }
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
