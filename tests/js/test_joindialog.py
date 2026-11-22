"""JS: joindialog.js, the join dialog's parts: the pairs of keys, `結合` enabled, the column of the same name (Issue #344), the columns to add (Issue #358), the dry run, the cancel of a wait and the save of the rows of both tables (Issue #379)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.js

# Opens the dialog, with the page's stylesheet, on a stub of the server: the
# input has `label`, `color` and `x`, the table to join `label_1`, `label_2`,
# `label`, `score` and `color`. The searches list 2 columns at most, the one
# named `exact` first, as the server does; a read waits for
# `window.readGate` when set; `/api/join` answers 400 for the key `color`;
# `/api/join/check` answers `CHECKED`; both record each body and, after
# `window.holdNext = <path>`, wait for `window.release(status, body)`.
# `/api/join/cancel` counts its calls, and fails while `window.cancelFails`.
# The saves (`saves.js`) record each start, held after `window.holdSave`
# until `window.saveDone()`.
# What the stub's dry run answers: 2 sets of the input's keys match none, none of the joined table's.
CHECKED = {
    "rows": 2000,
    "matched": 1500,
    "right_rows": 1500,
    "right_matched": 1200,
    "left_unmatched": {"sets": 2, "top": [{"values": ["B"], "rows": 400}, {"values": [None], "rows": 100}]},
    "right_unmatched": {"sets": 0, "top": []},
}
OPEN = """async () => {
  const { JoinDialog } = await import("/static/js/joindialog.js");
  const CHECKED = __CHECKED__;
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
    if (path === "/api/join/cancel") {
      window.cancels++;
      if (window.cancelFails) throw new TypeError("Failed to fetch");
      return new Response(null, { status: 204 });
    }
    const body = JSON.parse(init.body);
    if (path === "/api/join/source") {
      window.reads.push(body);
      if (window.readGate) await window.readGate;
      return answer({ paths: body.paths, files: 2, rows: 1500, columns: 5, casts: [] });
    }
    (path === "/api/join/check" ? window.checkBodies : window.joinBodies).push(body);
    if (window.holdNext === path) {
      window.holdNext = null;
      const [status, held] = await new Promise((resolve) => { window.release = (...given) => resolve(given); });
      if (status !== 200) return answer(held, status);
    }
    if (path === "/api/join/check") return answer(window.checked);
    if (body.keys.some((key) => key.left === "color")) return answer({ detail: "結合する表でキーが重複しています" }, 400);
    return answer({ added: ["_joined", "score"], rows: 2000, matched: 1500 });
  };
  window.checkBodies = [];
  window.cancels = 0;
  window.cancelFails = false;
  window.holdNext = null;
  window.checked = CHECKED;
  window.answered = 0;
  window.saveStarts = [];
  window.holdSave = false;
  const saves = {
    running: false,
    async start(format, request) {
      window.saveStarts.push([format, request]);
      if (window.holdSave) await new Promise((resolve) => { window.saveDone = resolve; });
    },
  };
  const style = document.createElement("link");
  Object.assign(style, { rel: "stylesheet", href: "/static/app.css", id: "join-style" });
  await new Promise((resolve) => { style.onload = resolve; document.head.append(style); });
  const dialog = document.createElement("dialog");
  dialog.id = "join-under-test";
  document.body.append(dialog);
  window.joinDone = null;
  const join = new JoinDialog(dialog, {
    joined: (answer, kind, sameNames) => { window.joinDone = [answer, kind, sameNames]; },
    answered: () => { window.answered++; },
    saves,
  });
  window.joinDialog = join;
  join.open();
}""".replace("__CHECKED__", json.dumps(CHECKED))


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


def _check(page: Page) -> None:
    """Press `確かめる` and wait for what the dry run found."""
    page.locator("#join-under-test .join-check-run").click()
    expect(page.locator("#join-under-test .join-check-line").first).to_be_visible()


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
            check: dialog.querySelector(".join-check-run").disabled,
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
            columnsPicked: m.joinedText({ added: ["a"], rows: 10, matched: 10, skipped: [] }, "rows", null),
            comparing: [
              m.comparingText({ type: "progress", stage: "compare", done: 0, total: 10, column: "temp" }),
              m.comparingText({ type: "progress", stage: "compare", done: 1199, total: 1200, column: "lot id" }),
            ],
            picked: [
              m.joinReady(true, "rows", [], []),
              m.joinReady(true, "rows", [], ["a", null]),
              m.joinReady(true, "rows", [], ["a", "b"]),
              m.joinReady(true, "key", [{ left: "a", right: "a" }], [null]),
              m.joinReady(true, "key", [{ left: "a", right: "a" }], ["b"], true),
              m.joinReady(true, "key", [{ left: "a", right: null }], ["b"], true),
              m.joinReady(false, "rows", [], ["b"]),
            ],
            ready: [
              m.joinReady(false, "rows", []),
              m.joinReady(true, "rows", [{ left: null, right: null }]),
              m.joinReady(true, "key", [{ left: "a", right: "a" }], null, true),
              m.joinReady(true, "key", [{ left: "a", right: "a" }, { left: "b", right: null }], null, true),
              m.joinReady(true, "key", [], null, true),
            ],
            // By keys, only after a dry run of them; by rows, without one.
            checked: [
              m.joinReady(true, "key", [{ left: "a", right: "a" }]),
              m.joinReady(true, "key", [{ left: "a", right: "a" }], null, false),
              m.joinReady(false, "key", [{ left: "a", right: "a" }], null, true),
              m.joinReady(true, "rows", [], null, false),
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
        "skippedByKey": "3 列を結合しました。元の表の 74.9% の行が結合できました。元の表と同じ名前の 2 列は保持しませんでした。",
        "skippedByRows": "1 列を結合しました。元の表と同じ名前の 1,200 列は保持しませんでした。",
        "noneSkipped": "1 列を結合しました。",
        "equalByKey": "2 列を結合しました。元の表の 50.0% の行が結合できました。元の表と名前も中身も同じ 1 列は保持しませんでした。",
        "equalByRows": "1 列を結合しました。元の表と名前も中身も同じ 1,200 列は保持しませんでした。",
        "noneEqual": "1 列を結合しました。",
        "columnsPicked": "1 列を結合しました。",
        "comparing": [
            "同じ名前の列を比べています（1 / 10）：temp",
            "同じ名前の列を比べています（1200 / 1200）：lot id",
        ],
        "picked": [False, False, True, False, True, False, False],
        "ready": [False, True, True, False, False],
        "checked": [False, False, False, True],
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
        "check": True,
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


def test_picking_a_column_fills_the_same_name_and_enables_the_dry_run(dialog: Page) -> None:
    """A column picked on the left fills the joined table's empty field of the same name; typed text is not taken; `結合` waits for a dry run."""
    page = dialog
    _read(page)
    _pick(page, 0, 0, "lab", "label")
    right = page.locator("#join-under-test .join-key-input").nth(1)
    expect(right).to_have_value("label")
    assert _state(page)["fields"] == [["label", False, True], ["label", False, True]]
    assert _state(page)["check"] is False
    assert _state(page)["join"] is True

    # Text typed is not a column until one is picked.
    right.fill("sco")
    assert _state(page)["check"] is True
    page.locator("#join-under-test .join-candidate").filter(has_text="score").click()
    assert _state(page)["fields"][1] == ["score", False, True]
    assert _state(page)["check"] is False

    # No column of the same name, or a field already given: nothing is put.
    page.locator("#join-under-test .join-add-key").click()
    _pick(page, 1, 0, "x", "x")
    page.wait_for_timeout(200)
    assert _state(page)["fields"][2:] == [["x", False, True], ["", False, False]]
    assert _state(page)["check"] is True
    _pick(page, 1, 1, "col", "color")
    _pick(page, 1, 0, "lab", "label")
    page.wait_for_timeout(200)
    assert _state(page)["fields"][2:] == [["label", False, True], ["color", False, True]]
    assert _state(page)["check"] is False


