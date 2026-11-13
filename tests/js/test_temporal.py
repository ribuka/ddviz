"""JS: temporal.js reads and writes the values of temporal axes, and plotly reads its date text back as the same milliseconds."""

from __future__ import annotations

import datetime as dt

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

DAY_MS = 86_400_000


def at_ms(text: str) -> float:
    """Return a naive datetime written as text as milliseconds since the epoch."""
    at = dt.datetime.fromisoformat(text)
    return (at - dt.datetime(1970, 1, 1)) // dt.timedelta(microseconds=1) / 1000  # noqa: DTZ001


# For each kind of temporal axis: the texts typed and the values they read
# as (milliseconds, or seconds of a duration), and values with the text the
# dialog writes for them.
CASES = {
    "datetime": (
        {
            "2026-10-31 01:00:00.123456": at_ms("2026-10-31 01:00:00.123456"),
            "2026-10-31T02:00:00.5": at_ms("2026-10-31 02:00:00.500000"),
            " 2026-10-31 01:30:00.25 ": at_ms("2026-10-31 01:30:00.250000"),
        },
        {at_ms("2026-10-31 01:30:00.250000"): "2026-10-31 01:30:00.25"},
    ),
    "date": (
        {
            "2026-11-01 12:30": at_ms("2026-11-01 12:30"),
            "2026-11-03": at_ms("2026-11-03 00:00"),
        },
        {
            at_ms("2026-11-02 00:00"): "2026-11-02",
            at_ms("2026-11-01 12:30"): "2026-11-01 12:30:00",
        },
    ),
    "time": (
        {"-00:01:00": -60_000, "24:01:00": DAY_MS + 60_000, "12:00": 12 * 3_600_000},
        {12 * 3_600_000: "12:00:00", -60_000: "-00:01:00", DAY_MS + 60_500: "24:01:00.5"},
    ),
    "duration": (
        {"-5": -5, "100.5": 100.5, "-0.25": -0.25},
        {-0.25: "-0.25", 100.5: "100.5"},
    ),
}

CONVERT = """async ({ kind, texts, values }) => {
  const { axisText, readAxisValue } = await import("/static/js/temporal.js");
  return {
    read: texts.map((text) => readAxisValue(kind, text)),
    written: values.map((value) => axisText(kind, value)),
  };
}"""


@pytest.mark.parametrize("kind", list(CASES))
def test_the_values_of_each_kind_read_and_write(js_page: Page, kind: str) -> None:
    """Each kind reads its texts as their values and writes values as the dialog shows them."""
    typed, shown = CASES[kind]
    result = js_page.evaluate(
        CONVERT, {"kind": kind, "texts": list(typed), "values": list(shown)}
    )
    assert result["read"] == [{"value": pytest.approx(v, abs=1e-3)} for v in typed.values()]
    assert result["written"] == list(shown.values())


def test_wrong_values_tell_why(js_page: Page) -> None:
    """Dates that do not exist, wrong times, time zones, empty text and times past plotly's dates are refused with their reason."""
    cases = [
        ("datetime", "2026-02-30", "存在しない日付です"),
        ("datetime", "2026-13-01", "存在しない日付です"),
        ("datetime", "2026-10-31 24:00", "時刻が正しくありません"),
        ("datetime", "2026-10-31 12:61", "時刻が正しくありません"),
        ("datetime", "", "値を入れてください"),
        ("datetime", "2026-10-31 12:00Z", "タイムゾーンは付けられません"),
        ("time", "9" * 309 + ":00", "時間が大きすぎます"),
        ("time", "100000000000000:00", "時間が大きすぎます"),
        ("time", "-100000000000000:00", "時間が大きすぎます"),
        ("duration", "abc", "秒数を入れてください"),
    ]
    read = js_page.evaluate(
        """async (cases) => {
          const { readAxisValue } = await import("/static/js/temporal.js");
          return cases.map(([kind, text]) => readAxisValue(kind, text));
        }""",
        [[kind, text] for kind, text, _ in cases],
    )
    assert read == [{"error": why} for _, _, why in cases]


def test_a_range_within_milliseconds_reads_back_the_same(js_page: Page) -> None:
    """A range of a deep zoom written as plotly's date text reads back from a plotly date axis as the very same milliseconds, either way round."""
    start = at_ms("2026-10-31 00:00") + 333.000123
    ranges = [[start, start + 3.0004567], [start + 3.0004567, start]]
    result = js_page.evaluate(
        """async (ranges) => {
          if (!window.Plotly) {
            await new Promise((resolve, reject) => {
              const script = document.createElement("script");
              script.src = "/static/vendor/plotly-4.1.1.min.js";
              script.onload = resolve;
              script.onerror = reject;
              document.head.append(script);
            });
          }
          const { dateText, linearRange } = await import("/static/js/temporal.js");
          const div = document.createElement("div");
          document.body.append(div);
          const out = [];
          for (const range of ranges) {
            await Plotly.newPlot(div, [], { xaxis: { type: "date", range: range.map(dateText) } });
            out.push(linearRange(div._fullLayout.xaxis));
          }
          Plotly.purge(div);
          div.remove();
          return out;
        }""",
        ranges,
    )
    assert result == ranges
