"""JS: refstats.js tells the statistics the reference lines need and whether a result has them; axiscontrols.js aggregates again only for more."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js


def line(kind: str, value: float) -> dict:
    """Return a reference line of `kind` and `value`."""
    return {"type": kind, "value": value, "color": "#000000", "dash": "dash"}


# A result of the numeric x "a", the numeric y "b", the temporal y "t", the
# log y "l" and the categorical y "g".
META = {
    "panels": [{"xaxis": "x", "yaxis": "y", "x": 0, "y": 0}],
    "x_columns": ["a"],
    "y_columns": ["b", "t", "l", "g", "a"],
    "x_axes": ["x"],
    "y_axes": ["y", "y", "y", "y", "y"],
    "x_numeric": [True],
    "y_numeric": [True, False, False, False, True],
    "x_log": [False],
    "y_log": [False, False, True, False, False],
    "temporal": {"t": "datetime"},
    "axis_levels": {"g": ["p", "q"]},
    "one_band": False,
}

NEEDED = """async ([meta, settings]) => {
  const m = await import("/static/js/refstats.js");
  const columns = m.numericColumns(meta);
  const needed = m.neededStats((column) => settings[column], columns);
  return { columns, needed: { ...needed } };
}"""

COVERS = """async ([asked, settings]) => {
  const m = await import("/static/js/refstats.js");
  return m.coversStats(asked, m.neededStats((column) => settings[column], Object.keys(settings)));
}"""


def test_the_needed_statistics_of_each_numeric_axis_column(js_page: Page) -> None:
    """Each numeric axis column with lines of the statistics needs its moments and its percentiles, ascending once each; others are left out."""
    settings = {
        "a": {"lines": [line("quantile", 95), line("value", 1), line("quantile", 5), line("quantile", 95)]},
        "b": {"lines": [line("sigma", 3), line("sigma", 0)]},
        "t": {"lines": [line("sigma", 3)]},
        "l": {"lines": [line("quantile", 50)]},
        "g": {"lines": [line("sigma", 1)]},
    }
    got = js_page.evaluate(NEEDED, [META, settings])
    assert got["columns"] == ["a", "b"]
    assert got["needed"] == {
        "a": {"moments": False, "quantiles": [5, 95]},
        "b": {"moments": True, "quantiles": []},
    }
    values_only = js_page.evaluate(NEEDED, [META, {"a": {"lines": [line("value", 1)]}}])
    assert values_only["needed"] == {}


@pytest.mark.parametrize(
    ("lines", "covered"),
    [
        # As aggregated: nothing more.
        ([line("sigma", 2), line("quantile", 95)], True),
        # Another n, a line removed, or none left: the same statistics.
        ([line("sigma", 3), line("quantile", 95)], True),
        ([line("quantile", 95)], True),
        ([line("value", 1)], True),
        ([], True),
        # A new percentile.
        ([line("sigma", 2), line("quantile", 95), line("quantile", 5)], False),
    ],
)
def test_more_statistics_are_not_covered(js_page: Page, lines: list, covered: bool) -> None:
    """A result aggregated for some lines covers fewer of them and another n; a new percentile is not covered."""
    asked = {"b": {"moments": True, "quantiles": [95]}}
    assert js_page.evaluate(COVERS, [asked, {"b": {"lines": lines}}]) is covered


def test_the_first_lines_of_a_column_are_not_covered(js_page: Page) -> None:
    """The first sigma line of a column aggregated without moments, or without its column, is not covered."""
    assert js_page.evaluate(COVERS, [{"b": {"moments": False, "quantiles": [5]}}, {"b": {"lines": [line("sigma", 1)]}}]) is False
    assert js_page.evaluate(COVERS, [{}, {"b": {"lines": [line("quantile", 5)]}}]) is False


# An `AxisControls` whose result `meta` draws "b" on y, aggregated with the
# statistics `asked`; it applies `lines` to "b" and returns how many times it
# plotted the graph again and relayouted it.
APPLY = """async ([meta, asked, steps]) => {
  const m = await import("/static/js/axiscontrols.js");
  const { emptySettings } = await import("/static/js/axisdialog.js");
  let drawn = { ...meta, ref_stats_asked: asked };
  const calls = { replot: 0, relayout: 0 };
  const a = new m.AxisControls({
    gd: { _fullLayout: {} },
    current: () => drawn,
    hideHover: () => {},
    relayoutOwn: async () => calls.relayout++,
    plotted: () => true,
    // A new result, aggregated with what the lines need (`refStats`).
    replot: async () => {
      calls.replot++;
      const numeric = new Map([["a", true], ["b", true]]);
      drawn = { ...drawn, ref_stats_asked: a.refStats({ x: ["a"], y: ["b"] }, numeric, new Map()) };
      return drawn;
    },
    followMargin: () => {},
    openPlotMenu: () => {},
  });
  const out = [];
  for (const lines of steps) {
    await a.apply("y", "b", { ...emptySettings(), lines }, null, undefined);
    out.push({ ...calls });
  }
  return out;
}"""


def test_apply_plots_again_only_for_more_statistics(js_page: Page) -> None:
    """The first sigma line plots the graph again; another n, a removal and a color are drawn as they are; a new percentile plots again."""
    sigma = line("sigma", 2)
    steps = [
        [sigma],
        [line("sigma", 3)],
        [],
        [line("value", 1)],
        [line("quantile", 95)],
    ]
    calls = js_page.evaluate(APPLY, [META, {}, steps])
    assert [c["replot"] for c in calls] == [1, 1, 1, 1, 2]
    assert [c["relayout"] for c in calls] == [0, 1, 2, 3, 3]
    covered = js_page.evaluate(APPLY, [META, {"b": {"moments": True, "quantiles": [95]}}, [[sigma, line("quantile", 95)]]])
    assert covered == [{"replot": 0, "relayout": 1}]


# Whether the step `target` is drawn on `META` aggregated with `asked`
# without a plot, from the step `shown`.
WITHOUT_PLOT = """async ([meta, asked, shown, target]) => {
  const m = await import("/static/js/refstats.js");
  return m.drawsWithoutPlot({ ...meta, ref_stats_asked: asked }, shown, target);
}"""


def step(lines: list, **changes: object) -> dict:
    """Return drawing settings whose dialog gives "b" `lines`, with other parts changed by `changes`."""
    axes = {"dialog": [["b", {"lines": lines}]], "angles": [], "logs": {"x": [], "y": []},
            "reversed": {"x": [], "y": []}, "keepLevels": []}
    out = {"zones": {"y": ["b"]}, "elements": [], "options": {}, "axes": axes, "filters": {}}
    for key, value in changes.items():
        if key in axes:
            axes[key] = value
        else:
            out[key] = value
    return out


@pytest.mark.parametrize(
    ("target", "without"),
    [
        # Another n, a line removed, none left: the statistics the result has.
        (step([line("sigma", 3), line("quantile", 95)]), True),
        (step([line("quantile", 95)]), True),
        (step([]), True),
        # A percentile, or the moments, the result was not aggregated with.
        (step([line("sigma", 2), line("quantile", 5)]), False),
        # Another part of the settings: the graph, an angle.
        (step([line("sigma", 2)], zones={"y": ["a"]}), False),
        (step([line("sigma", 2)], angles=[["y:b", 30]]), False),
    ],
)
def test_a_step_of_the_dialog_alone_draws_without_a_plot(js_page: Page, target: dict, without: bool) -> None:
    """A step of undo and redo that changes the dialog's settings alone, whose lines the result has the statistics of, is drawn without a plot."""
    shown = step([line("sigma", 2), line("quantile", 95)])
    asked = {"b": {"moments": True, "quantiles": [95]}}
    assert js_page.evaluate(WITHOUT_PLOT, [META, asked, shown, target]) is without
    lacking = {"b": {"moments": False, "quantiles": [95]}}
    needs_moments = step([line("sigma", 1)])
    assert js_page.evaluate(WITHOUT_PLOT, [META, lacking, shown, needs_moments]) is False
