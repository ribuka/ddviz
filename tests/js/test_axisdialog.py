"""JS: axisdialog.js checks the fields of an axis's dialog and turns its settings into plotly's attributes."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.js

DAY_MS = 86_400_000
UNITS = ["millisecond", "second", "minute", "hour", "day", "week"]
DIGITS_ERROR = "0〜15 の整数にしてください"
ANGLE_ERROR = "−90〜90 の整数にしてください"
COUNT_ERROR = "有効な正の整数を入力してください"
LINE = {"color": "#000000", "dash": "dash"}

# Opens the dialog with `args` (the settings over empty ones) and records
# each apply in `window.applied` as {settings, range, angle}.
OPEN = """async (args) => {
  const m = await import("/static/js/axisdialog.js");
  window.applied = [];
  m.openAxisDialog({
    title: "X 軸: c",
    ...args,
    settings: { ...m.emptySettings(), ...(args.settings ?? {}) },
    onApply: (settings, range, angle) => window.applied.push({ settings, range, angle }),
  });
}"""

# Calls the functions of axisdialog.js named in `calls`, `[name, ...args]`.
CALL = """async (calls) => {
  const m = await import("/static/js/axisdialog.js");
  return calls.map(([name, ...args]) => m[name](...args));
}"""


# Closes the dialogs and removes them at once (their "close" event, which
# removes them, comes later).
CLOSE = "() => document.querySelectorAll('dialog.axis-dialog').forEach((d) => { d.close(); d.remove(); })"


def at_ms(text: str) -> float:
    """Return a naive datetime written as text as milliseconds since the epoch."""
    at = dt.datetime.fromisoformat(text)
    return (at - dt.datetime(1970, 1, 1)) // dt.timedelta(microseconds=1) / 1000  # noqa: DTZ001


def meta(**axes: dict) -> dict:
    """Return a result of one panel (or of the panels given) with an x and a y column, numeric and linear unless `axes` says otherwise."""
    out = {
        "panels": [{"xaxis": "x", "yaxis": "y", "x": 0, "y": 0}],
        "x_columns": ["a"],
        "y_columns": ["b"],
        "x_numeric": [True],
        "y_numeric": [True],
        "x_log": [False],
        "y_log": [False],
        "temporal": {},
        "axis_levels": {},
        "one_band": False,
    }
    return {**out, **axes}


@pytest.fixture
def page(js_page: Page) -> Iterator[Page]:
    """Return the shared page, closing the dialog a test leaves open."""
    yield js_page
    js_page.evaluate(CLOSE)


def open_dialog(page: Page, **args: object) -> Locator:
    """Open the dialog with `args` and return it."""
    page.evaluate(OPEN, args)
    dialog = page.locator("dialog.axis-dialog")
    expect(dialog).to_be_visible()
    return dialog


def applied(page: Page) -> list[dict]:
    """Return what the dialog applied, in order."""
    return page.evaluate("window.applied")


def call(page: Page, *calls: list) -> list:
    """Return the results of the calls of axisdialog.js."""
    return page.evaluate(CALL, [list(c) for c in calls])


# ---- numeric axes: the fields, the format of the labels, the angle ----


def test_wrong_numeric_fields_tell_why(page: Page) -> None:
    """An end that is no number, a maximum not above the minimum, a wrong interval or split each have their reason; a line takes a number."""
    base = {"min": "0", "max": "1", "dtick": "", "minor": ""}
    cases = [
        ({"min": "3", "max": "2", "dtick": "-1", "minor": "5"},
         {"max": "最小値より大きくしてください", "dtick": "0 より大きくしてください"}),
        ({"min": "", "max": "a"}, {"min": "数値を入れてください", "max": "数値を入れてください"}),
        ({"dtick": "abc"}, {"dtick": "数値を入れてください"}),
        ({"dtick": "0"}, {"dtick": "0 より大きくしてください"}),
        ({"dtick": "1", "minor": "1"}, {"minor": "2〜100 の整数にしてください"}),
        ({"dtick": "1", "minor": "101"}, {"minor": "2〜100 の整数にしてください"}),
        ({"dtick": "1", "minor": "2.5"}, {"minor": "2〜100 の整数にしてください"}),
        ({"minor": "2"}, {"minor": "間隔を入れたときだけ使えます"}),
    ]
    results = call(page, *[["readFields", {**base, **fields}] for fields, _ in cases])
    assert results == [{"errors": errors} for _, errors in cases]
    (good,) = call(page, ["readFields", {**base, "min": "-1", "dtick": "0.5", "minor": "5"}])
    assert good == {
        "range": [-1, 1], "dtick": 0.5, "unit": None, "minor": 5,
        "format": "auto", "digits": None, "separators": False,
    }

    dialog = open_dialog(page, range=[0, 1])
    dialog.locator("input[name=line]").fill("a")
    dialog.get_by_role("button", name="追加").click()
    expect(dialog.locator("input[name=line] ~ .axis-dialog-error")).to_have_text(
        "数値を入れてください"
    )
    expect(dialog.locator(".axis-dialog-line")).to_have_count(0)


def test_each_format_uses_only_its_fields(page: Page) -> None:
    """Automatic uses the separators, decimal both, exponent the digits, percent both; a field not used is disabled but keeps what was typed."""
    dialog = open_dialog(page, range=[0, 1])
    form = dialog.locator("select[name=format]")
    digits = dialog.locator("input[name=digits]")
    separators = dialog.locator("input[name=separators]")
    expect(form).to_have_value("auto")
    expect(digits).to_have_value("2")
    expect(digits).to_be_disabled()
    expect(separators).not_to_be_checked()
    expect(separators).to_be_enabled()
    form.select_option("fixed")
    digits.fill("0")
    separators.check()
    form.select_option("exponent")
    expect(digits).to_be_enabled()
    expect(separators).to_be_disabled()
    form.select_option("percent")
    expect(separators).to_be_enabled()
    expect(separators).to_be_checked()
    expect(digits).to_have_value("0")


def test_wrong_digits_apply_nothing(page: Page) -> None:
    """Digits outside 0 to 15 are refused with the other fields; a format that does not use them does not check them."""
    base = {"min": "0", "max": "1", "dtick": "5000", "minor": ""}
    results = call(
        page,
        *[["readFields", {**base, "format": "exponent", "digits": d}]
          for d in ["16", "", "1.5", "-1", "a"]],
        ["readFields", {**base, "format": "auto", "digits": "a"}],
    )
    assert results[:-1] == [{"errors": {"digits": DIGITS_ERROR}}] * 5
    assert "errors" not in results[-1]

    dialog = open_dialog(page, range=[0, 1])
    dialog.locator("select[name=format]").select_option("exponent")
    dialog.locator("input[name=digits]").fill("16")
    dialog.locator("input[name=dtick]").fill("5000")
    dialog.get_by_role("button", name="OK").click()
    error = dialog.locator("input[name=digits] ~ .axis-dialog-error")
    expect(error).to_have_text(DIGITS_ERROR)
    expect(dialog).to_be_visible()
    assert applied(page) == []
    # A disabled field is not checked: its error goes.
    dialog.locator("select[name=format]").select_option("auto")
    expect(error).to_have_text("")


def test_the_formats_turn_into_plotly_attributes(page: Page) -> None:
    """Each format is a d3-format of its digits and separators; automatic keeps plotly's labels, with separators when asked."""
    results = call(
        page,
        ["formatAttributes", {"format": "fixed", "digits": 0, "separators": True}],
        ["formatAttributes", {"format": "exponent", "digits": 2, "separators": False}],
        ["formatAttributes", {"format": "percent", "digits": 2, "separators": True}],
        ["formatAttributes", {"format": "auto", "digits": None, "separators": True}],
        ["formatAttributes", {"format": "auto", "digits": None, "separators": False}],
        ["readFields", {"min": "0", "max": "1", "dtick": "", "minor": "",
                        "format": "fixed", "digits": " 0 ", "separators": True}],
        ["readFields", {"min": "0", "max": "1", "dtick": "", "minor": "",
                        "format": "exponent", "digits": "2", "separators": True}],
    )
    assert results[:5] == [
        {"tickformat": ",.0f", "separatethousands": None},
        {"tickformat": ".2e", "separatethousands": None},
        {"tickformat": ",.2%", "separatethousands": None},
        {"tickformat": None, "separatethousands": True},
        {"tickformat": None, "separatethousands": None},
    ]
    assert (results[5]["format"], results[5]["digits"], results[5]["separators"]) == ("fixed", 0, True)
    # Exponent has no separators.
    assert (results[6]["format"], results[6]["digits"], results[6]["separators"]) == ("exponent", 2, False)


