"""E2E: the filter card that searches the candidates of a column of 1,500 levels and ticks them (Issue #122)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_color_levels import api_requests, card
from tests.e2e.test_scatter import SETTLED, drop_on_filters, place

pytestmark = pytest.mark.e2e

# Rows of the levels the search for ABC finds; every other level has 2.
ABC_ROWS = {"ABC": 5, "abc": 7, "ABC-123": 9}
LEVELS = 1500


@pytest.fixture
def scatter_frame() -> pl.DataFrame:
    """Return x, y and a label of 1,500 levels: ABC, abc, ABC-123 and L1 to L1497."""
    labels = [v for v, n in ABC_ROWS.items() for _ in range(n)]
    labels += [f"L{i}" for i in range(1, LEVELS - len(ABC_ROWS) + 1) for _ in range(2)]
    rng = np.random.default_rng(0)
    return pl.DataFrame(
        {
            "x": rng.normal(0, 1, len(labels)),
            "y": rng.normal(0, 1, len(labels)),
            "label": labels,
        }
    )


@pytest.fixture
def scatter_path(tmp_path: Path, scatter_frame: pl.DataFrame) -> Path:
    """Write `scatter_frame`."""
    path = tmp_path / "labels.parquet"
    scatter_frame.write_parquet(path)
    return path


def _listed(page: Page) -> list[str]:
    """Return the candidates the label card lists."""
    rows = card(page, "label").locator(".filter-card-body > .filter-levels .filter-level-name")
    return rows.all_inner_texts()


def _box(page: Page, level: str, where: str = ".filter-card-body > .filter-levels") -> object:
    """Return the check box of a level the label card shows in `where`."""
    return (
        card(page, "label")
        .locator(f"{where} .filter-level")
        .filter(has=page.get_by_text(level, exact=True))
        .locator("input")
    )


def test_the_candidates_are_searched_ticked_and_kept(app_page: Page) -> None:
    """A blank search lists the first 100; ABC ticked alone keeps its rows (not abc or ABC-123); Count and another search keep the tick, fetch only the candidates and aggregate nothing."""
    page = app_page
    columns = page.locator("#columns .column")
    expect(columns.filter(has_text="label")).to_be_visible()
    place(page, "x", "x")
    place(page, "y", "y")
    drop_on_filters(page, columns.filter(has=page.get_by_text("label", exact=True)), 1)
    label = card(page, "label")
    expect(label.locator(".filter-truncated")).to_have_text(
        "先頭100件を表示しています。検索語を絞ってください"
    )
    expect(label.locator(".filter-card-body > .filter-levels .filter-level")).to_have_count(100)
    expect(label.locator(".filter-mode [aria-pressed=true]")).to_have_text("水準を選択")
    aggregating = api_requests(page)
    status = page.locator("#status")

    # The button searches.
    search = label.locator(".filter-search input")
    search.fill("abc")
    with page.expect_response("**/api/filter-levels?*") as answered:
        label.locator(".filter-search-go").click()
    assert answered.value.ok
    expect(label.locator(".filter-truncated")).to_be_hidden()
    assert _listed(page) == ["ABC", "abc", "ABC-123"]

    with page.expect_response("**/api/overview") as drawn:
        _box(page, "ABC").check()
    assert drawn.value.ok
    page.wait_for_function(SETTLED)
    expect(status).to_have_text(f"{ABC_ROWS['ABC']} 行（フィルタ後）")
    expect(page.locator(".filter-summary")).to_have_text(f"（1）label: 1/{LEVELS}")
    assert aggregating == ["overview"]

    # Count orders the candidates of the same search again.
    with page.expect_response("**/api/filter-levels?*") as answered:
        label.locator(".filter-card-sort").click()
        page.locator('.filter-sort-menu [data-order="count"]').click()
    assert "order=count" in answered.value.url
    expect(label.locator(".filter-card-body > .filter-levels .filter-level-name").first).to_have_text("ABC-123")
    assert _listed(page) == ["ABC-123", "abc", "ABC"]
    expect(_box(page, "ABC")).to_be_checked()

    # The Enter of an IME conversion does not search; Enter does.
    search.fill("L1")
    searched: list[str] = []
    page.on("request", lambda r: searched.append(r.url) if "filter-levels" in r.url else None)
    search.evaluate(
        """(box) => box.dispatchEvent(new KeyboardEvent("keydown", {
          key: "Enter", keyCode: 229, isComposing: true, bubbles: true,
        }))"""
    )
    page.evaluate("() => new Promise((r) => setTimeout(r, 300))")
    assert searched == []
    with page.expect_response("**/api/filter-levels?*") as answered:
        search.press("Enter")
    assert "q=L1" in answered.value.url
    expect(label.locator(".filter-card-body > .filter-levels .filter-level").first).to_be_visible()
    assert "ABC" not in _listed(page)
    # ABC, ticked, is shown apart.
    expect(_box(page, "ABC", ".filter-picked")).to_be_checked()
    page.evaluate("() => new Promise((r) => setTimeout(r, 600))")
    expect(status).to_have_text(f"{ABC_ROWS['ABC']} 行（フィルタ後）")
    assert aggregating == ["overview"]
