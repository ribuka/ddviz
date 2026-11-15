// Whether a key is an Enter that does not commit an IME conversion. Every
// Enter of the page's fields (apply, add, pick, leave the field) goes
// through this, so the Enter that commits a Japanese word does nothing.
export function plainEnter(event) {
  return event.key === "Enter" && !event.isComposing && event.keyCode !== 229;
}
