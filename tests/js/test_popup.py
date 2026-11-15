"""JS: popup.js opens, places and closes the right-click menus, and makes their items."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# Places a fixed box of 100 x 50 px at (x, y) and returns its rect, the
# window's size and EDGE, then removes the box.
PLACE = """async ([x, y]) => {
  const m = await import("/static/js/popup.js");
  const box = document.createElement("div");
  box.style.cssText = "position: fixed; width: 100px; height: 50px";
  document.body.append(box);
  m.placeAt(box, x, y);
  const rect = box.getBoundingClientRect();
  box.remove();
  return {
    left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
    width: innerWidth, height: innerHeight, edge: m.EDGE,
  };
}"""

# Makes a Popup whose `onClose` counts in `window.counts.closed` and whose `inside()`
# returns `window.beside`, a box of its own, and a function opening a fixed
# box at (x, y) as `window.box`.
SETUP = """async () => {
  const m = await import("/static/js/popup.js");
  // Popups of earlier tests still listen; this one counts on its own.
  const counts = { closed: 0 };
  window.counts = counts;
  window.beside = document.createElement("div");
  window.beside.style.cssText = "position: fixed; left: 600px; top: 600px; width: 40px; height: 40px";
  document.body.append(window.beside);
  window.popup = new m.Popup({ onClose: () => counts.closed++, inside: () => [window.beside] });
  window.openBox = (x, y) => {
    const box = document.createElement("div");
    box.style.cssText = "position: fixed; width: 100px; height: 50px";
    window.popup.open(box, { clientX: x, clientY: y });
    return box;
  };
}"""

TEARDOWN = """() => {
  window.popup.close();
  window.beside.remove();
  for (const name of ["popup", "beside", "openBox", "counts", "box", "first"]) delete window[name];
}"""

# The state of the popup: whether an element is open, whether it is
# `window.box` and in the page, and the count of `onClose`.
STATE = """() => ({
  open: window.popup.element !== null,
  same: window.popup.element === window.box,
  inPage: document.body.contains(window.box),
  closed: window.counts.closed,
})"""


@pytest.fixture
def popup(js_page: Page) -> Iterator[Page]:
    """Return the page with a Popup set up as SETUP, torn down after the test."""
    js_page.evaluate(SETUP)
    yield js_page
    js_page.evaluate(TEARDOWN)


def test_placeat_keeps_a_point_inside_the_window(js_page: Page) -> None:
    """A point inside the window places the box's top left there."""
    out = js_page.evaluate(PLACE, [200, 150])
    assert (out["left"], out["top"]) == (200, 150)


def test_placeat_moves_the_box_in_from_the_bottom_right(js_page: Page) -> None:
    """Near the bottom right, the box's right and bottom are EDGE px inside the window."""
    width, height = js_page.evaluate("() => [innerWidth, innerHeight]")
    out = js_page.evaluate(PLACE, [width - 10, height - 10])
    assert out["edge"] == 4
    assert (out["right"], out["bottom"]) == (width - 4, height - 4)


def test_placeat_moves_the_box_in_from_the_top_left(js_page: Page) -> None:
    """Outside on the top left, the box's left and top are EDGE px inside the window."""
    out = js_page.evaluate(PLACE, [-50, -30])
    assert (out["left"], out["top"]) == (4, 4)


def test_open_appends_the_element_and_a_second_open_removes_the_first(popup: Page) -> None:
    """`open` adds the element to the body at the point; a second `open` removes the first."""
    out = popup.evaluate("""() => {
      window.first = window.openBox(100, 80);
      const firstIn = window.first.parentElement === document.body;
      const rect = window.first.getBoundingClientRect();
      window.box = window.openBox(300, 200);
      return {
        firstIn, at: [rect.left, rect.top],
        firstGone: !document.body.contains(window.first),
        secondIn: window.box.parentElement === document.body,
      };
    }""")
    assert out == {"firstIn": True, "at": [100, 80], "firstGone": True, "secondIn": True}
    assert popup.evaluate(STATE)["same"]


def test_a_press_inside_does_not_close(popup: Page) -> None:
    """A press in the element or in an element of `inside()` keeps the popup open."""
    popup.evaluate("() => { window.box = window.openBox(100, 80); }")
    popup.mouse.click(150, 100)
    popup.mouse.click(620, 620)
    state = popup.evaluate(STATE)
    assert state["open"] and state["same"] and state["inPage"]


def test_a_press_outside_closes(popup: Page) -> None:
    """A press outside the element and `inside()` closes the popup and calls `onClose`."""
    popup.evaluate("() => { window.box = window.openBox(100, 80); window.counts.closed = 0; }")
    popup.mouse.click(400, 400)
    assert popup.evaluate(STATE) == {"open": False, "same": False, "inPage": False, "closed": 1}


def test_escape_closes(popup: Page) -> None:
    """Escape closes the popup and calls `onClose`."""
    popup.evaluate("() => { window.box = window.openBox(100, 80); window.counts.closed = 0; }")
    popup.keyboard.press("Escape")
    assert popup.evaluate(STATE) == {"open": False, "same": False, "inPage": False, "closed": 1}


def test_close_calls_onclose_when_closed(popup: Page) -> None:
    """`close` calls `onClose` even when no element is open."""
    assert popup.evaluate("() => { window.counts.closed = 0; window.popup.close(); return window.counts.closed; }") == 1


