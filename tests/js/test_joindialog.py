"""JS: joindialog.js, the join dialog's parts: the pairs of keys, `結合` enabled, the column of the same name (Issue #344)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.js

# Opens the dialog, with the page's stylesheet, on a stub of the server: the
# input has `label`, `color` and `x`, the table to join `label_1`, `label_2`,
# `label`, `score` and `color`. The searches list 2 columns at most, the one
# named `exact` first, as the server does; a read waits for
# `window.readGate` when set; `/api/join` answers 400 for the key `color`
# and records each body.
OPEN = """async () => {
  const { JoinDialog } = await import("/static/js/joindialog.js");
  const columns = {
    "/api/columns": ["label", "color", "x"],
    "/api/join/columns": ["label_1", "label_2", "label", "score", "color"],
  };
  window.joinBodies = [];
  window.reads = [];
  window.readGate = null;
  window.fetch = async (url, init) => {
    const answer = (body, status = 200) => new Response(JSON.stringify(body), { status });
    const [path, query] = String(url).split("?");
    if (path in columns) {
      const params = new URLSearchParams(query);
      const q = params.get("q").toLowerCase();
      const found = columns[path].filter((name) => name.includes(q));
      found.sort((a, b) => (a !== params.get("exact")) - (b !== params.get("exact")));
      const listed = found.slice(0, 2).map((name) => ({ name, dtype: "String", numeric: false, temporal: false }));
      return answer({ total: columns[path].length, matched: found.length, columns: listed });
    }
    const body = JSON.parse(init.body);
    if (path === "/api/join/source") {
      window.reads.push(body);
      if (window.readGate) await window.readGate;
      return answer({ paths: body.paths, files: 2, rows: 1500, columns: 5, casts: [] });
    }
    window.joinBodies.push(body);
    if (body.keys.some((key) => key.left === "color")) return answer({ detail: "結合する表でキーが重複しています" }, 400);
    return answer({ added: ["_joined", "score"], rows: 2000, matched: 1500 });
  };
  const style = document.createElement("link");
  Object.assign(style, { rel: "stylesheet", href: "/static/app.css", id: "join-style" });
  await new Promise((resolve) => { style.onload = resolve; document.head.append(style); });
  const dialog = document.createElement("dialog");
  dialog.id = "join-under-test";
  document.body.append(dialog);
  window.joinDone = null;
  const join = new JoinDialog(dialog, { joined: (answer, kind) => { window.joinDone = [answer, kind]; } });
  join.open();
}"""


@pytest.fixture
def dialog(js_page: Page) -> Iterator[Page]:
    """Open the dialog on the stub of the server; remove it after."""
    js_page.evaluate(OPEN)
    yield js_page
    js_page.evaluate("document.getElementById('join-under-test').remove(); document.getElementById('join-style').remove()")


def _read(page: Page) -> None:
    """Enter two paths and read them."""
    page.locator("#join-under-test .join-paths").fill(" a.parquet \n\n b.parquet ")
    page.locator("#join-under-test .join-read").click()
    expect(page.locator("#join-under-test .join-source-result")).to_have_text("2 ファイル・1,500 行・5 列")


def _pick(page: Page, row: int, side: int, typed: str, name: str) -> None:
    """Type `typed` in a key's field and pick `name` among the candidates."""
    field = page.locator("#join-under-test .join-key").nth(row).locator(".join-key-input").nth(side)
    field.fill(typed)
    page.locator(f'#join-under-test .join-candidate[data-name="{name}"]').click()
    expect(field).to_have_value(name)


def _state(page: Page) -> dict:
    """Return the keys' fields, whether each is disabled and confirmed, and the buttons' states."""
    return page.evaluate(
        """() => {
          const dialog = document.getElementById("join-under-test");
          const disabled = (s) => [...dialog.querySelectorAll(s)].map((e) => e.disabled);
          return {
            fields: [...dialog.querySelectorAll(".join-key-input")].map((e) => [e.value, e.disabled, e.classList.contains("confirmed")]),
            remove: disabled(".join-remove-key"),
            add: dialog.querySelector(".join-add-key").disabled,
            join: dialog.querySelector(".join-run").disabled,
            keysHidden: dialog.querySelector(".join-keys-section").hidden,
          };
        }"""
    )


