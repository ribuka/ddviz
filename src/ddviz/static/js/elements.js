// Icons above the figure that choose the elements of the graph
// (`ddviz.server.encoding.ELEMENTS`): points, box plots and smoothing lines.
// Each icon toggles its element, and several are drawn one over another.
// An element that cannot be drawn yet shows its icon, which cannot be
// pressed; nor can the last element that can be drawn be turned off. Box
// plots need a categorical X column and a numeric Y column, or numeric Y
// columns alone (`ddviz.server.plan.has_box_pair`), smoothing lines a numeric X column and
// a numeric Y column (`ddviz.server.plan.has_smooth_pair`): without them,
// their icon cannot be pressed either. A right click on the smoothing
// lines' icon opens their menu (smoothmenu.js).

const ELEMENTS = [
  {
    name: "points",
    label: "点",
    drawn: true,
    svg: '<circle cx="5" cy="12" r="2"/><circle cx="10" cy="6" r="2"/><circle cx="14" cy="13" r="2"/><circle cx="18" cy="5" r="2"/>',
  },
  {
    name: "box",
    label: "箱ひげ図",
    drawn: true,
    needs: "X にカテゴリの列か何も置かず、Y に数値の列を置くと描ける",
    svg: '<path d="M11 2v4M11 15v5M8 2h6M8 20h6" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="6" y="6" width="10" height="9" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6 10h10" stroke="currentColor" stroke-width="1.5"/>',
  },
  {
    name: "smooth",
    label: "平滑線",
    drawn: true,
    needs: "X と Y に数値の列を置くと描ける",
    svg: '<path d="M2 17C6 17 7 6 11 6s5 9 9 7" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  },
];

export class ElementBar {
  // `root` takes the icons; `onChange` gets the chosen elements, in the
  // order of `ELEMENTS`, after each toggle; `onSmoothMenu` the right click's
  // event on the smoothing lines' icon.
  constructor(root, onChange, onSmoothMenu) {
    this.chosen = new Set(["points"]);
    // Elements the graph cannot have now, though they can be drawn.
    this.blocked = new Set(["box", "smooth"]);
    // How the smoothing lines are fitted, shown in their icon's title.
    this.smoothText = "";
    this.onChange = onChange;
    this.buttons = ELEMENTS.map((element) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "element";
      button.dataset.element = element.name;
      button.innerHTML = `<svg viewBox="0 0 22 22" width="18" height="18" fill="currentColor" aria-hidden="true">${element.svg}</svg>`;
      button.setAttribute("aria-label", element.label);
      button.addEventListener("click", () => this.toggle(element));
      if (element.name === "smooth") {
        button.addEventListener("contextmenu", (event) => {
          event.preventDefault();
          if (this.usable(element)) onSmoothMenu(event);
        });
      }
      root.append(button);
      return button;
    });
    this.render();
  }

  // Whether `element` can be pressed now.
  usable(element) {
    return element.drawn && !this.blocked.has(element.name);
  }

  // Lets each element of `allowed` (name to whether the graph can have it)
  // be chosen or not. Elements chosen are turned off when they no longer can
  // be, the points turned on when nothing else is left; returns whether the
  // chosen elements changed (`onChange` got them).
  allow(allowed) {
    let changed = false;
    for (const [name, ok] of Object.entries(allowed)) {
      if (ok) this.blocked.delete(name);
      else this.blocked.add(name);
      if (!ok && this.chosen.delete(name)) changed = true;
    }
    if (changed && !ELEMENTS.some((e) => this.usable(e) && this.chosen.has(e.name))) {
      this.chosen.add("points");
    }
    this.render();
    if (changed) this.emit();
    return changed;
  }

  // Shows how the smoothing lines are fitted in their icon's title.
  setSmoothText(text) {
    this.smoothText = text;
    this.render();
  }

  emit() {
    this.onChange(ELEMENTS.map((e) => e.name).filter((name) => this.chosen.has(name)));
  }

  toggle(element) {
    if (!this.usable(element)) return;
    if (this.chosen.has(element.name)) {
      if (!this.othersDrawn(element)) return;
      this.chosen.delete(element.name);
    } else {
      this.chosen.add(element.name);
    }
    this.render();
    this.emit();
  }

  // Whether an element other than `element` that can be drawn is chosen.
  othersDrawn(element) {
    return ELEMENTS.some((e) => e !== element && this.usable(e) && this.chosen.has(e.name));
  }

  render() {
    ELEMENTS.forEach((element, i) => {
      const button = this.buttons[i];
      const on = this.chosen.has(element.name);
      button.classList.toggle("on", on);
      button.setAttribute("aria-pressed", String(on));
      button.disabled = !this.usable(element);
      const label =
        element.name === "smooth" && this.smoothText ? `${element.label}（${this.smoothText}）` : element.label;
      const menu = element.name === "smooth" ? "。右クリックで方式を選ぶ" : "";
      button.title = !element.drawn
        ? `${label}（まだ描けない）`
        : this.blocked.has(element.name)
          ? `${label}（${element.needs}）`
          : on && !this.othersDrawn(element)
          ? `${label}（ほかに描く要素がないので外せない）${menu}`
          : `${label}：押して${on ? "外す" : "重ねる"}${menu}`;
    });
  }
}
