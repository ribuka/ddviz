// How the page shows the data's level names: an empty string has no
// visible text, so it is shown as a placeholder (docs/spec.md, "最悪のデータでの表示").
// The placeholder is only shown; conditions and colors keep the real "".
export const EMPTY_LEVEL = "（空文字列）";

// Returns a level's name as shown: the placeholder for an empty string.
export function levelText(name) {
  return name === "" ? EMPTY_LEVEL : String(name);
}