def test_the_applied_format_opens_again(page: Page) -> None:
    """The dialog opens with the format, digits and separators applied."""
    dialog = open_dialog(
        page, range=[0, 1], settings={"format": "percent", "digits": 3, "separators": True}
    )
    expect(dialog.locator("select[name=format]")).to_have_value("percent")
    expect(dialog.locator("input[name=digits]")).to_have_value("3")
    expect(dialog.locator("input[name=separators]")).to_be_checked()


def test_wrong_angles_are_refused(page: Page) -> None:
    """−91, 91, a fraction, text, full-width digits, two signs and an exponent are refused; the bounds, a sign, spaces and an empty field are taken."""
    wrong = ["-91", "91", "22.5", "abc", "４５", "+-4", "1e1"]
    good = {" +90 ": 90, "-90": -90, "0": 0, "-0": 0, "": None, " ": None}
    results = call(page, *[["readAngle", text] for text in [*wrong, *good]])
    assert results[: len(wrong)] == [{"error": ANGLE_ERROR}] * len(wrong)
    assert results[len(wrong) :] == [{"value": v} for v in good.values()]


def test_a_log_axis_has_no_angle_until_linear(page: Page) -> None:
    """A numeric axis on a log scale opens no dialog and draws plotly's labels; linear again, its angle is drawn."""
    log = meta(y_numeric=[False], y_log=[True])
    linear = meta()
    angle = "(role) => (role === 'y' ? 45 : null)"
    kinds, layouts = page.evaluate(
        f"""async ([log, linear]) => {{
          const m = await import("/static/js/axisdialog.js");
          const none = () => undefined;
          return [
            [m.dialogKind(log, "y", 0), m.hasAngle(log, "y", 0),
             m.dialogKind(linear, "y", 0), m.hasAngle(linear, "y", 0)],
            [m.decorate({{}}, log, none, {angle}), m.decorate({{}}, linear, none, {angle})],
          ];
        }}""",
        [log, linear],
    )
    assert kinds == [None, False, "number", True]
    assert "tickangle" not in layouts[0].get("yaxis", {})
    assert layouts[1]["yaxis"] == {"tickangle": 45}


