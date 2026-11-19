"""JS: table.js disables the selection table's save button without selected rows (Issue #328)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.js

INDEX = Path(__file__).parents[2] / "src" / "ddviz" / "static" / "index.html"

# Makes the table from the app's markup (read here: a test may leave
# `window.fetch` stubbed in the shared page), shows each count of rows, and
# returns whether the table is hidden and the save button disabled, and its
# title, after each, with the presses that reached the app; then removes it.
SHOW = """async ([html, counts]) => {
  const { SelectionTable } = await import("/static/js/table.js");
  const markup = new DOMParser().parseFromString(html, "text/html");
  const root = document.importNode(markup.getElementById("table"), true);
  document.body.append(root);
  try {
    const table = new SelectionTable(root);
    const pressed = [];
    table.onSave = (button) => pressed.push(button.className);
    const states = [];
    for (const rows of counts) {
      table.show(rows);
      const save = root.querySelector(".table-save");
      if (rows !== null) save.click();
      states.push({ hidden: root.hidden, disabled: save.disabled, title: save.title });
    }
    return { states, pressed };
  } finally {
    root.remove();
  }
}"""

# An empty page of the table: none of its rows matter here.
EMPTY_PAGE = {
    "rows": 0,
    "offset": 0,
    "page_size": 100,
    "index": [],
    "total_columns": 0,
    "col_offset": 0,
    "columns": [],
    "plot_columns": 0,
}


def test_the_save_button_needs_selected_rows(js_page: Page) -> None:
    """Without rows the button is disabled and says why; with rows it opens the menu; without a selection the table hides."""

    def empty(route: Route) -> None:
        route.fulfill(body=json.dumps(EMPTY_PAGE), content_type="application/json")

    js_page.route("**/api/table?*", empty)
    try:
        result = js_page.evaluate(SHOW, [INDEX.read_text(encoding="utf-8"), [0, 5, None]])
    finally:
        js_page.unroute("**/api/table?*", empty)
    no_rows, rows, hidden = result["states"]
    assert no_rows == {"hidden": False, "disabled": True, "title": "選んだ行がありません"}
    assert rows == {
        "hidden": False,
        "disabled": False,
        "title": "選んだ行を保存（CSV / Parquet）",
    }
    assert hidden["hidden"] is True
    # Only the press with rows reaches the app.
    assert result["pressed"] == ["table-save"]
