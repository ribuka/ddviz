"""JS: saves.js words a save's state and fills its bar; notice.js holds a save's toast until it ends (Issue #194)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# Returns [text in the toast, text in the history, bar] of each save state.
STATES = """async (saves) => {
  const { saveText, savePercent } = await import("/static/js/saves.js");
  return saves.map((s) => {
    const save = { format: "csv", done: 0, total: 0, received: 0, transferTotal: 0, ...s };
    if (save.ended) save.ended = new Date(2026, 10, 15, 9, 5);
    return [saveText(save, true), saveText(save, false), savePercent(save)];
  });
}"""


def test_a_saves_state_in_words_and_its_bar(js_page: Page) -> None:
    """The export fills the bar to 90%, the transfer the rest; the sizes share the larger's unit."""
    states = js_page.evaluate(
        STATES,
        [
            {"state": "counting"},
            {"state": "writing", "done": 12_000_000, "total": 100_000_000},
            {"state": "writing", "done": 0, "total": 0},
            {"state": "transfer"},
            {"state": "transfer", "received": 500_000, "transferTotal": 1_400_000},
            {"state": "transfer", "received": 1_200_000_000, "transferTotal": 1_400_000_000},
            {"state": "transfer", "received": 1_200_000_000},
            {"state": "transfer", "received": 512, "transferTotal": 900, "cancelling": True},
            {"state": "saved", "name": "a.csv", "size": 1_234_567, "ended": True},
            {"state": "saved", "name": "a.csv", "size": 999, "ended": True},
            {"state": "browser", "name": "a.csv", "ended": True},
            {"state": "error", "error": "x", "ended": True},
            {"state": "cancelled", "ended": True},
            {"state": "cancelled", "name": "a.csv", "ended": True},
            {"state": "missing", "name": "a.csv", "ended": True},
        ],
    )
    toast, row, bar = zip(*states, strict=True)
    assert list(toast[:8]) == [
        "書き出す行を数えています…",
        "データを書き出しています（12,000,000 / 100,000,000 行）",
        "データを書き出しています（0 / 0 行）",
        "保存しています…",
        "保存しています（0.5 / 1.4 MB）",
        "保存しています（1.2 / 1.4 GB）",
        "保存しています（1.2 GB）",
        "中止しています…",
    ]
    assert bar[0] is None
    assert bar[1] == pytest.approx(10.8)
    assert bar[2] == 90
    assert bar[3] == 90
    assert bar[4] == pytest.approx(90 + 10 * 500 / 1400)
    assert bar[6] == 90
    assert list(toast[8:]) == [
        "ダウンロードに保存しました（a.csv）",
        "ダウンロードに保存しました（a.csv）",
        "ダウンロードを開始しました（a.csv）",
        "保存できませんでした：x",
        "保存を中止しました",
        "保存を中止しました（a.csv）",
        "ダウンロードに保存しました（a.csv）",
    ]
    assert list(row[8:]) == [
        "1.2 MB · 09:05",
        "999 B · 09:05",
        "ブラウザーのダウンロード · 09:05",
        "失敗：x",
        "中止しました",
        "中止しました",
        "移動または削除されました",
    ]


def test_a_held_toast_stays_until_it_settles(clock_page: Page) -> None:
    """A save's toast does not leave while held; settled, it leaves after its kind's time, and its close is told."""
    page = clock_page
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    page.evaluate(
        """async () => {
          const { Toasts } = await import("/static/js/notice.js");
          window.box = document.createElement("div");
          document.body.append(window.box);
          window.toasts = new Toasts(window.box);
          window.closes = 0;
          window.held = window.toasts.hold(document.createElement("span"), () => window.closes++);
        }"""
    )
    shown = "() => window.box.querySelectorAll('.toast:not(.toast-leaving)').length"
    page.clock.run_for(60000)
    assert page.evaluate(shown) == 1
    assert page.evaluate("window.toasts.settle(window.held, 'error')") is True
    assert page.evaluate("window.held.getAttribute('role')") == "alert"
    page.clock.run_for(9900)
    assert page.evaluate(shown) == 1
    page.clock.run_for(200)
    assert page.evaluate(shown) == 0
    assert page.evaluate("window.closes") == 1
    # Closed, it cannot settle: the save shows its end in a new toast.
    assert page.evaluate("window.toasts.settle(window.held, 'success')") is False