def test_temporal_axes_and_the_one_band_have_no_angle(page: Page) -> None:
    """A temporal axis's dialog has no angle; the one band of an empty X opens no dialog; a categorical axis takes the angle alone."""
    temporal = meta(x_numeric=[False], temporal={"a": "datetime"})
    band = meta(x_numeric=[False], one_band=True, axis_levels={"a": ["p", "q"]})
    category = meta(x_numeric=[False], axis_levels={"a": ["p", "q"]})
    results = page.evaluate(
        """async (metas) => {
          const m = await import("/static/js/axisdialog.js");
          return metas.map((meta) => [m.dialogKind(meta, "x", 0), m.hasAngle(meta, "x", 0)]);
        }""",
        [temporal, band, category],
    )
    assert results == [["datetime", False], [None, False], ["category", True]]
    dialog = open_dialog(page, kind="datetime", range=[0, DAY_MS])
    expect(dialog.locator("input[name=angle]")).to_have_count(0)


# ---- temporal axes ----

# For each kind of temporal axis: the ends and the reference line typed, the
# range and the line's position they stand for, the text of the line in the
# list, and the shape of the text of the ends written when the dialog opens.
CASES = {
    "datetime": (
        "2026-10-31 01:00:00.123456",
        "2026-10-31T02:00:00.5",
        "2026-10-31 01:30:00.25",
        [at_ms("2026-10-31 01:00:00.123456"), at_ms("2026-10-31 02:00:00.500000")],
        at_ms("2026-10-31 01:30:00.250000"),
        "2026-10-31 01:30:00.25",
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d{1,6})?",
    ),
    "date": (
        "2026-11-01 12:30",
        "2026-11-03",
        "2026-11-02",
        [at_ms("2026-11-01 12:30"), at_ms("2026-11-03 00:00")],
        at_ms("2026-11-02 00:00"),
        "2026-11-02",
        r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2}(\.\d{1,6})?)?",
    ),
    "time": (
        "-00:01:00",
        "24:01:00",
        "12:00",
        [-60_000, DAY_MS + 60_000],
        12 * 3_600_000,
        "12:00:00",
        r"-?\d{2,}:\d{2}:\d{2}(\.\d{1,6})?",
    ),
    "duration": (
        "-5",
        "100.5",
        "-0.25",
        [-5, 100.5],
        -0.25,
        "-0.25",
        r"-?\d+(\.\d+)?(e[+-]\d+)?",
    ),
}
# A range shown when the dialog opens, for each kind.
SHOWN = {
    "datetime": [at_ms("2026-10-31 00:00:00.000001"), at_ms("2026-10-31 16:39:00.000999")],
    "date": [at_ms("2026-10-31 00:00"), at_ms("2029-07-26 12:00")],
    "time": [-1_234.5, DAY_MS - 0.25],
    "duration": [-49.95, 1048.95],
}


