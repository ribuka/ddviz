"""JS: axisdirection.js turns ranges and keeps the direction of each column's axes."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def test_ascending_and_oriented_at_their_edges(js_page: Page) -> None:
    """Ranges read back ascending and go to plotly descending only on a reversed axis, down to the smallest doubles and an empty range."""
    checks = js_page.evaluate(
        """async () => {
          const { ascending, oriented } = await import("/static/js/axisdirection.js");
          return [
            ascending([1, 2]), ascending([2, 1]), ascending([3, 3]),
            oriented([1, 2], true), oriented([2, 1], true), oriented([2, 1], false),
            oriented([-5e-324, 5e-324], true), oriented([3, 3], true),
          ];
        }"""
    )
    assert checks[0] == [1, 2] and checks[1] == [1, 2] and checks[2] == [3, 3]
    assert checks[3:6] == [[2, 1], [2, 1], [1, 2]]
    assert checks[6] == [5e-324, -5e-324] and checks[7] == [3, 3]


def test_facets_turn_together_and_the_other_axes_stay(js_page: Page) -> None:
    """The facets of a column turn together; a second X column and the same column on Y stay as they are."""
    result = js_page.evaluate(
        """async () => {
          const { AxisDirections } = await import("/static/js/axisdirection.js");
          // X: x then y, Y: x, in two facets: x's axes are the 1st and 3rd.
          const meta = {
            x_columns: ["x", "y"],
            y_columns: ["x"],
            panels: [
              { xaxis: "x", yaxis: "y", x: 0, y: 0 },
              { xaxis: "x2", yaxis: "y2", x: 1, y: 0 },
              { xaxis: "x3", yaxis: "y3", x: 0, y: 0 },
              { xaxis: "x4", yaxis: "y4", x: 1, y: 0 },
            ],
          };
          const directions = new AxisDirections();
          directions.set("x", "x", true);
          const reversed = directions.byAxis(meta);
          directions.set("x", "x", false);
          const back = directions.byAxis(meta);
          return { reversed, back };
        }"""
    )
    assert result["reversed"] == {
        "x": True, "x2": False, "x3": True, "x4": False,
        "y": False, "y2": False, "y3": False, "y4": False,
    }
    assert not any(result["back"].values())


def test_a_reversed_log_axis_stays_log(js_page: Page) -> None:
    """A reversed log axis goes to plotly descending in exponents, and a zoom on it sends its values ascending."""
    result = js_page.evaluate(
        """async () => {
          const { ascending, oriented } = await import("/static/js/axisdirection.js");
          const { toValues } = await import("/static/js/axisscale.js");
          return {
            drawn: oriented([-0.5, 2.5], true),
            sent: toValues(true, ascending([0, -1])),
          };
        }"""
    )
    assert result["drawn"] == [2.5, -0.5]
    assert result["sent"] == [pytest.approx(0.1), pytest.approx(1.0)]
