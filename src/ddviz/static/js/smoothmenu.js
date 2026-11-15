// The menu of the smoothing lines, opened by a right click on their element
// icon (elements.js): the method (`ddviz.server.plan.SMOOTH_METHODS`) and
// its parameter, csaps' p or lowess' frac (`ddviz.server.plan.parse_smoothing`).
import { menuHeading, menuItem, Popup } from "./popup.js";

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

const popup = new Popup();

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
  const menu = document.createElement("div");
  menu.className = "scale-menu";
  const item = (text, checked, run) => {
    const pick = () => {
      popup.close();
      if (!checked) run();
    };
    menu.append(menuItem(text, pick, { checked }));
  };
  const heading = (text) => menu.append(menuHeading(text));
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
  popup.open(menu, event);
}