def test_menu_parts(js_page: Page) -> None:
    """`menuItem` has its classes and attributes and calls `onPick` once a click; the heading and separator have theirs."""
    out = js_page.evaluate("""async () => {
      const m = await import("/static/js/popup.js");
      let picks = 0;
      const plain = m.menuItem("A", () => picks++);
      const checked = m.menuItem("B", () => {}, { checked: true });
      const disabled = m.menuItem("C", () => {}, { disabled: true });
      document.body.append(plain);
      plain.click();
      plain.remove();
      const heading = m.menuHeading("H");
      const gap = m.menuSeparator();
      const info = (row) => ({
        tag: row.tagName, type: row.type, className: row.className,
        text: row.textContent, disabled: row.disabled,
      });
      return {
        plain: info(plain), checked: info(checked), disabled: info(disabled), picks,
        heading: [heading.tagName, heading.className, heading.textContent],
        gap: [gap.tagName, gap.className],
      };
    }""")
    base = {"tag": "BUTTON", "type": "button", "className": "scale-menu-item", "disabled": False}
    assert out["plain"] == {**base, "text": "A"}
    assert out["checked"] == {**base, "className": "scale-menu-item checked", "text": "B"}
    assert out["disabled"] == {**base, "text": "C", "disabled": True}
    assert out["picks"] == 1
    assert out["heading"] == ["DIV", "scale-menu-heading", "H"]
    assert out["gap"] == ["DIV", "scale-menu-separator"]


# Places a fixed anchor at (x, y), 80 x 20 px, and a fixed box of 100 x 50 px
# under it with `options`; returns their rects and the window's size, then
# removes both.
PLACE_UNDER = """async ([x, y, options]) => {
  const m = await import("/static/js/popup.js");
  const anchor = document.createElement("div");
  anchor.style.cssText = `position: fixed; left: ${x}px; top: ${y}px; width: 80px; height: 20px`;
  const box = document.createElement("div");
  box.style.cssText = "position: fixed; width: 100px; height: 50px";
  document.body.append(anchor, box);
  m.placeUnder(box, anchor, options);
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
  };
  const out = { anchor: rect(anchor), box: rect(box), width: innerWidth, height: innerHeight };
  anchor.remove();
  box.remove();
  return out;
}"""


def test_placeunder_aligns_left_below_the_anchor(js_page: Page) -> None:
    """Aligned left, the box's left is the anchor's left and its top the anchor's bottom + gap."""
    out = js_page.evaluate(PLACE_UNDER, [200, 100, {"align": "left", "gap": 2}])
    assert (out["box"]["left"], out["box"]["top"]) == (out["anchor"]["left"], out["anchor"]["bottom"] + 2)


def test_placeunder_aligns_right(js_page: Page) -> None:
    """Aligned right, the box's right is the anchor's right."""
    out = js_page.evaluate(PLACE_UNDER, [300, 100, {"align": "right", "gap": 4}])
    assert out["box"]["right"] == out["anchor"]["right"]
    assert out["box"]["top"] == out["anchor"]["bottom"] + 4


def test_placeunder_opens_above_without_room_below(js_page: Page) -> None:
    """With the anchor near the window's bottom, the box's bottom is the anchor's top - gap."""
    height = js_page.evaluate("() => innerHeight")
    out = js_page.evaluate(PLACE_UNDER, [200, height - 30, {"gap": 2}])
    assert out["box"]["bottom"] == out["anchor"]["top"] - 2


def test_placeunder_keeps_the_box_inside_on_the_right(js_page: Page) -> None:
    """With the anchor at the window's right edge, the box's right is EDGE px inside the window."""
    width = js_page.evaluate("() => innerWidth")
    out = js_page.evaluate(PLACE_UNDER, [width - 80, 100, {"align": "left"}])
    assert out["box"]["right"] == width - 4


# Opens a fixed box under `window.anchor`, a fixed button at (100, 100) of
# 80 x 20 px, with the Popup of SETUP.
OPEN_UNDER = """() => {
  window.anchor = document.createElement("button");
  window.anchor.style.cssText = "position: fixed; left: 100px; top: 100px; width: 80px; height: 20px";
  document.body.append(window.anchor);
  window.box = document.createElement("div");
  window.box.style.cssText = "position: fixed; width: 100px; height: 50px";
  window.popup.openUnder(window.box, window.anchor);
  window.counts.closed = 0;
  return window.popup.anchor === window.anchor;
}"""


@pytest.fixture
def under(popup: Page) -> Iterator[Page]:
    """Return the page with a popup opened under an anchor as OPEN_UNDER, the anchor removed after the test."""
    assert popup.evaluate(OPEN_UNDER)
    yield popup
    popup.evaluate("() => { window.anchor.remove(); delete window.anchor; }")


def test_openunder_a_press_on_the_anchor_does_not_close(under: Page) -> None:
    """A press in the anchor keeps the popup open under it."""
    under.mouse.click(140, 110)
    state = under.evaluate(STATE)
    assert state["open"] and state["same"] and state["inPage"]
    assert under.evaluate("() => window.popup.anchor === window.anchor")


def test_openunder_a_press_outside_closes_and_drops_the_anchor(under: Page) -> None:
    """A press outside the popup and its anchor closes it; the anchor is then null."""
    under.mouse.click(400, 400)
    assert under.evaluate(STATE) == {"open": False, "same": False, "inPage": False, "closed": 1}
    assert under.evaluate("() => window.popup.anchor") is None


def test_openunder_escape_closes_and_drops_the_anchor(under: Page) -> None:
    """Escape closes the popup opened under the anchor; the anchor is then null."""
    under.keyboard.press("Escape")
    assert under.evaluate(STATE) == {"open": False, "same": False, "inPage": False, "closed": 1}
    assert under.evaluate("() => window.popup.anchor") is None