@pytest.mark.parametrize("kind", list(CASES))
def test_a_temporal_axis_sets_its_range_and_reference_lines(page: Page, kind: str) -> None:
    """The dialog opens at the range shown in its kind's text; left alone it applies the very range, and the range and line typed land on their values."""
    low, high, line, expected, at, listed, shape = CASES[kind]
    dialog = open_dialog(page, kind=kind, range=SHOWN[kind])
    for name in ["min", "max"]:
        assert re.fullmatch(shape, dialog.locator(f"input[name={name}]").input_value())
    if kind == "duration":
        expect(dialog.locator(".axis-dialog-unit")).to_have_text(["秒", "秒", "秒"])
    else:
        expect(dialog.locator(".axis-dialog-unit")).to_have_count(0)
    dialog.get_by_role("button", name="適用").click()
    assert applied(page)[0]["range"] == SHOWN[kind]

    dialog.locator("input[name=min]").fill(low)
    dialog.locator("input[name=max]").fill(high)
    dialog.locator("input[name=line]").fill(line)
    dialog.get_by_role("button", name="追加").click()
    expect(dialog.locator(".axis-dialog-line-value")).to_have_text([listed])
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_have_count(0)
    last = applied(page)[-1]
    assert last["range"] == pytest.approx(expected, abs=1e-3)
    assert last["settings"]["lines"] == [{"value": pytest.approx(at, abs=1e-3), **LINE}]
    assert last["angle"] is None


