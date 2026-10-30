// The menu of the smoothing lines, opened by a right click on their element
// icon (elements.js): the method (`ddviz.server.plan.SMOOTH_METHODS`) and
// its parameter, csaps' p or lowess' frac (`ddviz.server.plan.parse_smoothing`).

export const METHODS = [
  ["gcv", "GCV 平滑化スプライン"],
  ["csaps", "csaps"],
  ["lowess", "lowess"],
];
// csaps' p offered, with x scaled to [0, 1] (`ddviz.shared.scatter.Smoothing`);
// null picks it from the data.
const PS = [null, 0.5, 0.9, 0.99, 0.999, 0.9999, 0.99999];
// lowess' frac offered; 2/3 is the default, as statsmodels'.
const FRACS = [0.1, 0.2, 0.3, 0.5, 2 / 3];
export const DEFAULT_SMOOTHING = { method: "gcv" };

// The parameters last picked, kept while another method is drawn.
const picked = { p: null, frac: 2 / 3 };

let open = null;

function close() {
  open?.remove();
  open = null;
}

window.addEventListener("pointerdown", (event) => {
  if (open && !open.contains(event.target)) close();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") close();
});

// Returns the text of a smoothing ({method, p, frac}).
export function smoothingText(smoothing) {
  const label = METHODS.find(([key]) => key === smoothing.method)[1];
  if (smoothing.method === "csaps") return `${label}、p = ${smoothing.p ?? "自動"}`;
  if (smoothing.method === "lowess") return `${label}、frac = ${fracText(smoothing.frac)}`;
  return label;
}

function fracText(frac) {
  return Math.abs(frac - 2 / 3) < 1e-9 ? "2/3" : String(frac);
}

// Returns the smoothing of a method with the parameter last picked for it.
function of(method) {
  if (method === "csaps") return { method, p: picked.p };
  if (method === "lowess") return { method, frac: picked.frac };
  return { method };
}

// Opens the menu at a right click. `smoothing` is the current one;
// `onPick` gets the smoothing picked.
export function openSmoothMenu(event, smoothing, onPick) {
  close();
  const menu = document.createElement("div");
  menu.className = "scale-menu";
  const item = (text, checked, run) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scale-menu-item";
    row.classList.toggle("checked", checked);
    row.textContent = text;
    row.addEventListener("click", () => {
      close();
      if (!checked) run();
    });
    menu.append(row);
  };
  const heading = (text) => {
    const head = document.createElement("div");
    head.className = "scale-menu-heading";
    head.textContent = text;
    menu.append(head);
  };
  heading("平滑線の方式");
  for (const [method, text] of METHODS) {
    item(text, smoothing.method === method, () => onPick(of(method)));
  }
  heading("csaps の p（x を 0〜1 にそろえて）");
  for (const p of PS) {
    const on = smoothing.method === "csaps" && (smoothing.p ?? null) === p;
    item(p === null ? "自動" : String(p), on, () => {
      picked.p = p;
      onPick(of("csaps"));
    });
  }
  heading("lowess の frac（使う行の割合）");
  for (const frac of FRACS) {
    const on = smoothing.method === "lowess" && Math.abs(smoothing.frac - frac) < 1e-9;
    item(fracText(frac), on, () => {
      picked.frac = frac;
      onPick(of("lowess"));
    });
  }
  document.body.append(menu);
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(event.clientX, innerWidth - rect.width - 4)}px`;
  menu.style.top = `${Math.min(event.clientY, innerHeight - rect.height - 4)}px`;
  open = menu;
}
