"""JS: bandticks.js thins the labels of a categorical axis so that they read."""

from __future__ import annotations

from itertools import pairwise

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

MONTHS = [f"{y}-{m:02d}" for y in range(1990, 2025) for m in range(1, 13)]
IDS = [f"L{i}" for i in range(10_000)]
LONG_LEVEL = "level_" + "x" * 100

# Returns the ticks of `levels` over all their bands on an axis `length`
# pixels long.
BAND_TICKS = """async ({ levels, length, across, room }) => {
  const { bandTicks } = await import("/static/js/bandticks.js");
  return bandTicks(levels, [-0.5, levels.length - 0.5], length, across, room);
}"""


def assert_readable(ticks: dict, levels: list[str], whole: bool) -> None:
    """Check that the labels name their levels (whole, or cut to "…"), evenly spaced and between 5 and 100."""
    at, texts = ticks["tickvals"], ticks["ticktext"]
    assert 5 <= len(at) <= 100
    assert len({b - a for a, b in pairwise(at)}) == 1
    for i, text in zip(at, texts, strict=True):
        if whole:
            assert text == levels[i]
        else:
            assert text == levels[i] or levels[i].startswith(text.removesuffix("…"))


@pytest.mark.parametrize("length", [300, 800])
def test_420_levels_on_y_tick_one_label_a_line(js_page: Page, length: int) -> None:
    """Months on Y draw with thinned labels a line of text apart."""
    ticks = js_page.evaluate(
        BAND_TICKS, {"levels": MONTHS, "length": length, "across": True, "room": 44}
    )
    assert_readable(ticks, MONTHS, whole=False)
    step = ticks["tickvals"][1] - ticks["tickvals"][0]
    assert step * length / len(MONTHS) >= 16


@pytest.mark.parametrize("length", [500, 1200])
def test_10000_levels_draw_with_tens_of_ticks(js_page: Page, length: int) -> None:
    """10,000 levels on X draw with whole labels at a step that fits them."""
    ticks = js_page.evaluate(
        BAND_TICKS, {"levels": IDS, "length": length, "across": False, "room": 0}
    )
    assert_readable(ticks, IDS, whole=True)


def test_worst_levels_tick_in_their_bands(js_page: Page) -> None:
    """A long level ends in "…" within its band, an empty one shows its placeholder, and markup is escaped for plotly."""
    result = js_page.evaluate(
        """async (long) => {
          const { bandTicks, fitText, plotlyText } = await import("/static/js/bandticks.js");
          const { levelText } = await import("/static/js/names.js");
          const ctx = document.createElement("canvas").getContext("2d");
          ctx.font = '12px "Open Sans", verdana, arial, sans-serif';
          const cut = fitText(long, 100);
          return {
            ticks: bandTicks([long, "", "<b>bold</b>"], [-0.5, 2.5], 600, false, 0),
            cut,
            cutWidth: ctx.measureText(cut).width,
            whole: fitText("short", 100),
            empty: levelText(""),
            markup: plotlyText("a & <b>bold</b>"),
          };
        }""",
        LONG_LEVEL,
    )
    assert result["ticks"]["tickvals"] == [0, 1, 2]
    long, empty, markup = result["ticks"]["ticktext"]
    assert long.endswith("…") and LONG_LEVEL.startswith(long.removesuffix("…"))
    assert empty == "（空文字列）"
    assert markup == "&lt;b&gt;bold&lt;/b&gt;"
    assert result["cut"].endswith("…") and result["cutWidth"] <= 100
    assert result["whole"] == "short"
    assert result["empty"] == "（空文字列）"
    assert result["markup"] == "a &amp; &lt;b&gt;bold&lt;/b&gt;"