def test_wrong_fields_of_a_temporal_axis_tell_why(page: Page) -> None:
    """Dates that do not exist, wrong times, empty ends, a minimum not below the maximum, wrong intervals and splits are each refused beside their field."""
    cases = [
        (("2026-02-30", "2026-10-31 24:00", "0", "5"),
         {"min": "存在しない日付です", "max": "時刻が正しくありません", "dtick": "0 より大きくしてください"}),
        (("", "2026-10-31 12:00Z", "abc", "11"),
         {"min": "値を入れてください", "max": "タイムゾーンは付けられません",
          "dtick": "数値を入れてください", "minor": "2〜10 の整数にしてください"}),
        (("2026-10-31 12:00", "2026-10-31 12:00:00.0", "", "2"),
         {"max": "最小値より大きくしてください", "minor": "間隔を入れたときだけ使えます"}),
        (("2026-10-31 12:61", "2026-10-31", "1", "1"),
         {"min": "時刻が正しくありません", "minor": "2〜10 の整数にしてください"}),
        (("2026-10-31 12:61", "2026-10-31", "1", "1.5"),
         {"min": "時刻が正しくありません", "minor": "2〜10 の整数にしてください"}),
    ]
    fields = [
        {"kind": "datetime", "min": a, "max": b, "dtick": c, "minor": d, "unit": "minute"}
        for (a, b, c, d), _ in cases
    ]
    results = call(page, *[["readFields", f] for f in fields])
    assert results == [{"errors": errors} for _, errors in cases]

    # A huge time, as an end and as a line.
    dialog = open_dialog(page, kind="time", range=[0, DAY_MS])
    errors = dialog.locator(".axis-dialog-error")
    for text in ["9" * 309 + ":00", "100000000000000:00", "-100000000000000:00"]:
        dialog.locator("input[name=max]").fill(text)
        dialog.get_by_role("button", name="OK").click()
        expect(errors.nth(1)).to_have_text("時間が大きすぎます")
        dialog.locator("input[name=line]").fill(text)
        dialog.get_by_role("button", name="追加").click()
        expect(dialog.locator("input[name=line] ~ .axis-dialog-error")).to_have_text(
            "時間が大きすぎます"
        )
    expect(dialog.locator(".axis-dialog-line")).to_have_count(0)
    assert applied(page) == []


def test_a_range_left_as_written_is_the_very_range(page: Page) -> None:
    """Applied as written, the range of a zoom within milliseconds is the same doubles, not their text rounded to the microsecond."""
    start = at_ms("2026-10-31 00:00") + 333.000123
    shown = [start, start + 3.0004567]
    dialog = open_dialog(page, kind="datetime", range=shown)
    dialog.get_by_role("button", name="OK").click()
    assert applied(page)[0]["range"] == shown


def test_temporal_ticks_and_their_minor_splits(page: Page) -> None:
    """Fixed intervals of a unit start at midnight (0 seconds of a duration), split by the minor parts; a week is 7 days; a unit alone keeps plotly's ticks."""
    auto = {"tickmode": None, "tick0": None, "dtick": None, "minor": None}
    midnight = "1970-01-01 00:00:00"
    results = call(
        page,
        *[["tickAttributes", {"dtick": 15, "unit": "minute", "minor": parts}, "time"]
          for parts in [3, 2, 10]],
        ["tickAttributes", {"dtick": 1, "unit": "week", "minor": None}, "time"],
        ["tickAttributes", {"dtick": 100, "unit": "second", "minor": 4}, "duration"],
        ["tickAttributes", {"dtick": None, "unit": "hour", "minor": None}, "time"],
        ["readFields", {"kind": "time", "min": "0:00", "max": "1:00", "dtick": "",
                        "unit": "hour", "minor": ""}],
    )
    for parts, attributes in zip([3, 2, 10], results[:3], strict=True):
        assert attributes == {
            "tickmode": "linear", "tick0": midnight, "dtick": 900_000,
            "minor": {"tick0": midnight, "dtick": 900_000 / parts, "showgrid": True},
        }
    assert results[3] == {"tickmode": "linear", "tick0": midnight, "dtick": 7 * DAY_MS, "minor": None}
    assert results[4] == {
        "tickmode": "linear", "tick0": 0, "dtick": 100,
        "minor": {"tick0": 0, "dtick": 25, "showgrid": True},
    }
    assert results[5] == auto
    # A unit without an interval is not kept.
    assert (results[6]["dtick"], results[6]["unit"]) == (None, None)


