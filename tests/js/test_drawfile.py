"""JS: the columns of the drawing settings and their check against the data loaded (`static/js/drawfile.js`, Issue #287)."""

from __future__ import annotations

import copy

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# A dialog's settings with a line of a statistic (Issue #313), kept as they are.
STAT_DIALOG = {"ticks": None, "format": None, "lines": [{"kind": "stat", "stat": "mean", "label": ""}]}

SETTINGS = {
    "zones": {
        "encoding": {
            "x": ["a"],
            "y": ["b", "e"],
            "color": "c",
            "symbol": "s",
            "row": None,
            "col": None,
            "wrap": "w",
            "elements": ["points", "smooth"],
        },
        "numeric": [["a", True], ["b", True], ["c", False], ["e", True], ["s", False], ["w", False]],
        "temporal": [["a", None], ["b", None], ["c", None], ["e", None], ["s", None], ["w", None]],
        "stashed": ["symbol", "wrap"],
    },
    "elements": {"chosen": ["points", "smooth"], "blocked": ["box"]},
    "options": {
        "colorBins": [10, 20],
        "smoothing": {"method": "lowess"},
        "shapeSize": 9,
        "lineWidth": 2,
        "lineAggregation": "mean",
        "showNullRows": {"color": True, "symbol": True, "row": True, "col": True, "wrap": True},
        "keepLevels": {"color": False, "symbol": True},
        "wrapCols": 3,
        "levelSizes": [["s", {"x": 12}], ["w", {"y": 4}]],
        "levelShapes": {"column": "s", "shapes": {"x": "square"}},
    },
    "axes": {
        "dialog": [["b", {"ticks": 5}], ["d", STAT_DIALOG]],
        "angles": [["x:a", 45], ["y:b", 30]],
        "logs": {"x": ["a"], "y": ["b"]},
        "reversed": {"x": [], "y": ["b", "e"]},
        "keepLevels": ["b", "w"],
    },
    "filters": [
        {"name": "a", "numeric": True, "range": [1, 2], "levels": [], "contains": "", "nulls": {}, "mode": "", "query": "", "order": "name"},
        {"name": "f", "numeric": False, "range": None, "levels": ["gone"], "contains": "", "nulls": {}, "mode": "", "query": "", "order": "name"},
    ],
}
COLUMNS = {
    "a": "numeric",
    "b": "numeric",
    "c": "categorical",
    "d": "numeric",
    "e": "numeric",
    "f": "categorical",
    "s": "categorical",
    "w": "categorical",
}


def run(page: Page, settings: dict, columns: dict, kinds: dict) -> dict:
    """Return `reconcile(settings, columns, kinds)` and the settings passed, after it."""
    return page.evaluate(
        """async ([settings, columns, kinds]) => {
          const m = await import("/static/js/drawfile.js");
          const result = m.reconcile(settings, columns, kinds);
          return { ...result, given: settings };
        }""",
        [settings, columns, kinds],
    )


def test_referenced_columns_are_every_place_of_the_settings(js_page: Page) -> None:
    """The zones (stashed too), filters, axes and legend settings name the columns, sorted once each."""
    names = js_page.evaluate(
        """async (settings) => (await import("/static/js/drawfile.js")).referencedColumns(settings)""",
        SETTINGS,
    )
    assert names == sorted(COLUMNS)


def test_columns_missing_or_of_another_kind_leave_every_place(js_page: Page) -> None:
    """A column the data lacks (c, f, s) or holds with another kind (b) leaves the zones, filters, axes and legend; the others stay."""
    kinds = {**COLUMNS, "b": "categorical", "c": None, "f": None, "s": None}
    result = run(js_page, SETTINGS, COLUMNS, kinds)
    assert result["given"] == SETTINGS
    assert result["dropped"] == ["b", "c", "f", "s"]
    got = result["settings"]
    zones = got["zones"]
    assert zones["encoding"] == {
        **SETTINGS["zones"]["encoding"],
        "y": ["e"],
        "color": None,
        "symbol": None,
    }
    assert zones["numeric"] == [["a", True], ["e", True], ["w", False]]
    assert zones["temporal"] == [["a", None], ["e", None], ["w", None]]
    # The stashed Symbol has no column left; the stashed Wrap keeps its own.
    assert zones["stashed"] == ["wrap"]
    assert [card["name"] for card in got["filters"]] == ["a"]
    assert got["axes"] == {
        "dialog": [["d", STAT_DIALOG]],
        "angles": [["x:a", 45]],
        "logs": {"x": ["a"], "y": []},
        "reversed": {"x": [], "y": ["e"]},
        "keepLevels": ["w"],
    }
    assert got["options"]["levelSizes"] == [["w", {"y": 4}]]
    assert got["options"]["levelShapes"] is None
    # The color column gone drops its bins; the wrap's number stays with its column.
    assert got["options"]["colorBins"] is None
    assert got["options"]["wrapCols"] == 3
    assert got["elements"] == SETTINGS["elements"]


def test_matching_columns_stay_as_they_are(js_page: Page) -> None:
    """With every column there with its kind, the settings come back unchanged, the statistic's line too."""
    result = run(js_page, SETTINGS, COLUMNS, COLUMNS)
    assert result == {"settings": SETTINGS, "dropped": [], "given": SETTINGS}


def test_a_wrap_column_taken_out_drops_its_number_and_its_stash(js_page: Page) -> None:
    """The wrap's number to a row goes with its column, as removing the chip by hand does."""
    result = run(js_page, SETTINGS, COLUMNS, {**COLUMNS, "w": "numeric"})
    got = result["settings"]
    assert result["dropped"] == ["w"]
    assert got["zones"]["encoding"]["wrap"] is None
    assert got["zones"]["stashed"] == ["symbol"]
    assert got["options"]["wrapCols"] is None
    assert got["options"]["colorBins"] == [10, 20]


def test_the_elements_follow_the_axis_columns_left(js_page: Page) -> None:
    """Without a numeric y left, the smoothing lines are turned off and the points drawn, as the icons do."""
    settings = copy.deepcopy(SETTINGS)
    settings["zones"]["encoding"]["y"] = ["b"]
    result = run(js_page, settings, COLUMNS, {**COLUMNS, "b": None})
    got = result["settings"]
    assert got["zones"]["encoding"]["y"] == []
    assert got["zones"]["encoding"]["elements"] == ["points"]
    assert got["elements"] == {"chosen": ["points"], "blocked": ["box", "line", "smooth"]}


def test_a_column_the_file_does_not_list_is_taken_out(js_page: Page) -> None:
    """A column the settings name but the file lists no kind of is taken as not matching."""
    columns = {name: kind for name, kind in COLUMNS.items() if name != "d"}
    result = run(js_page, SETTINGS, columns, COLUMNS)
    assert result["dropped"] == ["d"]
    assert result["settings"]["axes"]["dialog"] == [["b", {"ticks": 5}]]


def test_the_attachment_name_and_the_warning(js_page: Page) -> None:
    """The file name comes from the server's `Content-Disposition`; the warning lists the columns."""
    result = js_page.evaluate(
        """async () => {
          const m = await import("/static/js/drawfile.js");
          return [
            m.attachmentName("attachment; filename*=UTF-8''%E5%A3%B2%E4%B8%8A.ddviz.json", "x"),
            m.attachmentName(null, "fallback.json"),
            m.droppedText(["a", "b"]),
          ];
        }"""
    )
    assert result == [
        "売上.ddviz.json",
        "fallback.json",
        "描画設定のうち、データに無い列か種類の違う列を外しました：a, b",
    ]