def test_the_texts_and_when_it_may_join(js_page: Page) -> None:
    """The paths, the table read, the toast, and `結合` enabled by the kind and the keys."""
    result = js_page.evaluate(
        """async () => {
          const m = await import("/static/js/joindialog.js");
          return {
            paths: m.parsePaths("  a.parquet\\r\\n\\n   \\nb c.parquet  \\n"),
            source: m.sourceText({ files: 2, rows: 1234567, columns: 1200 }),
            byKey: m.joinedText({ added: ["a", "b", "c"], rows: 2003, matched: 1500 }, "key"),
            none: m.joinedText({ added: ["a"], rows: 0, matched: 0 }, "key"),
            byRows: m.joinedText({ added: ["a", "b"], rows: 10, matched: 10 }, "rows"),
            ready: [
              m.joinReady(false, "rows", []),
              m.joinReady(true, "rows", [{ left: null, right: null }]),
              m.joinReady(true, "key", [{ left: "a", right: "a" }]),
              m.joinReady(true, "key", [{ left: "a", right: "a" }, { left: "b", right: null }]),
              m.joinReady(true, "key", []),
            ],
          };
        }"""
    )
    assert result == {
        "paths": ["a.parquet", "b c.parquet"],
        "source": "2 ファイル・1,234,567 行・1,200 列",
        "byKey": "3 列を結合しました。元の表の 74.9% の行が結合できました。",
        "none": "1 列を結合しました。元の表の 0.0% の行が結合できました。",
        "byRows": "2 列を結合しました。",
        "ready": [False, True, True, False, False],
    }


def test_the_keys_wait_for_the_read_and_rows_are_added_and_removed(dialog: Page) -> None:
    """Before `読む` the keys are disabled; after it, `+ キーを足す` adds a row and `×` removes one, never the last."""
    page = dialog
    assert page.locator("#join-under-test .join-paths").evaluate("(e) => e === document.activeElement")
    assert page.locator("#join-under-test .join-read").is_disabled()
    assert _state(page) == {
        "fields": [["", True, False], ["", True, False]],
        "remove": [True],
        "add": True,
        "join": True,
        "keysHidden": False,
    }
    _read(page)
    assert page.evaluate("window.joinBodies") == []
    assert _state(page)["fields"] == [["", False, False], ["", False, False]]
    assert _state(page)["remove"] == [True]
    page.locator("#join-under-test .join-add-key").click()
    assert _state(page)["remove"] == [False, False]
    assert page.locator("#join-under-test .join-key").nth(1).locator(".join-key-input").first.evaluate(
        "(e) => e === document.activeElement"
    )
    page.locator("#join-under-test .join-remove-key").first.click()
    state = _state(page)
    assert state["remove"] == [True]
    assert len(state["fields"]) == 2


def test_picking_a_column_fills_the_same_name_and_enables_the_join(dialog: Page) -> None:
    """A column picked on the left fills the joined table's empty field of the same name; typed text is not taken."""
    page = dialog
    _read(page)
    _pick(page, 0, 0, "lab", "label")
    right = page.locator("#join-under-test .join-key-input").nth(1)
    expect(right).to_have_value("label")
    assert _state(page)["fields"] == [["label", False, True], ["label", False, True]]
    assert _state(page)["join"] is False

    # Text typed is not a column until one is picked.
    right.fill("sco")
    assert _state(page)["join"] is True
    page.locator("#join-under-test .join-candidate").filter(has_text="score").click()
    assert _state(page)["fields"][1] == ["score", False, True]
    assert _state(page)["join"] is False

    # No column of the same name, or a field already given: nothing is put.
    page.locator("#join-under-test .join-add-key").click()
    _pick(page, 1, 0, "x", "x")
    page.wait_for_timeout(200)
    assert _state(page)["fields"][2:] == [["x", False, True], ["", False, False]]
    assert _state(page)["join"] is True
    _pick(page, 1, 1, "col", "color")
    _pick(page, 1, 0, "lab", "label")
    page.wait_for_timeout(200)
    assert _state(page)["fields"][2:] == [["label", False, True], ["color", False, True]]
    assert _state(page)["join"] is False


def test_the_kind_by_rows_hides_the_keys(dialog: Page) -> None:
    """`行の順で並べる` hides the keys and may join once a table is read; the keys come back as they were."""
    page = dialog
    page.locator("#join-under-test input[value=rows]").check()
    assert _state(page)["keysHidden"] is True
    assert _state(page)["join"] is True
    _read(page)
    assert _state(page)["join"] is False
    page.locator("#join-under-test input[value=key]").check()
    assert _state(page)["keysHidden"] is False
    assert _state(page)["join"] is True


