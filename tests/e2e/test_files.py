"""E2E: several Parquet files open as one table, in natural order."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest
import uvicorn
from playwright.sync_api import Page, expect

from ddviz.server.app import create_app
from ddviz.server.settings import Settings
from tests.e2e.conftest import TOKEN
from tests.e2e.test_scatter import PAINTED_PIXEL, place

pytestmark = pytest.mark.e2e


@pytest.fixture
def app_url(tmp_path: Path, folder_path: Path) -> Iterator[str]:
    """Serve the files of `folder_path`, given out of order, as one input."""
    root = tmp_path / "run"
    root.mkdir()
    files = [
        folder_path / n for n in ("part-10.parquet", "part-2.parquet", "part-1.parquet")
    ]
    app = create_app(
        [str(f) for f in files], False, root, tmp_path / "cache", Settings(), TOKEN
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("the UI server did not start")
        thread.join(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(30)


def test_several_files_load_draw_and_hover_as_one_table(
    app_page: Page, folder_frame: pl.DataFrame
) -> None:
    """The cast column is told, the points draw, and a hovered row's number is in natural order."""
    page = app_page
    casts = page.locator("#casts")
    expect(casts).to_be_visible()
    expect(casts.locator(".casts-text")).to_contain_text("3 個のファイル")
    expect(casts.locator("tbody tr")).to_have_count(1)
    casts.get_by_role("button", name="OK").click()
    expect(casts).to_be_hidden()

    place(page, "x", "x", plots=False)
    place(page, "y", "y")
    pixel = page.wait_for_function(PAINTED_PIXEL).json_value()
    page.mouse.move(pixel["x"], pixel["y"])
    label = page.locator("#hover-label")
    expect(label).to_contain_text("行番号: ")
    lines = dict(line.split(": ", 1) for line in label.inner_text().splitlines())
    row = folder_frame.row(int(lines["行番号"]), named=True)
    for column in ["x", "y"]:
        assert float(lines[column]) == pytest.approx(row[column], rel=1e-5)
