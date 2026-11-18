"""JS: the constants the JS mirrors from Python hold Python's values.

Each case imports one module and returns one constant (or the part of it the
Python value mirrors); a change on one side only fails the case named
`<file>:<name>` after the JS constant.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from ddviz.compute import boxes, levelindex
from ddviz.server import encoding, figure, plotoptions
from ddviz.shared import missing, palette, scatter

pytestmark = pytest.mark.js

# The values mirrored: a number, a string, or a list of either.
type Value = float | str | list[float] | list[str]

# (JS file, JS expression over the module `m`, Python value), keyed by the case id.
PAIRS: dict[str, tuple[str, str, Value]] = {
    "boxes.js:BAND": ("boxes.js", "m.BAND", scatter.BAND),
    "boxes.js:BOX": ("boxes.js", "m.BOX", boxes.BOX),
    "colorpanel.js:HUES": ("colorpanel.js", "m.HUES", list(palette.DEFAULT_COLORS)),
    "filters.js:LISTED": ("filters.js", "m.LISTED", levelindex.LISTED),
    "plotimage.js:HIDDEN": (
        "plotimage.js",
        "m.HIDDEN",
        figure.HIDDEN_LABELS["tickfont"]["color"],
    ),
    "scalemenu.js:COLOR_BINS_MIN": (
        "scalemenu.js",
        "m.COLOR_BINS_MIN",
        plotoptions.COLOR_BINS_MIN,
    ),
    "shapemenu.js:SIZES": ("shapemenu.js", "m.SIZES", list(plotoptions.SHAPE_SIZES)),
    "shapemenu.js:LINE_WIDTHS": (
        "shapemenu.js",
        "m.LINE_WIDTHS",
        list(plotoptions.LINE_WIDTHS),
    ),
    "shapemenu.js:LINE_AGGREGATIONS": (
        "shapemenu.js",
        "m.LINE_AGGREGATIONS.map((a) => a.value)",
        list(scatter.LINE_AGGREGATIONS),
    ),
    "smoothmenu.js:METHODS": (
        "smoothmenu.js",
        "m.METHODS.map((method) => method[0])",
        list(plotoptions.SMOOTH_METHODS),
    ),
    "elements.js:ELEMENTS": (
        "elements.js",
        "m.ELEMENTS.map((element) => element.name)",
        list(encoding.ELEMENTS),
    ),
    "names.js:MISSING": ("names.js", "m.MISSING", missing.MISSING),
    "names.js:MISSING_TEXT": ("names.js", "m.MISSING_TEXT", missing.MISSING_TEXT),
    "names.js:TEXT_NOTE": ("names.js", "m.TEXT_NOTE", missing.TEXT_NOTE),
    "names.js:MISSING_COLOR": ("names.js", "m.MISSING_COLOR", missing.MISSING_COLOR),
}


def _js_value(page: Page, file: str, expression: str) -> Value:
    """Return `expression` over the module `/static/js/<file>`."""
    return page.evaluate(
        f"""async () => {{
          const m = await import("/static/js/{file}");
          return {expression};
        }}"""
    )


@pytest.mark.parametrize(
    ("file", "expression", "expected"), PAIRS.values(), ids=PAIRS.keys()
)
def test_the_js_constant_holds_the_python_value(
    js_page: Page, file: str, expression: str, expected: Value
) -> None:
    """The JS constant (or the part of it Python's value mirrors) equals Python's value."""
    assert _js_value(js_page, file, expression) == expected