def test_a_refused_join_tells_why_and_a_new_key_joins(dialog: Page) -> None:
    """A refused join shows the server's reason with the dialog open and the fields back; another key joins and closes it."""
    page = dialog
    _read(page)
    _pick(page, 0, 0, "col", "color")
    page.locator("#join-under-test .join-run").click()
    expect(page.locator("#join-under-test .join-error")).to_have_text("結合する表でキーが重複しています")
    assert page.evaluate("document.getElementById('join-under-test').open")
    assert _state(page)["join"] is False
    _pick(page, 0, 0, "lab", "label")
    _pick(page, 0, 1, "label", "label")
    page.locator("#join-under-test .join-run").click()
    page.wait_for_function("window.joinDone !== null")
    assert page.evaluate("document.getElementById('join-under-test').open") is False
    assert page.evaluate("window.joinBodies") == [
        {"kind": "key", "keys": [{"left": "color", "right": "color"}]},
        {"kind": "key", "keys": [{"left": "label", "right": "label"}]},
    ]
    assert page.evaluate("window.joinDone") == [
        {"added": ["_joined", "score"], "rows": 2000, "matched": 1500},
        "key",
    ]


def _candidates(page: Page) -> list[str]:
    """Return the candidates listed under the focused field."""
    return page.locator("#join-under-test .join-candidate").all_inner_texts()


def test_a_column_of_the_name_typed_is_listed_past_the_limit(dialog: Page) -> None:
    """The fields ask for the column of the name typed first: past the limit of the list it is still picked, and filled by its same name (review of #350)."""
    page = dialog
    _read(page)
    right = page.locator("#join-under-test .join-key-input").nth(1)
    right.fill("lab")
    expect(page.locator("#join-under-test .join-candidate")).to_have_text(["label_1", "label_2"])
    right.fill("label")
    expect(page.locator("#join-under-test .join-candidate")).to_have_text(["label", "label_1"])
    right.fill("")
    page.locator("#join-under-test .join-paths").focus()
    _pick(page, 0, 0, "label", "label")
    expect(right).to_have_value("label")
    assert _state(page)["fields"] == [["label", False, True], ["label", False, True]]


def test_editing_what_was_read_waits_for_another_read(dialog: Page) -> None:
    """Paths or the subfolders' check changed after `読む` take back the table read and its keys until another `読む`; spaces and blank lines do not (review of #350)."""
    page = dialog
    paths = page.locator("#join-under-test .join-paths")
    result = page.locator("#join-under-test .join-source-result")
    _read(page)
    _pick(page, 0, 0, "label", "label")
    expect(page.locator("#join-under-test .join-run")).to_be_enabled()

    paths.fill("a.parquet\n  b.parquet  \n\n")
    expect(result).to_have_text("2 ファイル・1,500 行・5 列")
    assert _state(page)["join"] is False

    paths.fill("a.parquet\nc.parquet")
    expect(result).to_have_text("")
    assert _state(page) == {
        "fields": [["", True, False], ["", True, False]],
        "remove": [True],
        "add": True,
        "join": True,
        "keysHidden": False,
    }
    page.locator("#join-under-test .join-read").click()
    expect(result).to_have_text("2 ファイル・1,500 行・5 列")
    _pick(page, 0, 0, "label", "label")
    expect(page.locator("#join-under-test .join-run")).to_be_enabled()

    page.locator("#join-under-test .join-recursive").check()
    expect(result).to_have_text("")
    assert _state(page)["join"] is True
    page.locator("#join-under-test input[value=rows]").check()
    assert _state(page)["join"] is True
    page.locator("#join-under-test .join-read").click()
    expect(result).to_have_text("2 ファイル・1,500 行・5 列")
    expect(page.locator("#join-under-test .join-run")).to_be_enabled()
    assert page.evaluate("window.reads") == [
        {"paths": ["a.parquet", "b.parquet"], "recursive": False},
        {"paths": ["a.parquet", "c.parquet"], "recursive": False},
        {"paths": ["a.parquet", "c.parquet"], "recursive": True},
    ]


def test_a_read_answered_after_an_edit_is_dropped(dialog: Page) -> None:
    """Paths changed while a read is in flight drop its answer: `結合` stays off until the new paths are read (review of #350)."""
    page = dialog
    page.evaluate("() => { window.readGate = new Promise((resolve) => { window.openGate = resolve; }); }")
    paths = page.locator("#join-under-test .join-paths")
    result = page.locator("#join-under-test .join-source-result")
    paths.fill("a.parquet")
    page.locator("#join-under-test .join-read").click()
    expect(result).to_have_text("読んでいます…")
    page.locator("#join-under-test input[value=rows]").check()
    paths.fill("b.parquet")
    expect(result).to_have_text("")
    page.evaluate("window.openGate()")
    page.wait_for_timeout(100)
    expect(result).to_have_text("")
    assert _state(page)["join"] is True
    page.evaluate("window.readGate = null")
    page.locator("#join-under-test .join-read").click()
    expect(result).to_have_text("2 ファイル・1,500 行・5 列")
    expect(page.locator("#join-under-test .join-run")).to_be_enabled()
    assert [r["paths"] for r in page.evaluate("window.reads")] == [["a.parquet"], ["b.parquet"]]