def test_temporal_ticks_and_lines_draw_on_every_panel(page: Page) -> None:
    """The ticks and lines of a column draw on every panel of it; cleared, every panel is plotly's own again."""
    facets = meta(
        panels=[
            {"xaxis": "x", "yaxis": "y", "x": 0, "y": 0},
            {"xaxis": "x2", "yaxis": "y2", "x": 0, "y": 0},
        ],
        x_columns=["clock"],
        x_numeric=[False],
        temporal={"clock": "time"},
    )
    noon = 12 * 3_600_000
    settings = {
        "dtick": 1, "unit": "week", "minor": None, "lines": [{"value": noon, **LINE}],
        "format": "auto", "digits": None, "separators": False,
    }
    drawn, cleared = page.evaluate(
        """async ([meta, settings]) => {
          const m = await import("/static/js/axisdialog.js");
          const of = (s) => (column) => (column === "clock" ? s : undefined);
          return [m.decorate({}, meta, of(settings)), m.decorationUpdate(meta, of(m.emptySettings()))];
        }""",
        [facets, settings],
    )
    for key in ["xaxis", "xaxis2"]:
        assert drawn[key] == {"tickmode": "linear", "tick0": "1970-01-01 00:00:00", "dtick": 7 * DAY_MS}
    assert "yaxis" not in drawn
    assert [(s["xref"], s["yref"], s["x0"], s["line"]["dash"]) for s in drawn["shapes"]] == [
        ("x", "y domain", "1970-01-01 12:00:00", "dash"),
        ("x2", "y2 domain", "1970-01-01 12:00:00", "dash"),
    ]
    assert cleared["shapes"] == []
    for key in ["xaxis", "xaxis2"]:
        assert cleared[f"{key}.tickmode"] is None
        assert cleared[f"{key}.dtick"] is None

    # Opened again, the dialog shows the interval, its unit and the line.
    dialog = open_dialog(page, kind="time", range=[0, DAY_MS], settings=settings)
    expect(dialog.locator("input[name=dtick]")).to_have_value("1")
    expect(dialog.locator("select[name=unit]")).to_have_value("week")
    expect(dialog.locator(".axis-dialog-line-value")).to_have_text(["12:00:00"])


@pytest.mark.parametrize(
    ("kind", "drawn", "unit"),
    [
        ("datetime", 5_000, "second"),
        ("datetime", 500, "millisecond"),
        ("datetime", 0.5, "millisecond"),
        ("datetime", DAY_MS, "day"),
        ("datetime", 2 * DAY_MS, "day"),
        ("datetime", 7 * DAY_MS, "week"),
        ("datetime", "M3", "month"),
        ("date", "M12", "year"),
        ("date", "M24", "year"),
        ("date", "M18", "month"),
        ("time", "M3", "week"),
        ("duration", 20, "second"),
        ("duration", 0.5, "millisecond"),
        ("duration", 7200, "hour"),
        ("date", None, "day"),
        ("datetime", None, "second"),
        ("duration", 0, "second"),
    ],
)
def test_the_unit_of_an_automatic_interval_follows_the_ticks_drawn(
    page: Page, kind: str, drawn: float | str | None, unit: str
) -> None:
    """Without an interval set, the unit picked is the largest up to plotly's ticks: seconds of a duration, months or years of "M<n>"; without ticks, a day or a second."""
    assert call(page, ["drawnUnit", kind, drawn]) == [unit]


@pytest.mark.parametrize(
    ("drawn", "picked"), [("M3", "month"), ("M12", "year"), ("M24", "year")]
)
def test_automatic_calendar_ticks_pick_their_unit(page: Page, drawn: str, picked: str) -> None:
    """Plotly's own ticks of months or years pick that unit with an empty interval and the check off; a unit alone keeps them automatic."""
    dialog = open_dialog(page, kind="date", range=[0, 3_000 * DAY_MS], drawn=drawn)
    expect(dialog.locator("input[name=dtick]")).to_have_value("")
    expect(dialog.locator("select[name=unit]")).to_have_value(picked)
    expect(dialog.locator("input[name=calendar-minor]")).to_be_disabled()
    dialog.locator("select[name=unit]").select_option("month" if picked == "year" else "year")
    dialog.get_by_role("button", name="OK").click()
    settings = applied(page)[0]["settings"]
    assert (settings["dtick"], settings["unit"], settings["minor"]) == (None, None, None)


