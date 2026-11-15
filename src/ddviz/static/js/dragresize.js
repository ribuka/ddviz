// Drags of an edge that changes a pane's size (the filter pane, the left
// pane and the selection table, Issue #198): a drag starts on a press of the
// primary button only, and ends on pointerup or pointercancel.

// Calls `start(event)` on a press of the primary button on `handle`, and
// captures the pointer. `start` returns `{ move(e), end() }`: `move` gets
// each pointermove until the drag ends, `end` is called once when it ends,
// on pointerup or pointercancel. Every listener but the pointerdown one is
// removed then.
export function attachDrag(handle, start) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    const drag = start(event);
    const move = (e) => drag.move(e);
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      drag.end();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  });
}
