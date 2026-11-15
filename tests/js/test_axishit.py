"""JS: axishit.js finds the axis column under the pointer on the plot."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# Places `gd`, a plot of two panels side by side at the page's (100, 50):
# the left one's plot area is (80, 20)-(280, 170) in the plot's pixels, the
# right one's (320, 20)-(520, 170). A tick label of the left panel's x axis
# lies below its plot area at the page's (200, 230)-(240, 240). `gd` is
# removed after `body` runs.
SETUP = """
  const m = await import("/static/js/axishit.js");
  const gd = document.createElement("div");
  gd.style.cssText = "position: fixed; left: 100px; top: 50px; width: 600px; height: 300px";
  gd._fullLayout = {
    xaxis: { _offset: 80, _length: 200 },
    yaxis: { _offset: 20, _length: 150 },
    xaxis2: { _offset: 320, _length: 200 },
    yaxis2: { _offset: 20, _length: 150 },
  };
  const tick = document.createElement("g");
  tick.className = "xtick";
  const label = document.createElement("text");
  label.style.cssText = "position: fixed; left: 200px; top: 230px; width: 40px; height: 10px; display: block";
  tick.append(label);
  gd.append(tick);
  document.body.append(gd);
  const meta = {
    panels: [
      { x: 0, y: 0, xaxis: "x", yaxis: "y" },
      { x: 1, y: 1, xaxis: "x2", yaxis: "y2" },
    ],
  };
"""


def _call(page: Page, body: str) -> object:
    """Return what `body` returns, run after `SETUP`, and remove `gd`."""
    return page.evaluate(f"async () => {{ {SETUP} try {{ {body} }} finally {{ gd.remove(); }} }}")


def test_y_margin_at_is_the_left_panel_s_margin(js_page: Page) -> None:
    """A point in the left margin of the leftmost panel, its top and bottom edges included, is its y axis."""
    hits = _call(
        js_page,
        "return [[140, 150], [140, 70], [140, 220]].map(([x, y]) => m.yMarginAt(x, y, gd, meta, 0));",
    )
    assert hits == [{"axis": "y", "index": 0}] * 3


def test_y_margin_at_is_null_off_the_margin(js_page: Page) -> None:
    """The plot area's left edge itself, an x up to `from`, and a point above or below the panels are no axis's."""
    hits = _call(
        js_page,
        """return [
          m.yMarginAt(180, 150, gd, meta, 0),
          m.yMarginAt(140, 150, gd, meta, 140),
          m.yMarginAt(130, 150, gd, meta, 140),
          m.yMarginAt(140, 69, gd, meta, 0),
          m.yMarginAt(140, 221, gd, meta, 0),
        ];""",
    )
    assert hits == [None] * 5


def test_label_at_is_null_in_a_plot_area(js_page: Page) -> None:
    """A point in a panel's plot area is the panel's; a point on a tick label outside is its axis."""
    hits = _call(
        js_page,
        "return [m.labelAt(250, 150, gd, meta), m.labelAt(500, 150, gd, meta), m.labelAt(220, 235, gd, meta)];",
    )
    assert hits == [None, None, {"axis": "x", "index": 0}]