def test_a_log_duration_draws_none_of_its_settings(page: Page) -> None:
    """A duration on a log axis has no dialog and draws neither its ticks nor its lines; linear again, it draws them."""
    log = meta(y_columns=["took"], y_numeric=[False], y_log=[True], temporal={"took": "duration"})
    linear = {**log, "y_log": [False]}
    settings = {
        "dtick": 100, "unit": "second", "minor": None, "lines": [{"value": 500, **LINE}],
        "format": "auto", "digits": None, "separators": False,
    }
    results = page.evaluate(
        """async ([log, linear, settings]) => {
          const m = await import("/static/js/axisdialog.js");
          const of = (column) => (column === "took" ? settings : undefined);
          return [m.dialogKind(log, "y", 0), m.decorate({}, log, of),
                  m.dialogKind(linear, "y", 0), m.decorate({}, linear, of)];
        }""",
        [log, linear, settings],
    )
    assert results[0] is None
    assert results[1] == {}
    assert results[2] == "duration"
    assert results[3]["yaxis"]["dtick"] == 100
    assert [s["y0"] for s in results[3]["shapes"]] == [500]


def test_calendar_ticks_of_a_date_axis_follow_the_months(page: Page) -> None:
    """A calendar interval is plotly's "M<n>" from 1970-01-01, its minor ticks one unit each; another kind of axis keeps plotly's ticks."""
    midnight = "1970-01-01 00:00:00"
    results = call(
        page,
        ["tickAttributes", {"dtick": 5, "unit": "month", "minor": 5}, "date"],
        ["tickAttributes", {"dtick": 2, "unit": "year", "minor": None}, "datetime"],
        ["tickAttributes", {"dtick": 3, "unit": "year", "minor": 3}, "datetime"],
        ["tickAttributes", {"dtick": 5, "unit": "month", "minor": 5}, "time"],
        ["readFields", {"kind": "date", "min": "2026-01-01", "max": "2027-01-01",
                        "dtick": " 5 ", "unit": "month", "minor": "abc", "calendarMinor": True}],
    )
    assert results[0] == {
        "tickmode": "linear", "tick0": midnight, "dtick": "M5",
        "minor": {"tick0": midnight, "dtick": "M1", "showgrid": True},
    }
    assert results[1] == {"tickmode": "linear", "tick0": midnight, "dtick": "M24", "minor": None}
    assert results[2]["minor"] == {"tick0": midnight, "dtick": "M12", "showgrid": True}
    assert results[3] == {"tickmode": None, "tick0": None, "dtick": None, "minor": None}
    # The field of the minor splits is not read with a calendar unit.
    assert (results[4]["dtick"], results[4]["unit"], results[4]["minor"]) == (5, "month", 5)

    dialog = open_dialog(page, kind="date", range=[0, 3_000 * DAY_MS])
    units = dialog.locator("select[name=unit] option").evaluate_all(
        "(options) => options.map((o) => o.value)"
    )
    assert units == [*UNITS, "month", "year"]
    dialog.locator("input[name=dtick]").fill("5")
    dialog.locator("select[name=unit]").select_option("month")
    expect(dialog.locator("input[name=minor]")).to_be_hidden()
    row = dialog.locator(".axis-dialog-check:has([name=calendar-minor])")
    expect(row).to_have_text("1か月ごとに補助目盛りを表示")
    expect(dialog.locator("input[name=calendar-minor]")).not_to_be_checked()
    dialog.locator("select[name=unit]").select_option("year")
    expect(row).to_have_text("1年ごとに補助目盛りを表示")