def test_the_kind_by_rows_hides_the_keys(dialog: Page) -> None:
    """`行の順で並べる` hides the keys and may join once a table is read; the keys come back as they were."""
    page = dialog
    page.locator("#join-under-test .join-kinds input[value=rows]").check()
    assert _state(page)["keysHidden"] is True
    assert _state(page)["join"] is True
    _read(page)
    assert _state(page)["join"] is False
    page.locator("#join-under-test .join-kinds input[value=key]").check()
    assert _state(page)["keysHidden"] is False
    assert _state(page)["join"] is True


def test_a_refused_join_tells_why_and_a_new_key_joins(dialog: Page) -> None:
    """A refused join shows the server's reason with the dialog open and the fields back; another key joins and closes it."""
    page = dialog
    _read(page)
    _pick(page, 0, 0, "col", "color")
    _check(page)
    page.locator("#join-under-test .join-run").click()
    expect(page.locator("#join-under-test .join-error")).to_have_text("結合する表でキーが重複しています")
    assert page.evaluate("document.getElementById('join-under-test').open")
    assert _state(page)["join"] is False
    _pick(page, 0, 0, "lab", "label")
    _pick(page, 0, 1, "label", "label")
    assert _state(page)["join"] is True
    _check(page)
    page.locator("#join-under-test .join-run").click()
    page.wait_for_function("window.joinDone !== null")
    assert page.evaluate("document.getElementById('join-under-test').open") is False
    assert page.evaluate("window.joinBodies") == [
        {"kind": "key", "keys": [{"left": "color", "right": "color"}], "columns": None, "same_names": "skip_equal"},
        {"kind": "key", "keys": [{"left": "label", "right": "label"}], "columns": None, "same_names": "skip_equal"},
    ]
    assert page.evaluate("window.joinDone") == [
        {"added": ["_joined", "score"], "rows": 2000, "matched": 1500},
        "key",
        "skip_equal",
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
    _check(page)
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
        "check": True,
        "keysHidden": False,
    }
    page.locator("#join-under-test .join-read").click()
    expect(result).to_have_text("2 ファイル・1,500 行・5 列")
    _pick(page, 0, 0, "label", "label")
    _check(page)
    expect(page.locator("#join-under-test .join-run")).to_be_enabled()

    page.locator("#join-under-test .join-recursive").check()
    expect(result).to_have_text("")
    assert _state(page)["join"] is True
    page.locator("#join-under-test .join-kinds input[value=rows]").check()
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
    page.locator("#join-under-test .join-kinds input[value=rows]").check()
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
    """Return the section `保持する列`: its heading, the radios of the mode and of the same names (checked, disabled, the label and the texts of the latter), what is hidden, and the lines of the columns."""
    return page.evaluate(
        """() => {
          const section = document.querySelector("#join-under-test .join-added");
          const radios = [...section.querySelectorAll(".join-added-mode input")];
          const same = section.querySelector(".join-same-names");
          const sames = [...same.querySelectorAll("input[type=radio]")];
          const add = section.querySelector(".join-add-column");
          return {
            heading: section.querySelector("h3").textContent,
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
    """Choose `保持しない` for the same names, then pick `score` and add an empty line under `選んだ列だけ`."""
    page.locator("#join-under-test .join-same-names input[value=skip]").check()
    page.locator("#join-under-test .join-added input[value=picked]").check()
    _pick_added(page, 0, "sco", "score")
    page.locator("#join-under-test .join-add-column").click()


# The radios of the same names, in order, with their texts.
SAME_TEXTS = [["skip_equal", "中身が違えば保持"], ["skip", "保持しない"]]
# The section as each open and read starts it, once the table is read.
DEFAULT_ADDED = {
    "heading": "保持する列",
    "hidden": False,
    "mode": ["all"],
    "radiosOff": [False, False],
    "same": {"label": "元の表と同じ名前の列：", "texts": SAME_TEXTS, "checked": ["skip_equal"], "off": [False] * 2, "hidden": False},
    "listHidden": True,
    "fields": [["", False, "結合する表の列"]],
    "remove": [True],
    "add": [False, True],
}
# The same before the table is read: everything disabled.
UNREAD_ADDED = {
    **DEFAULT_ADDED,
    "radiosOff": [True, True],
    "same": {**DEFAULT_ADDED["same"], "off": [True] * 2},
    "fields": [["", True, "結合する表の列"]],
    "add": [True, True],
}


def test_the_columns_to_add_wait_for_the_read_and_switch_by_the_radio(dialog: Page) -> None:
    """`保持する列` is disabled before `読む`, shown for both kinds; `選んだ列だけ` hides the radios of the same names and lists the lines, added and removed, never the last."""
    page = dialog
    assert _added(page) == UNREAD_ADDED
    _read(page)
    assert _added(page) == DEFAULT_ADDED
    page.locator("#join-under-test .join-kinds input[value=rows]").check()
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
    """`すべての列` sends null with the radio of the same names as `same_names`; `選んだ列だけ` sends the lines in their order with null; each open starts again."""
    page = dialog

    def join() -> dict:
        page.evaluate("window.joinDone = null")
        page.locator("#join-under-test .join-run").click()
        page.wait_for_function("window.joinDone !== null")
        return page.evaluate("window.joinBodies.at(-1)")

    page.locator("#join-under-test .join-kinds input[value=rows]").check()
    _read(page)
    assert join() == {"kind": "rows", "keys": [], "columns": None, "same_names": "skip_equal"}

    page.evaluate("window.joinDialog.open()")
    assert _added(page) == UNREAD_ADDED
    page.locator("#join-under-test .join-kinds input[value=rows]").check()
    _read(page)
    page.locator("#join-under-test .join-same-names input[value=skip]").check()
    assert join() == {"kind": "rows", "keys": [], "columns": None, "same_names": "skip"}

    page.evaluate("window.joinDialog.open()")
    assert _added(page) == UNREAD_ADDED
    page.locator("#join-under-test .join-kinds input[value=rows]").check()
    _read(page)
    page.locator("#join-under-test .join-same-names input[value=skip]").check()
    page.locator("#join-under-test .join-same-names input[value=skip_equal]").check()
    assert _added(page)["same"]["checked"] == ["skip_equal"]
    assert join() == {"kind": "rows", "keys": [], "columns": None, "same_names": "skip_equal"}
    assert page.evaluate("window.joinDone")[1:] == ["rows", "skip_equal"]

    page.evaluate("window.joinDialog.open()")
    assert _added(page) == UNREAD_ADDED
    page.locator("#join-under-test .join-kinds input[value=rows]").check()
    _read(page)
    _choose_added(page)
    _pick_added(page, 1, "label_1", "label_1")
    assert join() == {"kind": "rows", "keys": [], "columns": ["score", "label_1"], "same_names": None}


def test_reading_again_or_editing_the_paths_resets_the_columns_to_add(dialog: Page) -> None:
    """`読む` again, and paths changed after the read, bring `保持する列` back to its default."""
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


def test_the_texts_of_a_dry_run(js_page: Page) -> None:
    """The two lines with thousands separators and one decimal, none for no rows; the headings and cells of the tables of the keys matching none."""
    result = js_page.evaluate(
        """async () => {
          const m = await import("/static/js/joindialog.js");
          const answer = { rows: 1000, matched: 749, right_rows: 1500000, right_matched: 1200000 };
          return {
            lines: m.checkText(answer),
            empty: m.checkText({ rows: 0, matched: 0, right_rows: 0, right_matched: 0 }),
            headings: [m.unmatchedHeading("left", 37), m.unmatchedHeading("right", 1234)],
            cells: m.unmatchedRows({ sets: 2, top: [{ values: ["B", null], rows: 1200 }, { values: [null, "x"], rows: 31 }] }),
            cancelled: [
              m.wasCancelled({ status: 409, text: JSON.stringify({ detail: "cancelled" }) }),
              m.wasCancelled({ status: 409, text: JSON.stringify({ detail: "already joined" }) }),
              m.wasCancelled({ status: 500, text: JSON.stringify({ detail: "cancelled" }) }),
              m.wasCancelled({ status: 409, text: "no json" }),
            ],
          };
        }"""
    )
    assert result == {
        "lines": [
            "元の表：1,000 行のうち 749 行（74.9%）が結合できます。251 行は結合できません。",
            "結合する表：1,500,000 行のうち 1,200,000 行（80.0%）が元の表の行と一致します。300,000 行は一致しません。",
        ],
        "empty": [
            "元の表：0 行のうち 0 行が結合できます。0 行は結合できません。",
            "結合する表：0 行のうち 0 行が元の表の行と一致します。0 行は一致しません。",
        ],
        "headings": [
            "元の表で結合できなかったキー（37 組。行の多い順に最大 20 組）",
            "結合する表で一致しなかったキー（1,234 組。行の多い順に最大 20 組）",
        ],
        "cells": [["B", "null", "1,200"], ["null", "x", "31"]],
        "cancelled": [True, False, False, False],
    }


def _check_state(page: Page) -> dict:
    """Return what the dry run shows: its lines, the headings and cells of its tables, whether it is hidden, and whether `確かめる`, `結合` and the save's radios and buttons are disabled."""
    return page.evaluate(
        """() => {
          const dialog = document.getElementById("join-under-test");
          const result = dialog.querySelector(".join-check-result");
          const save = dialog.querySelector(".join-rows-save");
          return {
            hidden: result.hidden,
            lines: [...result.querySelectorAll(".join-check-line")].map((e) => e.textContent),
            headings: [...result.querySelectorAll(".join-unmatched-heading")].map((e) => e.textContent),
            tables: [...result.querySelectorAll(".join-unmatched table")].map((t) =>
              [...t.rows].map((r) => [...r.cells].map((c) => c.textContent))),
            check: dialog.querySelector(".join-check-run").disabled,
            join: dialog.querySelector(".join-run").disabled,
            save: [...save.querySelectorAll("input, button")].map((e) => e.disabled),
          };
        }"""
    )


SHOWN = {
    "hidden": False,
    "lines": [
        "元の表：2,000 行のうち 1,500 行（75.0%）が結合できます。500 行は結合できません。",
        "結合する表：1,500 行のうち 1,200 行（80.0%）が元の表の行と一致します。300 行は一致しません。",
    ],
    "headings": ["元の表で結合できなかったキー（2 組。行の多い順に最大 20 組）"],
    "tables": [[["label", "行数"], ["B", "400"], ["null", "100"]]],
    "check": False,
    "join": False,
    "save": [False] * 4,
}
# Nothing found: `結合` and the save off, `確かめる` on.
DROPPED = {**SHOWN, "hidden": True, "lines": [], "headings": [], "tables": [], "join": True, "save": [True] * 4}


def _checked(page: Page) -> None:
    """Read the table, pick the key `label` on both sides and run the dry run."""
    _read(page)
    _pick(page, 0, 0, "label", "label")
    _check(page)


def test_a_dry_run_shows_what_it_found_and_lets_it_join_and_save(dialog: Page) -> None:
    """`確かめる` waits for every key; its answer shows the two lines and the input's table (the joined table's has no set), and enables `結合` and the save."""
    page = dialog
    state = _check_state(page)
    assert (state["hidden"], state["check"], state["join"], state["save"]) == (True, True, True, [True] * 4)
    _read(page)
    assert _check_state(page)["check"] is True
    _checked(page)
    assert _check_state(page) == SHOWN
    assert page.evaluate("window.checkBodies") == [{"keys": [{"left": "label", "right": "label"}]}]
    assert page.evaluate("window.answered") == 1
    page.evaluate(
        """() => { window.checked = { ...window.checked, right_unmatched: { sets: 21, top: [{ values: ["C"], rows: 1 }] } }; }"""
    )
    _check(page)
    state = _check_state(page)
    assert state["headings"][1] == "結合する表で一致しなかったキー（21 組。行の多い順に最大 20 組）"
    assert state["tables"][1] == [["label", "行数"], ["C", "1"]]


@pytest.mark.parametrize(
    "edit",
    ["left", "right", "add", "remove", "kind", "read", "paths", "reopen"],
)
def test_changing_the_keys_or_the_table_drops_the_dry_run(dialog: Page, edit: str) -> None:
    """A field of the keys typed in or picked, a pair added or removed, the kind switched, the table read again or its paths changed, and the dialog opened again drop what the dry run found."""
    page = dialog
    _checked(page)
    if edit == "remove":
        page.locator("#join-under-test .join-add-key").click()
        _pick(page, 1, 0, "x", "x")
        _pick(page, 1, 1, "sco", "score")
        _check(page)
        page.locator("#join-under-test .join-remove-key").nth(1).click()
    elif edit == "left":
        page.locator("#join-under-test .join-key-input").nth(0).fill("labe")
    elif edit == "right":
        _pick(page, 0, 1, "sco", "score")
    elif edit == "add":
        page.locator("#join-under-test .join-add-key").click()
    elif edit == "kind":
        page.locator("#join-under-test .join-kinds input[value=rows]").check()
        page.locator("#join-under-test .join-kinds input[value=key]").check()
    elif edit == "read":
        page.locator("#join-under-test .join-read").click()
        expect(page.locator("#join-under-test .join-source-result")).to_have_text("2 ファイル・1,500 行・5 列")
    elif edit == "paths":
        page.locator("#join-under-test .join-paths").fill("c.parquet")
    else:
        page.evaluate("window.joinDialog.open()")
    state = _check_state(page)
    assert {k: state[k] for k in ("hidden", "lines", "tables", "join", "save")} == {
        k: DROPPED[k] for k in ("hidden", "lines", "tables", "join", "save")
    }


def test_the_columns_to_keep_leave_the_dry_run(dialog: Page) -> None:
    """The columns to keep are not part of the dry run: changing them keeps what it found."""
    page = dialog
    _checked(page)
    _choose_added(page)
    _pick_added(page, 1, "label_1", "label_1")
    assert _check_state(page) == SHOWN
    page.locator("#join-under-test .join-run").click()
    page.wait_for_function("window.joinDone !== null")
    assert page.evaluate("window.joinBodies") == [
        {"kind": "key", "keys": [{"left": "label", "right": "label"}], "columns": ["score", "label_1"], "same_names": None}
    ]


def _wait_state(page: Page) -> dict:
    """Return the wait at the bottom: its text, whether `中止` is hidden and disabled, whether `キャンセル` is disabled, and the field of the error with whether it is a notice."""
    return page.evaluate(
        """() => {
          const dialog = document.getElementById("join-under-test");
          const busy = dialog.querySelector(".join-busy");
          const abort = dialog.querySelector(".join-abort");
          const error = dialog.querySelector(".join-error");
          return {
            text: busy.hidden ? null : busy.textContent,
            abort: [abort.hidden, abort.disabled],
            cancel: dialog.querySelector(".join-cancel").disabled,
            error: [error.textContent, error.classList.contains("join-notice")],
            open: dialog.open,
          };
        }"""
    )


IDLE = {"text": None, "abort": [True, False], "cancel": False, "error": ["", False], "open": True}
# Where each wait posts and what starts it.
WAITS = {"check": ("/api/join/check", "join-check-run"), "join": ("/api/join", "join-run")}


def _hold(page: Page, kind: str) -> None:
    """Hold the next request of the wait `kind` (`WAITS`) and start it."""
    path, press = WAITS[kind]
    page.evaluate(f"window.holdNext = {json.dumps(path)}")
    page.locator(f"#join-under-test .{press}").click()
    page.wait_for_function("window.holdNext === null")


def _release(page: Page, status: int, body: dict | None = None) -> None:
    """Answer the request held with `status` and `body`."""
    page.evaluate(f"window.release({status}, {json.dumps(body)})")


def _abort(page: Page, cancels: int) -> None:
    """Press `中止` and wait for its `cancels`-th cancel to be sent."""
    page.locator("#join-under-test .join-abort").click()
    page.wait_for_function(f"window.cancels === {cancels}")


@pytest.mark.parametrize("kind", list(WAITS))
def test_a_wait_is_cancelled_and_the_dialog_stays(dialog: Page, kind: str) -> None:
    """While a dry run or a join waits, `中止` sends the cancel and waits for its answer: a cancelled one brings the fields back, told plainly, the dialog open; キャンセル and Esc do nothing meanwhile.

    A cancelled dry run leaves none, `結合` off; a cancelled join leaves the dry run before, `結合` on.
    """
    page = dialog
    _checked(page)
    assert _wait_state(page) == IDLE
    _hold(page, kind)
    text = "確かめています…" if kind == "check" else "結合しています…"
    assert _wait_state(page) == {**IDLE, "text": text, "abort": [False, False], "cancel": True}
    assert _check_state(page)["join"] is True
    page.keyboard.press("Escape")
    page.locator("#join-under-test .join-cancel").click(force=True)
    assert _wait_state(page)["open"] is True
    _abort(page, 1)
    assert _wait_state(page) == {**IDLE, "text": "中止しています…", "abort": [False, True], "cancel": True}
    _release(page, 409, {"detail": "cancelled"})
    expect(page.locator("#join-under-test .join-error")).to_have_text("中止しました。")
    assert _wait_state(page) == {**IDLE, "error": ["中止しました。", True]}
    state = _check_state(page)
    if kind == "check":
        assert {k: state[k] for k in ("hidden", "join", "save")} == {"hidden": True, "join": True, "save": [True] * 4}
    else:
        assert state == SHOWN
    assert page.evaluate("window.joinDone") is None
    assert page.evaluate("window.answered") == 2


@pytest.mark.parametrize("kind", list(WAITS))
def test_a_wait_cancelled_too_late_ends_as_it_answers(dialog: Page, kind: str) -> None:
    """A dry run or a join that answers done after `中止` was sent is taken as done: the dry run shows, the join closes the dialog."""
    page = dialog
    _checked(page)
    _hold(page, kind)
    _abort(page, 1)
    _release(page, 200)
    if kind == "check":
        expect(page.locator("#join-under-test .join-check-line").first).to_be_visible()
        assert _check_state(page) == SHOWN
        assert _wait_state(page) == IDLE
    else:
        page.wait_for_function("window.joinDone !== null")
        assert _wait_state(page)["open"] is False


def test_a_cancel_the_server_did_not_take_may_be_sent_again(dialog: Page) -> None:
    """A cancel that does not reach the server gives `中止` back; a refused wait then shows its reason in red."""
    page = dialog
    _checked(page)
    page.evaluate("window.cancelFails = true")
    _hold(page, "check")
    _abort(page, 1)
    expect(page.locator("#join-under-test .join-abort")).to_be_enabled()
    assert _wait_state(page)["text"] == "確かめています…"
    page.evaluate("window.cancelFails = false")
    _abort(page, 2)
    _release(page, 500, {"detail": "メモリが足りません"})
    expect(page.locator("#join-under-test .join-error")).to_have_text("メモリが足りません")
    assert _wait_state(page)["error"] == ["メモリが足りません", False]
    assert _check_state(page)["hidden"] is True


def test_the_rows_of_both_tables_are_saved_from_the_dialog(dialog: Page) -> None:
    """The save sends the columns of the radio to the save of the plot's data; `確かめる`, `結合` and the save wait until it is written; each open starts at `Key columns`."""
    page = dialog
    _checked(page)
    radios = page.locator("#join-under-test .join-rows-save input")
    texts = "(rs) => rs.map((r) => [r.value, r.checked, r.closest(`label`).textContent.trim()])"
    assert radios.evaluate_all(texts) == [["key", True, "Key columns"], ["all", False, "All columns"]]
    assert page.locator("#join-under-test .join-rows-label").inner_text() == "行の一覧を保存："
    page.evaluate("window.holdSave = true")
    page.locator("#join-under-test .join-rows-save-csv").click()
    page.wait_for_function("window.saveStarts.length === 1")
    state = _check_state(page)
    assert (state["check"], state["join"], state["save"]) == (True, True, [True] * 4)
    page.evaluate("window.saveDone()")
    expect(page.locator("#join-under-test .join-run")).to_be_enabled()
    assert _check_state(page) == SHOWN
    page.evaluate("window.holdSave = false")
    page.locator("#join-under-test .join-rows-save input[value=all]").check()
    page.locator("#join-under-test .join-rows-save-parquet").click()
    page.wait_for_function("window.saveStarts.length === 2")
    url = "/api/plot-data/join-rows"
    assert page.evaluate("window.saveStarts") == [
        ["csv", {"url": url, "fields": {"columns": "key"}}],
        ["parquet", {"url": url, "fields": {"columns": "all"}}],
    ]
    page.evaluate("window.joinDialog.open()")
    assert radios.evaluate_all("(rs) => rs.map((r) => r.checked)") == [True, False]
