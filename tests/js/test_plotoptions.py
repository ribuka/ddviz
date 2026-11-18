"""JS: plotoptions.js keeps the settings of a plot request and builds its fields."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def _call(page: Page, body: str) -> object:
    """Return what `body` (the body of a function of `o`, a new `PlotOptions`) returns."""
    return page.evaluate(
        f"""async () => {{
          const m = await import("/static/js/plotoptions.js");
          const o = new m.PlotOptions();
          {body}
        }}"""
    )


def test_a_new_one_requests_the_defaults(js_page: Page) -> None:
    """A new `PlotOptions` asks for the defaults of every setting."""
    assert _call(js_page, "return o.request({ symbol: null });") == {
        "color_bins": None,
        "wrap_cols": None,
        "smooth": {"method": "gcv"},
        "shape_size": None,
        "line_width": 2,
        "line_aggregation": "raw",
        "shape_sizes": None,
        "level_shapes": None,
        "show_null_rows": {
            "color": True,
            "symbol": True,
            "row": True,
            "col": True,
            "wrap": True,
        },
        "keep_unfiltered_color_levels": False,
        "keep_unfiltered_symbol_levels": False,
    }


def test_a_level_named_proto_is_a_level(js_page: Page) -> None:
    """The size of the level "__proto__" is a size of a level, not the dictionary's prototype."""
    result = _call(
        js_page,
        """o.setLevelSize("s", "__proto__", 9);
        const sizes = o.request({ symbol: "s" }).shape_sizes;
        return [Object.keys(sizes), sizes["__proto__"], Object.getPrototypeOf(sizes)];""",
    )
    assert result == [["__proto__"], 9, None]


def test_the_size_of_every_series_drops_the_level_sizes(js_page: Page) -> None:
    """After `setShapeSize(11)` the request has the size 11 and no level sizes."""
    result = _call(
        js_page,
        """o.setLevelSize("s", "a", 9);
        o.setShapeSize(11);
        const r = o.request({ symbol: "s" });
        return [r.shape_size, r.shape_sizes];""",
    )
    assert result == [11, None]


def test_level_shapes_stay_with_their_column(js_page: Page) -> None:
    """The shapes are sent for their symbol column only; picking for another column drops them."""
    result = _call(
        js_page,
        """o.setLevelShape("s", "a", "square");
        const before = [o.request({ symbol: "s" }).level_shapes, o.request({ symbol: "t" }).level_shapes];
        const other = o.pickedShapes("t");
        return [...before, other, o.request({ symbol: "s" }).level_shapes];""",
    )
    assert result == [{"a": "square"}, None, None, None]


def test_a_null_shape_drops_the_level_shape(js_page: Page) -> None:
    """A null shape takes the shape of the level's place again."""
    result = _call(
        js_page,
        """o.setLevelShape("s", "a", "square");
        o.setLevelShape("s", "a", null);
        return o.request({ symbol: "s" }).level_shapes;""",
    )
    assert result is None


def test_the_request_copies_show_null_rows(js_page: Page) -> None:
    """Changing the request's `show_null_rows` leaves the settings as they were."""
    result = _call(
        js_page,
        """o.request({ symbol: null }).show_null_rows.color = false;
        return o.showNullRows;""",
    )
    assert result == {
        "color": True,
        "symbol": True,
        "row": True,
        "col": True,
        "wrap": True,
    }


def test_load_sets_back_what_saved_returned(js_page: Page) -> None:
    """`load(saved())` sets back the color's cutting, the number to a row, keeping the levels of Color and of Symbol each, and Show null rows, the last two in the same object."""
    result = _call(
        js_page,
        """o.colorBins = { n: 5, by: "range" };
        o.wrapCols = 3;
        o.keepLevels.symbol = true;
        o.showNullRows.col = false;
        const shown = o.showNullRows;
        const kept = o.keepLevels;
        const state = o.saved();
        o.colorBins = null;
        o.wrapCols = null;
        o.keepLevels.color = true;
        o.keepLevels.symbol = false;
        o.showNullRows.col = true;
        o.showNullRows.wrap = false;
        o.load(state);
        return [
          state,
          o.colorBins,
          o.wrapCols,
          o.keepLevels,
          o.keepLevels === kept,
          o.request({ symbol: null }).keep_unfiltered_symbol_levels,
          o.showNullRows,
          o.showNullRows === shown,
        ];""",
    )
    bins = {"n": 5, "by": "range"}
    show = {"color": True, "symbol": True, "row": True, "col": False, "wrap": True}
    assert result == [
        {
            "colorBins": bins,
            "wrapCols": 3,
            "keepLevels": {"color": False, "symbol": True},
            "showNullRows": show,
        },
        bins,
        3,
        {"color": False, "symbol": True},
        True,
        True,
        show,
        True,
    ]


def test_shared_size_is_null_with_level_sizes(js_page: Page) -> None:
    """The shared size is the meta's without level sizes, null with them, and null without a meta."""
    result = _call(
        js_page,
        """const meta = { marker_size: 7 };
        const without = [o.sharedSize(meta), o.sharedSize(null)];
        o.setLevelSize("s", "a", 9);
        return [...without, o.sharedSize(meta)];""",
    )
    assert result == [7, None, None]
