// Icons above the figure that choose the elements of the graph
// (`ddviz.server.encoding.ELEMENTS`): points, box plots and smoothing lines.
// Each icon toggles its element, and several are drawn one over another.
// An element that cannot be drawn yet shows its icon, which cannot be
// pressed; nor can the last element that can be drawn be turned off.

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
    drawn: false,
    svg: '<path d="M11 2v4M11 15v5M8 2h6M8 20h6" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="6" y="6" width="10" height="9" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6 10h10" stroke="currentColor" stroke-width="1.5"/>',
  },
  {
    name: "smooth",
    label: "平滑線",
    drawn: false,
    svg: '<path d="M2 17C6 17 7 6 11 6s5 9 9 7" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  },
];

export class ElementBar {
  // `root` takes the icons; `onChange` gets the chosen elements, in the
  // order of `ELEMENTS`, after each toggle.
  constructor(root, onChange) {
    this.chosen = new Set(["points"]);
    this.onChange = onChange;
    this.buttons = ELEMENTS.map((element) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "element";
      button.dataset.element = element.name;
      button.innerHTML = `<svg viewBox="0 0 22 22" width="18" height="18" fill="currentColor" aria-hidden="true">${element.svg}</svg>`;
      button.setAttribute("aria-label", element.label);
      button.addEventListener("click", () => this.toggle(element));
      root.append(button);
      return button;
    });
    this.render();
  }

  toggle(element) {
    if (!element.drawn) return;
    if (this.chosen.has(element.name)) {
      if (!this.othersDrawn(element)) return;
      this.chosen.delete(element.name);
    } else {
      this.chosen.add(element.name);
    }
    this.render();
    this.onChange(ELEMENTS.map((e) => e.name).filter((name) => this.chosen.has(name)));
  }

  // Whether an element other than `element` that can be drawn is chosen.
  othersDrawn(element) {
    return ELEMENTS.some((e) => e !== element && e.drawn && this.chosen.has(e.name));
  }

  render() {
    ELEMENTS.forEach((element, i) => {
      const button = this.buttons[i];
      const on = this.chosen.has(element.name);
      button.classList.toggle("on", on);
      button.setAttribute("aria-pressed", String(on));
      button.disabled = !element.drawn;
      button.title = !element.drawn
        ? `${element.label}（まだ描けない）`
        : on && !this.othersDrawn(element)
          ? `${element.label}（ほかに描く要素がないので外せない）`
          : `${element.label}：押して${on ? "外す" : "重ねる"}`;
    });
  }
}