def test_wrong_calendar_intervals_and_the_minor_check(page: Page) -> None:
    """A calendar interval takes positive integers whose months are safe; 1 or none turns the minor ticks off; the minor splits and the check are kept apart."""
    wrong = [("month", t) for t in ["0", "-1", "1.5", "1e2", "9007199254740992", "abc"]]
    wrong.append(("year", "750599937895083"))
    results = call(
        page,
        *[["readCount", text, unit] for unit, text in wrong],
        ["readCount", " 750599937895082 ", "year"],
        ["readCount", "", "month"],
        *[["readFields", {"kind": "date", "min": "2026-01-01", "max": "2027-01-01",
                          "dtick": d, "unit": "month", "minor": "", "calendarMinor": c}]
          for d, c in [("3", True), ("3", False), ("1", True), ("", True)]],
    )
    assert results[: len(wrong)] == [{"error": COUNT_ERROR}] * len(wrong)
    assert results[len(wrong) : len(wrong) + 2] == [{"value": 750599937895082}, {"value": None}]
    picked = [(r["dtick"], r["unit"], r["minor"]) for r in results[len(wrong) + 2 :]]
    assert picked == [(3, "month", 3), (3, "month", None), (1, "month", None), (None, None, None)]

    dialog = open_dialog(page, kind="date", range=[0, 3_000 * DAY_MS])
    dtick = dialog.locator("input[name=dtick]")
    unit = dialog.locator("select[name=unit]")
    check = dialog.locator("input[name=calendar-minor]")
    minor = dialog.locator("input[name=minor]")
    error = dialog.locator("input[name=dtick] ~ .axis-dialog-error")
    unit.select_option("month")
    dtick.fill("0")
    expect(check).to_be_disabled()
    dialog.get_by_role("button", name="適用").click()
    expect(error).to_have_text(COUNT_ERROR)
    assert applied(page) == []
    dtick.fill(" 3 ")
    expect(check).to_be_enabled()
    check.check()
    dialog.get_by_role("button", name="適用").click()
    expect(error).to_have_text("")
    assert applied(page)[-1]["settings"]["minor"] == 3

    # Disabled for a while, the check comes back as it was.
    dtick.fill("1")
    expect(check).to_be_disabled()
    expect(check).to_be_checked()
    dtick.fill("")
    expect(check).to_be_disabled()
    dtick.fill("3")
    expect(check).to_be_enabled()
    expect(check).to_be_checked()
    # Weeks take minor splits; their field and the check stay apart.
    unit.select_option("week")
    expect(check).to_be_hidden()
    expect(minor).to_have_value("")
    minor.fill("7")
    dtick.fill("1")
    dialog.get_by_role("button", name="適用").click()
    settings = applied(page)[-1]["settings"]
    assert (settings["dtick"], settings["unit"], settings["minor"]) == (1, "week", 7)
    unit.select_option("month")
    dtick.fill("3")
    expect(check).to_be_checked()
    unit.select_option("week")
    expect(minor).to_have_value("7")
    unit.select_option("month")
    # An interval of 1 applied takes the check off.
    dtick.fill("1")
    dialog.get_by_role("button", name="適用").click()
    assert applied(page)[-1]["settings"]["minor"] is None
    dtick.fill("3")
    expect(check).not_to_be_checked()

    # 12 months set open again as 12 months.
    page.evaluate(CLOSE)
    dialog = open_dialog(
        page, kind="date", range=[0, 3_000 * DAY_MS], settings={"dtick": 12, "unit": "month", "minor": None}
    )
    expect(dialog.locator("input[name=dtick]")).to_have_value("12")
    expect(dialog.locator("select[name=unit]")).to_have_value("month")


@pytest.mark.parametrize("kind", ["time", "duration"])
def test_times_and_durations_have_no_calendar_units(page: Page, kind: str) -> None:
    """A time's or a duration's interval takes no months nor years."""
    assert call(page, ["hasCalendar", kind], ["hasCalendar", "date"], ["hasCalendar", "datetime"]) == [
        False, True, True,
    ]
    dialog = open_dialog(page, kind=kind, range=[0, 1000])
    units = dialog.locator("select[name=unit] option").evaluate_all(
        "(options) => options.map((o) => o.value)"
    )
    assert units == UNITS
    expect(dialog.locator("input[name=calendar-minor]")).to_have_count(0)
