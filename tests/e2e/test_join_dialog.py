"""E2E: the join dialog, opened with Ctrl+J, joins another table to the input (Issue #344), all its columns or some (Issue #358), maybe but those of the same values (Issue #359), after a dry run whose rows of both tables it saves (Issue #379).

The input is `scatter_path` (2,003 rows, ``label`` unique); the table to
join is `join_paths` (conftest.py).
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import polars as pl
import pytest
from playwright.sync_api import Locator, Page, Route, expect
from polars.testing import assert_frame_equal

from tests.e2e.test_axis_format import open_dialog
from tests.e2e.test_scatter import drawn_task, place

pytestmark = pytest.mark.e2e

# The columns the join by `label` adds, in the column list's order.
ADDED = ["_joined", "color_joined", "score", "source_joined", "filename_joined"]
# 1,500 of the 2,003 rows of the input match.
JOINED_TOAST = "5 列を結合しました。元の表の 74.9% の行が結合できました。"
ONCE_TOAST = "結合は 1 回だけです。やり直すには File → New で開き直してください。"
# Records whether the page took the last Ctrl+J (its default prevented),
# after the page's listeners.
WATCH_J = """window.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key.toLowerCase() === "j") window.lastJ = event.defaultPrevented;
});"""


def join_dialog(page: Page) -> Locator:
    """Return the join dialog."""
    return page.locator("dialog#join")


def press_ctrl_j(page: Page) -> bool:
    """Press Ctrl+J and return whether the page took it (prevented the browser's)."""
    page.evaluate("window.lastJ = undefined")
    page.keyboard.press("Control+j")
    page.wait_for_function("window.lastJ !== undefined")
    return page.evaluate("window.lastJ")


def key_field(page: Page, row: int, side: int) -> Locator:
    """Return a key's field: `side` 0 for the input's column, 1 for the joined table's."""
    return join_dialog(page).locator(".join-key").nth(row).locator(".join-key-input").nth(side)


def pick(page: Page, row: int, side: int, typed: str, name: str) -> None:
    """Type `typed` in a key's field and pick `name` among the candidates."""
    field = key_field(page, row, side)
    field.fill(typed)
    join_dialog(page).locator(".join-candidate").filter(has_text=name).first.click()
    expect(field).to_have_value(name)


def pick_added(page: Page, row: int, typed: str, name: str) -> None:
    """Type `typed` in a line of `選んだ列だけ` and pick `name` among the candidates."""
    field = join_dialog(page).locator(".join-added-column").nth(row).locator(".join-key-input")
    field.fill(typed)
    join_dialog(page).locator(".join-candidate").filter(has_text=name).first.click()
    expect(field).to_have_value(name)


def read_source(page: Page, paths: list[Path], found: str = "2 ファイル・1,500 行・5 列") -> None:
    """Enter `paths` in the dialog, read them and wait for the table read, `found`."""
    dialog = join_dialog(page)
    dialog.locator(".join-paths").fill("\n".join(str(p) for p in paths))
    dialog.get_by_role("button", name="読む").click()
    expect(dialog.locator(".join-source-result")).to_have_text(found)


def check_keys(page: Page) -> None:
    """Press `確かめる`, `結合` off until then, and wait for what the dry run found."""
    dialog = join_dialog(page)
    expect(dialog.get_by_role("button", name="結合", exact=True)).to_be_disabled()
    dialog.get_by_role("button", name="確かめる").click()
    expect(dialog.locator(".join-check-line").first).to_be_visible()


def run_join(page: Page, toast: str = JOINED_TOAST) -> None:
    """Press `確かめる`, then `結合`, and wait for the dialog to close and the toast `toast`."""
    check_keys(page)
    join_dialog(page).get_by_role("button", name="結合", exact=True).click()
    expect(join_dialog(page)).not_to_be_visible()
    expect(page.locator("#toasts .toast-text").filter(has_text=toast)).to_be_visible()


def joined_marks(page: Page) -> list[list[str]]:
    """Return the listed columns with the mark of the join, and the mark's title."""
    return page.evaluate(
        """() => [...document.querySelectorAll("#columns .column")]
          .filter((item) => item.querySelector(".joined"))
          .map((item) => [item.dataset.name, item.querySelector(".joined").textContent, item.querySelector(".joined").title])"""
    )


@pytest.fixture
def join_page(app_page: Page) -> Page:
    """Return the page once its columns are listed, recording whether it takes Ctrl+J."""
    app_page.evaluate(WATCH_J)
    expect(app_page.locator("#columns .column").first).to_be_visible()
    app_page.wait_for_function("window.ddvizCanJoin()")
    return app_page


def test_ctrl_j_opens_the_dialog_but_not_from_a_field_or_a_dialog(join_page: Page) -> None:
    """Ctrl+J opens the dialog from the graph's page; in a filter's field or with the axis dialog open, the key is the browser's."""
    page = join_page
    dialog = join_dialog(page)
    page.evaluate("document.activeElement.blur()")
    assert press_ctrl_j(page) is True
    expect(dialog).to_be_visible()
    expect(dialog.locator(".join-paths")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()

    page.locator("#columns .column").filter(has=page.get_by_text("label", exact=True)).drag_to(
        page.locator("#filters")
    )
    search = page.locator(".filter-card .filter-search input")
    search.focus()
    assert press_ctrl_j(page) is False
    expect(dialog).not_to_be_visible()

    place(page, "x", "x")
    place(page, "y", "y")
    axis = open_dialog(page, "x")
    assert press_ctrl_j(page) is False
    expect(dialog).not_to_be_visible()
    page.keyboard.press("Escape")
    expect(axis).not_to_be_visible()
    page.evaluate("document.activeElement.blur()")
    assert press_ctrl_j(page) is True
    expect(dialog).to_be_visible()


def test_a_join_by_keys_lists_the_joined_columns_marked_and_they_draw(
    join_page: Page, join_paths: list[Path]
) -> None:
    """Read two files, pick a key (its same name filled), join: the toast tells the share, the columns are marked and draw."""
    page = join_page
    page.keyboard.press("Control+j")
    read_source(page, join_paths)
    pick(page, 0, 0, "lab", "label")
    expect(key_field(page, 0, 1)).to_have_value("label")
    run_join(page)

    names = page.locator("#columns .column").evaluate_all("(items) => items.map((i) => i.dataset.name)")
    assert names[-len(ADDED) :] == ADDED
    title = "結合：a.parquet and 1 more"
    expect(page.locator("#columns .column .joined")).to_have_count(len(ADDED))
    assert joined_marks(page) == [[name, "J", title] for name in ADDED]

    place(page, "score", "x")
    place(page, "y", "y")
    drawn_task(page)
    expect(page.locator("#status")).to_contain_text("行")
    expect(page.locator("#empty")).to_be_hidden()


def test_a_refused_read_or_join_tells_why_and_the_join_is_done_once(
    join_page: Page, join_paths: list[Path], tmp_path: Path
) -> None:
    """A missing path and a repeated key (by the dry run) are told in the dialog, which stays open; another key joins, and Ctrl+J then tells it is done."""
    page = join_page
    dialog = join_dialog(page)
    page.keyboard.press("Control+j")
    missing = tmp_path / "missing.parquet"
    dialog.locator(".join-paths").fill(str(missing))
    with page.expect_response("**/api/join/source") as answered:
        dialog.get_by_role("button", name="読む").click()
    detail = answered.value.json()["detail"]
    assert answered.value.status == 400
    result = dialog.locator(".join-source-result")
    expect(result).to_have_text(detail)
    expect(result).to_have_class("join-source-result join-failed")
    expect(key_field(page, 0, 0)).to_be_disabled()

    read_source(page, join_paths)
    pick(page, 0, 0, "colo", "color")
    expect(key_field(page, 0, 1)).to_have_value("color")
    with page.expect_response("**/api/join/check") as answered:
        dialog.get_by_role("button", name="確かめる").click()
    detail = answered.value.json()["detail"]
    assert answered.value.status == 400
    assert detail.startswith("結合する表でキーが重複しています：3 組")
    expect(dialog.locator(".join-error")).to_have_text(detail)
    expect(dialog).to_be_visible()
    expect(key_field(page, 0, 0)).to_be_enabled()
    expect(dialog.get_by_role("button", name="結合", exact=True)).to_be_disabled()

    pick(page, 0, 0, "lab", "label")
    pick(page, 0, 1, "lab", "label")
    run_join(page)
    expect(page.locator("#columns .column .joined")).to_have_count(len(ADDED))

    page.evaluate("document.activeElement.blur()")
    assert press_ctrl_j(page) is True
    expect(page.locator("#toasts .toast-text").filter(has_text=ONCE_TOAST)).to_be_visible()
    expect(dialog).not_to_be_visible()
    assert page.evaluate("window.ddvizCanJoin()") is False


def test_only_the_columns_picked_are_added(join_page: Page, join_paths: list[Path]) -> None:
    """`選んだ列だけ` with `score` adds `_joined` and `score` alone (Issue #358)."""
    page = join_page
    page.keyboard.press("Control+j")
    read_source(page, join_paths)
    pick(page, 0, 0, "lab", "label")
    join_dialog(page).get_by_label("選んだ列だけ").check()
    pick_added(page, 0, "sco", "score")
    run_join(page, "2 列を結合しました。元の表の 74.9% の行が結合できました。")
    assert [name for name, _, _ in joined_marks(page)] == ["_joined", "score"]


def test_columns_named_like_the_input_s_are_left_out(join_page: Page, join_paths: list[Path]) -> None:
    """`保持しない` for the same names leaves `color` out, not as `color_joined`, and the toast tells it (Issue #358, #378)."""
    page = join_page
    page.keyboard.press("Control+j")
    read_source(page, join_paths)
    pick(page, 0, 0, "lab", "label")
    join_dialog(page).get_by_label("保持しない", exact=True).check()
    run_join(
        page,
        "4 列を結合しました。元の表の 74.9% の行が結合できました。元の表と同じ名前の 1 列は保持しませんでした。",
    )
    assert [name for name, _, _ in joined_marks(page)] == ["_joined", "score", "source_joined", "filename_joined"]


def test_columns_of_the_same_values_are_left_out(join_page: Page, equal_paths: list[Path]) -> None:
    """Without touching the radios (`中身が違えば保持`), the join leaves out `color`, of the input's values, adds `facet`, of others, as `facet_joined`, and the toast tells it (Issue #359, #378)."""
    page = join_page
    page.keyboard.press("Control+j")
    read_source(page, equal_paths, "2 ファイル・1,500 行・6 列")
    pick(page, 0, 0, "lab", "label")
    run_join(
        page,
        "5 列を結合しました。元の表の 74.9% の行が結合できました。元の表と名前も中身も同じ 1 列は保持しませんでした。",
    )
    assert [name for name, _, _ in joined_marks(page)] == [
        "_joined",
        "facet_joined",
        "score",
        "source_joined",
        "filename_joined",
    ]


def _found(scatter_path: Path, join_paths: list[Path]) -> tuple[list[str], list[list[str]], pl.DataFrame]:
    """Return the lines and the table a dry run by ``label`` shows, and the rows of both tables a save holds with the keys, found apart with polars."""
    left = pl.read_parquet(scatter_path).select("label")
    right = pl.concat([pl.read_parquet(p).select("label") for p in join_paths])
    unmatched = left.join(right, on="label", how="anti")
    rows, matched = left.height, left.height - unmatched.height
    right_matched = right.height - right.join(left, on="label", how="anti").height
    lines = [
        f"元の表：{rows:,} 行のうち {matched:,} 行（{matched / rows * 100:.1f}%）が結合できます。{rows - matched:,} 行は結合できません。",
        f"結合する表：{right.height:,} 行のうち {right_matched:,} 行（{right_matched / right.height * 100:.1f}%）が元の表の行と一致します。{right.height - right_matched:,} 行は一致しません。",
        f"元の表で結合できなかったキー（{unmatched.height:,} 組。行の多い順に最大 20 組）",
    ]
    first = unmatched.group_by("label").len().sort(["len", "label"], descending=[True, False], nulls_last=True)
    table = [["label", "行数"], *([v if v is not None else "null", f"{n:,}"] for v, n in first.head(20).rows())]
    mine = left.with_row_index("index")
    theirs = right.with_row_index("index_joined").with_columns(
        filename_joined=pl.concat([pl.repeat(p.stem, pl.read_parquet(p).height, eager=True) for p in join_paths])
    )
    full = mine.join(theirs, on="label", how="full", coalesce=False, suffix="_joined")
    state = (
        pl.when(pl.col("index").is_null())
        .then(pl.lit("right_only"))
        .when(pl.col("index_joined").is_null())
        .then(pl.lit("left_only"))
        .otherwise(pl.lit("both"))
    )
    saved = full.sort(["index", "index_joined"], nulls_last=True).select(
        state.alias("_joined"), "index", "index_joined", "label", "label_joined", "filename_joined"
    )
    return lines, table, saved


def _texts(frame: pl.DataFrame) -> pl.DataFrame:
    """Return a frame as a CSV holds it, read back as texts."""
    return pl.read_csv(io.BytesIO(frame.write_csv().encode()), infer_schema=False)


def _held(page: Page, held: list[Route]) -> Route:
    """Wait until a request is held in `held` and return it."""
    for _ in range(100):
        if held:
            return held.pop(0)
        page.wait_for_timeout(50)
    raise AssertionError("no request was held")


def _save_held_over_the_dialog(page: Page) -> None:
    """Hold a save of the rows of both tables: its toast is over the dialog, on top where it is, and its cancel ends it."""
    dialog = join_dialog(page)
    held: list[Route] = []
    page.route("**/api/plot-data/join-rows", lambda route: held.append(route))
    dialog.get_by_role("button", name="Parquet").click()
    toast = page.locator("#toasts .toast-save").filter(has=page.locator(".save-badge", has_text="Parquet"))
    expect(toast.locator(".save-name")).to_have_text("Parquet を書き出しています")
    box = toast.bounding_box()
    on_top = page.evaluate(
        "([x, y]) => document.elementFromPoint(x, y)?.closest('.toast-save') !== null",
        [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
    )
    assert on_top is True
    with page.expect_request("**/api/plot-data/cancel"):
        toast.get_by_role("button", name="中止").click()
    _held(page, held).fulfill(status=409, content_type="application/json", body='{"cancelled": true}')
    expect(toast.locator(".save-status")).to_have_text("保存を中止しました")
    page.unroute("**/api/plot-data/join-rows")


def _cancel_a_held_dry_run(page: Page) -> None:
    """Hold a dry run and cancel it: the server takes the cancel, and the request held answers as one cancelled, told with the dialog open."""
    dialog = join_dialog(page)
    checks: list[Route] = []
    page.route("**/api/join/check", lambda route: checks.append(route))
    dialog.get_by_role("button", name="確かめる").click()
    expect(dialog.locator(".join-busy")).to_have_text("確かめています…")
    with page.expect_response("**/api/join/cancel") as cancelled:
        dialog.get_by_role("button", name="中止").click()
    assert cancelled.value.status == 204
    _held(page, checks).fulfill(status=409, content_type="application/json", body='{"detail": "cancelled"}')
    expect(dialog.locator(".join-error")).to_have_text("中止しました。")
    expect(dialog).to_be_visible()
    expect(dialog.locator(".join-check-result")).to_be_hidden()
    page.unroute("**/api/join/check")


def test_a_dry_run_tells_what_matches_saves_the_rows_and_is_cancelled_before_the_join(
    join_page: Page, scatter_path: Path, join_paths: list[Path]
) -> None:
    """`確かめる` tells the rows of both tables that match and the keys that do not; the rows of both tables save as a CSV, the save's toast pressable over the dialog; a dry run cancelled tells it with the dialog open, and another one joins."""
    page = join_page
    dialog = join_dialog(page)
    lines, table, saved = _found(scatter_path, join_paths)
    page.keyboard.press("Control+j")
    read_source(page, join_paths)
    pick(page, 0, 0, "lab", "label")
    check_keys(page)
    expect(dialog.locator(".join-check-line")).to_have_text(lines[:2])
    expect(dialog.locator(".join-unmatched-heading")).to_have_text(lines[2:])
    cells = dialog.locator(".join-unmatched table").evaluate(
        "(t) => [...t.rows].map((r) => [...r.cells].map((c) => c.textContent))"
    )
    assert cells == table

    # The rows of both tables, by the keys, as a CSV.
    with page.expect_download() as downloaded:
        dialog.get_by_role("button", name="CSV").click()
    assert re.fullmatch(r"scatter_join_rows_\d{8}-\d{6}\.csv", downloaded.value.suggested_filename)
    content = Path(downloaded.value.path()).read_bytes()
    found = pl.read_csv(io.BytesIO(content.removeprefix("﻿".encode())), infer_schema=False)
    assert found.columns == ["_joined", "index", "index_joined", "label", "label_joined", "source_joined", "filename_joined"]
    assert_frame_equal(found.drop("source_joined"), _texts(saved))

    _save_held_over_the_dialog(page)
    _cancel_a_held_dry_run(page)
    run_join(page)
    expect(page.locator("#columns .column .joined")).to_have_count(len(ADDED))
