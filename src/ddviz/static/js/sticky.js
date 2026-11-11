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

// Gap in pixels between a y tick label and the plot area's edge, and
// between the plot area's bottom edge and an x tick label.
const TICK_GAP = 4;
const X_TICK_TOP = 3;
// Half the height in pixels of a line of a label: a label at an angle turns
// about the middle of its height at its end.
const HALF_LINE = 8;

function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}

// `angleOf(meta, role, index)` is the angle of the tick labels of an axis
// column, in degrees clockwise, or null for level labels.
export class StickyLabels {
  constructor(scroller, gd, angleOf = () => null) {
    this.scroller = scroller;
    this.gd = gd;
    this.angleOf = angleOf;
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
    // A label at an angle may reach past its panel: the label's own axis.
    const label = (strip) => {
      for (const span of strip.querySelectorAll(".tick")) {
        const r = span.getBoundingClientRect();
        if (clientX >= r.left && clientX <= r.right && clientY >= r.top && clientY <= r.bottom) {
          return meta.panels[Number(span.dataset.panel)];
        }
      }
      return null;
    };
    if (inside(this.strips.left, from)) {
      const own = label(this.strips.left);
      if (own) return { axis: "y", panel: own };
      const panel = meta.panels.find((p, i) => {
        const ya = full[axisKey(p.yaxis)];
        const top = origin.top + ya._offset;
        return i % ncol === 0 && clientY >= top && clientY <= top + ya._length;
      });
      return panel ? { axis: "y", panel } : null;
    }
    if (inside(this.strips.bottom)) {
      const own = label(this.strips.bottom);
      if (own) return { axis: "x", panel: own };
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
  // from the plot area's edge, of every panel row, whole (turned) and not
  // cut by the strip, with the gap that sets them off the edge. The labels
  // of a categorical axis not at an angle set leave it out (`leftmargin.js`).
  labelsWidth() {
    const edge = this.strips.left.getBoundingClientRect().right;
    let room = 0;
    for (const span of this.strips.left.querySelectorAll(".tick.y[data-measured]")) {
      room = Math.max(room, edge - span.getBoundingClientRect().left);
    }
    return room;
  }

  // Returns the room in pixels the x tick labels at an angle set of the
  // bottom strip take below the plot area's edge, whole and not cut by the
  // strip; 0 without such labels (`leftmargin.js`).
  labelsHeight() {
    const edge = this.strips.bottom.getBoundingClientRect().top;
    let room = 0;
    for (const span of this.strips.bottom.querySelectorAll(".tick.x[data-measured]")) {
      room = Math.max(room, span.getBoundingClientRect().bottom - edge);
    }
    return room;
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
        const angle = this.angleOf(meta, "y", panel.y);
        const measured = !meta.y_categorical[panel.y] || angle !== null;
        for (const tick of ya?._vals ?? []) {
          // Minor ticks (the axis dialog's) have no labels.
          if (tick.minor) continue;
          const y = ya._offset + ya.l2p(tick.x) - sy - t;
          const span = label("tick y", tick.text, yTickStyle(y, angle), true);
          span.dataset.panel = p;
          if (measured) span.dataset.measured = "";
          yTicks.push(span);
        }
      }
      // The bottom panel of each panel column: a wrapped grid may leave
      // the cells below it empty.
      if (p + ncol >= count) {
        const xa = full[axisKey(panel.xaxis)];
        const angle = this.angleOf(meta, "x", panel.x);
        for (const tick of xa?._vals ?? []) {
          if (tick.minor) continue;
          const x = xa._offset + xa.l2p(tick.x) - sx;
          const span = label("tick x", tick.text, xTickStyle(x, angle), true);
          span.dataset.panel = p;
          if (angle !== null) span.dataset.measured = "";
          xTicks.push(span);
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

// Returns the style of a y tick label at height `y` of the left strip, at
// `angle` (degrees clockwise, or null for level). A label at an angle
// turns about the middle of its height at its end, by the tick's height,
// and moves left so that no corner crosses the gap off the plot area.
function yTickStyle(y, angle) {
  if (angle === null) return { right: `${TICK_GAP}px`, top: `${y}px` };
  const turn = (angle * Math.PI) / 180;
  return {
    right: `${TICK_GAP + HALF_LINE * Math.abs(Math.sin(turn))}px`,
    top: `${y}px`,
    transformOrigin: "100% 50%",
    transform: `translateY(-50%) rotate(${angle}deg)`,
  };
}

// Returns the style of an x tick label at `x` of the bottom strip, at
// `angle` (as `yTickStyle`). A label at an angle turns about the middle of
// its height at the end next to the tick (its start for a clockwise angle,
// its end otherwise), so that it reads away from the axis, and moves down
// so that no corner crosses the gap below the plot area. An angle of 0
// draws the label centered under the tick, as a level one.
function xTickStyle(x, angle) {
  if (!angle) return { left: `${x}px`, top: `${X_TICK_TOP}px` };
  const turn = (angle * Math.PI) / 180;
  const top = X_TICK_TOP + HALF_LINE * Math.abs(Math.cos(turn));
  const start = angle > 0;
  return {
    left: `${x}px`,
    top: `${top}px`,
    transformOrigin: start ? "0 50%" : "100% 50%",
    transform: `${start ? "translateY(-50%)" : "translate(-100%, -50%)"} rotate(${angle}deg)`,
  };
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
