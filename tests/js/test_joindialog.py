"""JS: joindialog.js, the join dialog's parts: the pairs of keys, `結合` enabled, the column of the same name (Issue #344), the columns to add (Issue #358)."""

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
  const join = new JoinDialog(dialog, { joined: (answer, kind, sameNames) => { window.joinDone = [answer, kind, sameNames]; } });
  window.joinDialog = join;
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
            fields: [...dialog.querySelectorAll(".join-keys .join-key-input")].map((e) => [e.value, e.disabled, e.classList.contains("confirmed")]),
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
            skippedByKey: m.joinedText({ added: ["a", "b", "c"], rows: 2003, matched: 1500, skipped: ["d", "e"] }, "key", "skip"),
            skippedByRows: m.joinedText({ added: ["a"], rows: 10, matched: 10, skipped: Array(1200).fill("d") }, "rows", "skip"),
            noneSkipped: m.joinedText({ added: ["a"], rows: 10, matched: 10, skipped: [] }, "rows", "skip"),
            equalByKey: m.joinedText({ added: ["a", "b"], rows: 4, matched: 2, skipped: ["d"] }, "key", "skip_equal"),
            equalByRows: m.joinedText({ added: ["a"], rows: 10, matched: 10, skipped: Array(1200).fill("d") }, "rows", "skip_equal"),
            noneEqual: m.joinedText({ added: ["a"], rows: 10, matched: 10, skipped: [] }, "rows", "skip_equal"),
            renamed: m.joinedText({ added: ["a"], rows: 10, matched: 10, skipped: [] }, "rows", "rename"),
            comparing: [
              m.comparingText({ type: "progress", stage: "compare", done: 0, total: 10, column: "temp" }),
              m.comparingText({ type: "progress", stage: "compare", done: 1199, total: 1200, column: "lot id" }),
            ],
            picked: [
              m.joinReady(true, "rows", [], []),
              m.joinReady(true, "rows", [], ["a", null]),
              m.joinReady(true, "rows", [], ["a", "b"]),
              m.joinReady(true, "key", [{ left: "a", right: "a" }], [null]),
              m.joinReady(true, "key", [{ left: "a", right: "a" }], ["b"]),
              m.joinReady(true, "key", [{ left: "a", right: null }], ["b"]),
              m.joinReady(false, "rows", [], ["b"]),
            ],
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
        "skippedByKey": "3 列を結合しました。元の表の 74.9% の行が結合できました。元の表と同じ名前の 2 列は足しませんでした。",
        "skippedByRows": "1 列を結合しました。元の表と同じ名前の 1,200 列は足しませんでした。",
        "noneSkipped": "1 列を結合しました。",
        "equalByKey": "2 列を結合しました。元の表の 50.0% の行が結合できました。元の表と名前も中身も同じ 1 列は足しませんでした。",
        "equalByRows": "1 列を結合しました。元の表と名前も中身も同じ 1,200 列は足しませんでした。",
        "noneEqual": "1 列を結合しました。",
        "renamed": "1 列を結合しました。",
        "comparing": [
            "同じ名前の列を比べています（1 / 10）：temp",
            "同じ名前の列を比べています（1200 / 1200）：lot id",
        ],
        "picked": [False, False, True, False, True, False, False],
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
        {"kind": "key", "keys": [{"left": "color", "right": "color"}], "columns": None, "same_names": "rename"},
        {"kind": "key", "keys": [{"left": "label", "right": "label"}], "columns": None, "same_names": "rename"},
    ]
    assert page.evaluate("window.joinDone") == [
        {"added": ["_joined", "score"], "rows": 2000, "matched": 1500},
        "key",
        "rename",
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


def _added(page: Page) -> dict:
    """Return the section `足す列`: the radios of the mode and of the same names (checked, disabled, the label and the texts of the latter), what is hidden, and the lines of the columns."""
    return page.evaluate(
        """() => {
          const section = document.querySelector("#join-under-test .join-added");
          const radios = [...section.querySelectorAll(".join-added-mode input")];
          const same = section.querySelector(".join-same-names");
          const sames = [...same.querySelectorAll("input[type=radio]")];
          const add = section.querySelector(".join-add-column");
          return {
            hidden: section.hidden,
            mode: radios.filter((e) => e.checked).map((e) => e.value),
            radiosOff: radios.map((e) => e.disabled),
            same: {
              label: same.querySelector(".join-same-names-label").textContent,
              texts: sames.map((e) => [e.value, e.closest("label").textContent.trim()]),
              checked: sames.filter((e) => e.checked).map((e) => e.value),
              off: sames.map((e) => e.disabled),
              hidden: same.hidden,
            },
            listHidden: section.querySelector(".join-added-columns").hidden,
            fields: [...section.querySelectorAll(".join-added-column .join-key-input")].map((e) => [e.value, e.disabled, e.placeholder]),
            remove: [...section.querySelectorAll(".join-remove-column")].map((e) => e.disabled),
            add: [add.disabled, add.hidden],
          };
        }"""
    )


def _pick_added(page: Page, row: int, typed: str, name: str) -> None:
    """Type `typed` in a line of a column to add and pick `name` among the candidates."""
    field = page.locator("#join-under-test .join-added-column").nth(row).locator(".join-key-input")
    field.fill(typed)
    page.locator(f'#join-under-test .join-candidate[data-name="{name}"]').click()
    expect(field).to_have_value(name)


def _choose_added(page: Page) -> None:
    """Choose `足さない` for the same names, then pick `score` and add an empty line under `選んだ列だけ`."""
    page.locator("#join-under-test .join-same-names input[value=skip]").check()
    page.locator("#join-under-test .join-added input[value=picked]").check()
    _pick_added(page, 0, "sco", "score")
    page.locator("#join-under-test .join-add-column").click()


# The radios of the same names, in order, with their texts.
SAME_TEXTS = [["rename", "名前を変えて足す"], ["skip_equal", "中身も同じなら足さない"], ["skip", "足さない"]]
# The section as each open and read starts it, once the table is read.
DEFAULT_ADDED = {
    "hidden": False,
    "mode": ["all"],
    "radiosOff": [False, False],
    "same": {"label": "元の表と同じ名前の列：", "texts": SAME_TEXTS, "checked": ["rename"], "off": [False] * 3, "hidden": False},
    "listHidden": True,
    "fields": [["", False, "結合する表の列"]],
    "remove": [True],
    "add": [False, True],
}
# The same before the table is read: everything disabled.
UNREAD_ADDED = {
    **DEFAULT_ADDED,
    "radiosOff": [True, True],
    "same": {**DEFAULT_ADDED["same"], "off": [True] * 3},
    "fields": [["", True, "結合する表の列"]],
    "add": [True, True],
}


def test_the_columns_to_add_wait_for_the_read_and_switch_by_the_radio(dialog: Page) -> None:
    """`足す列` is disabled before `読む`, shown for both kinds; `選んだ列だけ` hides the radios of the same names and lists the lines, added and removed, never the last."""
    page = dialog
    assert _added(page) == UNREAD_ADDED
    _read(page)
    assert _added(page) == DEFAULT_ADDED
    page.locator("#join-under-test input[value=rows]").check()
    assert _added(page) == DEFAULT_ADDED
    page.locator("#join-under-test .join-added input[value=picked]").check()
    state = _added(page)
    assert (state["mode"], state["same"]["hidden"], state["listHidden"], state["add"]) == (["picked"], True, False, [False, False])
    assert _state(page)["join"] is True
    _pick_added(page, 0, "sco", "score")
    assert _state(page)["join"] is False
    page.locator("#join-under-test .join-add-column").click()
    assert page.locator("#join-under-test .join-added-column .join-key-input").nth(1).evaluate(
        "(e) => e === document.activeElement"
    )
    assert _added(page)["remove"] == [False, False]
    assert _state(page)["join"] is True
    page.locator("#join-under-test .join-remove-column").nth(1).click()
    assert _added(page)["fields"] == [["score", False, "結合する表の列"]]
    assert _added(page)["remove"] == [True]
    assert _state(page)["join"] is False
    page.locator("#join-under-test .join-added input[value=all]").check()
    state = _added(page)
    assert (state["same"]["hidden"], state["listHidden"], state["add"][1]) == (False, True, True)


def test_the_join_sends_the_columns_to_add(dialog: Page) -> None:
    """`すべての列` sends null with the radio of the same names as `same_names`; `選んだ列だけ` sends the lines in their order with `"rename"`; each open starts again."""
    page = dialog

    def join() -> dict:
        page.evaluate("window.joinDone = null")
        page.locator("#join-under-test .join-run").click()
        page.wait_for_function("window.joinDone !== null")
        return page.evaluate("window.joinBodies.at(-1)")

    page.locator("#join-under-test input[value=rows]").check()
    _read(page)
    assert join() == {"kind": "rows", "keys": [], "columns": None, "same_names": "rename"}

    page.evaluate("window.joinDialog.open()")
    assert _added(page) == UNREAD_ADDED
    page.locator("#join-under-test input[value=rows]").check()
    _read(page)
    page.locator("#join-under-test .join-same-names input[value=skip]").check()
    assert join() == {"kind": "rows", "keys": [], "columns": None, "same_names": "skip"}

    page.evaluate("window.joinDialog.open()")
    assert _added(page) == UNREAD_ADDED
    page.locator("#join-under-test input[value=rows]").check()
    _read(page)
    page.locator("#join-under-test .join-same-names input[value=skip_equal]").check()
    assert _added(page)["same"]["checked"] == ["skip_equal"]
    assert join() == {"kind": "rows", "keys": [], "columns": None, "same_names": "skip_equal"}
    assert page.evaluate("window.joinDone")[1:] == ["rows", "skip_equal"]

    page.evaluate("window.joinDialog.open()")
    assert _added(page) == UNREAD_ADDED
    page.locator("#join-under-test input[value=rows]").check()
    _read(page)
    _choose_added(page)
    _pick_added(page, 1, "label_1", "label_1")
    assert join() == {"kind": "rows", "keys": [], "columns": ["score", "label_1"], "same_names": "rename"}


def test_reading_again_or_editing_the_paths_resets_the_columns_to_add(dialog: Page) -> None:
    """`読む` again, and paths changed after the read, bring `足す列` back to its default."""
    page = dialog
    _read(page)
    _choose_added(page)
    page.locator("#join-under-test .join-read").click()
    expect(page.locator("#join-under-test .join-source-result")).to_have_text("2 ファイル・1,500 行・5 列")
    assert _added(page) == DEFAULT_ADDED

    _choose_added(page)
    page.locator("#join-under-test .join-paths").fill("c.parquet")
    expect(page.locator("#join-under-test .join-source-result")).to_have_text("")
    assert _added(page) == UNREAD_ADDED
