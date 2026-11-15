"""E2E: "Copy graph image" of the plot's menu copies every panel and the legend as a PNG (Issue #221).

The page's `navigator.clipboard.write` is replaced: the test takes the PNG
the page hands the clipboard (`CAPTURE`), decodes it in the page and compares
regions of it with what the page draws. It does not check the OS's clipboard
(the WebView2 check in `docs/spec.md`, "グラフ画像のコピー"), nor whole images
or text widths, which the fonts change.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from playwright.sync_api import Page, Route, expect

from ddviz.server.settings import ImageCopySettings, PlotSettings, Settings
from tests.e2e.test_scatter import FRAMES, place, wait_apart, wait_idle

pytestmark = pytest.mark.e2e

# Takes what the page writes to the clipboard: `window.copied` gets each
# item's type and blob. While `window.holdCopy` is set, the write waits for
# `window.releaseCopy()`.
CAPTURE = """
window.copied = [];
window.holdCopy = false;
addEventListener("DOMContentLoaded", () => {
  navigator.clipboard.write = async (items) => {
    if (window.holdCopy) await new Promise((resolve) => (window.releaseCopy = resolve));
    for (const item of items) {
      for (const type of item.types) window.copied.push({ type, blob: await item.getType(type) });
    }
  };
});
"""

# In-page helpers on the last copied PNG (`window.copied`), decoded once as
# `window.png` ({width, height, data}). Positions are in CSS px of the
# figure (plotly's), which the PNG holds at `scale` from `origin` (the
# figure's top left in the image's CSS px).
HELPERS = """
window.decodeCopy = async () => {
  const bitmap = await createImageBitmap(window.copied.at(-1).blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0);
  window.png = { width: bitmap.width, height: bitmap.height, data: ctx.getImageData(0, 0, bitmap.width, bitmap.height).data };
  return [bitmap.width, bitmap.height];
};
window.pngAt = (x, y) => {
  const { width, data } = window.png;
  const i = (Math.floor(y) * width + Math.floor(x)) * 4;
  return [data[i], data[i + 1], data[i + 2], data[i + 3]];
};
// Counts the pixels of the image in a rectangle (image CSS px) that `test(rgba)` keeps.
window.countIn = (scale, [left, top, right, bottom], test) => {
  let n = 0;
  for (let y = Math.floor(top * scale); y < Math.min(window.png.height, Math.ceil(bottom * scale)); y++) {
    for (let x = Math.floor(left * scale); x < Math.min(window.png.width, Math.ceil(right * scale)); x++) {
      if (test(window.pngAt(x, y))) n++;
    }
  }
  return n;
};
// Text and tick marks: dark gray (plotly's #444 and the legend's #222).
window.darkGray = ([r, g, b]) => Math.max(r, g, b) < 110 && Math.max(r, g, b) - Math.min(r, g, b) < 24;
window.near = (a, b, tolerance = 40) => a.every((v, i) => i > 2 || Math.abs(v - b[i]) <= tolerance);
window.rgbOf = (css) => {
  const ctx = document.createElement("canvas").getContext("2d");
  ctx.fillStyle = css;
  ctx.fillRect(0, 0, 1, 1);
  return Array.from(ctx.getImageData(0, 0, 1, 1).data);
};
// The share of the series canvas's drawn pixels (blended on the white plot
// area) that the image has in the same color at the same place, and how
// many there are. Pixels next to a gridline of the image are left out.
window.layerMatch = (origin, scale) => {
  const canvas = document.querySelector("canvas.image-layers");
  const full = document.getElementById("plot")._fullLayout;
  const ratio = canvas.width / full.width;
  const layer = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
  let drawn = 0;
  let same = 0;
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      const i = (y * canvas.width + x) * 4;
      const a = layer[i + 3] / 255;
      if (a < 0.05) continue;
      const want = [0, 1, 2].map((c) => layer[i + c] * a + 255 * (1 - a));
      const got = window.pngAt((origin[0] + (x + 0.5) / ratio) * scale, (origin[1] + (y + 0.5) / ratio) * scale);
      drawn++;
      if (window.near(got, want, 48)) same++;
    }
  }
  return { drawn, share: drawn ? same / drawn : 0 };
};
"""

# The page's state the copy must leave alone.
STATE = """() => {
  const gd = document.getElementById("plot");
  const ranges = Object.entries(gd._fullLayout)
    .filter(([key]) => /^[xy]axis\\d*$/.test(key))
    .map(([key, axis]) => [key, axis.range]);
  return JSON.stringify({
    ranges,
    dragmode: gd._fullLayout.dragmode,
    selection: [...gd.querySelectorAll(".selectionlayer path")].map((p) => p.getAttribute("d")),
    inactive: [...document.querySelectorAll("#legend .legend-item.inactive")].map((e) => e.textContent),
    scroll: [document.getElementById("scroller").scrollLeft, document.getElementById("scroller").scrollTop],
    legendScroll: document.getElementById("legend").scrollTop,
    layers: document.querySelector("canvas.image-layers").toDataURL().length,
  });
}"""

# The figure's places, in its CSS px: each panel's plot area, the margins
# and the size.
FIGURE = """() => {
  const gd = document.getElementById("plot");
  const full = gd._fullLayout;
  const key = (id) => id.replace(/^([xy])(\\d*)$/, "$1axis$2");
  const panels = [...new Set(Object.keys(full._plots))].map((id) => {
    const plot = full._plots[id];
    const xa = plot.xaxis;
    const ya = plot.yaxis;
    return { id, left: xa._offset, top: ya._offset, right: xa._offset + xa._length, bottom: ya._offset + ya._length };
  });
  return { width: full.width, height: full.height, margin: full.margin, panels };
}"""

N = 1200
COLORS = 40


@pytest.fixture
def scatter_path(tmp_path: Path) -> Path:
    """Write rows of two x and two y columns, colors of 3 and of 40 levels, symbols, facets and a numeric color."""
    rng = np.random.default_rng(1)
    frame = pl.DataFrame(
        {
            "x": rng.normal(0, 1, N),
            "x2": rng.uniform(0, 10, N),
            "y": rng.normal(0, 1, N),
            "y2": rng.uniform(0, 10, N),
            "c": rng.choice(["a", "b", "c"], N),
            "many": [f"level{i % COLORS:02d}" for i in range(N)],
            "k": rng.choice(["p", "q"], N),
            "f": [f"f{i % 6}" for i in range(N)],
            "r": rng.choice(["上", "下"], N),
            "v": rng.uniform(0, 100, N),
        }
    )
    path = tmp_path / "copy.parquet"
    frame.write_parquet(path)
    return path


@pytest.fixture
def page(app_page: Page) -> Page:
    """Return the app's page with the clipboard taken and the image helpers."""
    app_page.add_init_script(CAPTURE)
    app_page.reload()
    app_page.add_script_tag(content=HELPERS)
    expect(app_page.locator("#columns .column").first).to_be_visible()
    return app_page


def open_menu(page: Page) -> None:
    """Right-click the middle of the plot area in sight (of the scroller), off the strips of a grid that scrolls."""
    area = page.locator("#scroller").bounding_box()
    page.mouse.click(area["x"] + area["width"] / 2, area["y"] + area["height"] / 2, button="right")
    expect(page.locator(".plot-menu")).to_be_visible()


def copy_image(page: Page) -> tuple[int, int]:
    """Copy the image from the plot's menu and return the PNG's size, after the success toast."""
    before = page.evaluate("window.copied.length")
    open_menu(page)
    page.locator(".plot-menu .scale-menu-item", has_text="Copy graph image").click()
    expect(page.locator(".plot-menu")).to_have_count(0)
    page.wait_for_function(f"window.copied.length > {before}")
    expect(page.locator("#toasts")).to_contain_text("グラフ画像をクリップボードにコピーしました")
    assert page.evaluate("window.copied.at(-1).type") == "image/png"
    return tuple(page.evaluate("decodeCopy()"))


def layout_of(page: Page) -> dict:
    """Return the image module's margins (`PAD`, `NAME_BAND`)."""
    return page.evaluate(
        """async () => {
          const m = await import("/static/js/plotimage.js");
          return { pad: m.PAD, band: m.NAME_BAND, gap: m.LEGEND_GAP };
        }"""
    )


def dark_in(page: Page, scale: float, rect: list[float]) -> int:
    """Return the dark gray pixels in a rectangle of the image (CSS px)."""
    return page.evaluate("([s, r]) => countIn(s, r, darkGray)", [scale, rect])


def test_the_copy_holds_points_lines_smoothing_labels_and_the_legend(page: Page) -> None:
    """A small faceted plot with lines, smoothing lines, colors and symbols: the PNG has every layer pixel, the ticks, facet labels, axis names and the legend's markers, at 300 DPI on white."""
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "c", "color")
    place(page, "k", "symbol")
    place(page, "r", "row")
    for name in ("line", "smooth"):
        page.locator(f'#elements .element[data-element="{name}"]').click()
        wait_idle(page)
    page.evaluate(FRAMES)
    before = page.evaluate(STATE)
    width, height = copy_image(page)
    assert page.evaluate(STATE) == before
    scale = 300 / 96
    m = layout_of(page)
    fig = page.evaluate(FIGURE)
    origin = [m["pad"] + m["band"], m["pad"]]
    # The image's logical size holds the figure, the bands and the legend.
    assert width >= math.ceil((origin[0] + fig["width"] + m["pad"]) * scale)
    assert height >= math.ceil((origin[1] + fig["height"] + m["band"] + m["pad"]) * scale)
    assert page.evaluate("pngAt(0, 0)") == [255, 255, 255, 255]
    assert page.evaluate("pngAt(png.width - 1, png.height - 1)") == [255, 255, 255, 255]
    match = page.evaluate("([o, s]) => layerMatch(o, s)", [origin, scale])
    assert match["drawn"] > 500
    assert match["share"] > 0.9
    ox, oy = origin
    margin = fig["margin"]
    for panel in fig["panels"]:
        # The y ticks left of each panel row (one column here), the x ticks
        # under the bottom panel, the row labels right of each panel.
        assert dark_in(page, scale, [ox, oy + panel["top"], ox + panel["left"], oy + panel["bottom"]]) > 20
        assert dark_in(page, scale, [ox + panel["right"], oy + panel["top"], ox + fig["width"], oy + panel["bottom"]]) > 20
        # No text inside the plot areas.
        inner = [ox + panel["left"] + 2, oy + panel["top"] + 2, ox + panel["right"] - 2, oy + panel["bottom"] - 2]
        assert dark_in(page, scale, inner) == 0
    bottom = max(p["bottom"] for p in fig["panels"])
    assert dark_in(page, scale, [ox, oy + bottom, ox + fig["width"], oy + fig["height"]]) > 20
    # The axis names: x under the figure, y left of it.
    assert dark_in(page, scale, [ox, oy + fig["height"], ox + fig["width"], oy + fig["height"] + m["band"]]) > 10
    assert dark_in(page, scale, [m["pad"], oy, ox, oy + fig["height"]]) > 10
    assert margin["t"] > 0
    # The legend right of the figure: each color level's marker, the titles and names.
    legend = [ox + fig["width"] + m["gap"], oy, width / scale, height / scale]
    colors = page.evaluate(
        "[...document.querySelectorAll('#legend .legend-item .swatch:not(.shape)')].map((s) => rgbOf(getComputedStyle(s).backgroundColor))"
    )
    assert len(colors) == 3
    for color in colors:
        found = page.evaluate("([s, r, c]) => countIn(s, r, (p) => near(p, c, 12))", [scale, legend, color])
        assert found > 20
    assert dark_in(page, scale, legend) > 200


def test_box_plots_and_a_color_bar_are_copied(page: Page) -> None:
    """Box plots over the bands of a categorical x, and the gradient's color bar with its ticks."""
    place(page, "c", "x")
    place(page, "y", "y")
    place(page, "v", "color")
    page.locator('#elements .element[data-element="box"]').click()
    wait_idle(page)
    page.evaluate(FRAMES)
    width, height = copy_image(page)
    scale = 300 / 96
    m = layout_of(page)
    fig = page.evaluate(FIGURE)
    origin = [m["pad"] + m["band"], m["pad"]]
    match = page.evaluate("([o, s]) => layerMatch(o, s)", [origin, scale])
    assert match["drawn"] > 500
    assert match["share"] > 0.9
    legend = [origin[0] + fig["width"] + m["gap"], origin[1], width / scale, height / scale]
    ends = page.evaluate(
        """async () => {
          const m = await import("/static/js/colorscale.js");
          return [rgbOf(m.cssColor(0)), rgbOf(m.cssColor(1))];
        }"""
    )
    for color in ends:
        found = page.evaluate("([s, r, c]) => countIn(s, r, (p) => near(p, c, 16))", [scale, legend, color])
        assert found > 20
    assert dark_in(page, scale, legend) > 100


def test_a_scrolled_grid_and_legend_are_copied_whole_as_shown(page: Page) -> None:
    """A grid that scrolls both ways, of two x and two y columns, zoomed, with an inactive level and a selection: every panel and every legend item is in the PNG, the labels at the grid's edges only, and the page is left as it was."""
    page.set_viewport_size({"width": 1000, "height": 640})
    place(page, "x", "x")
    place(page, "y", "y")
    zone = page.locator('.zone[data-role="x"]').bounding_box()
    page.locator("#columns .column").filter(has=page.get_by_text("x2", exact=True)).drag_to(
        page.locator('.zone[data-role="x"]'), target_position={"x": zone["width"] * 0.97, "y": zone["height"] / 2}
    )
    wait_idle(page)
    zone = page.locator('.zone[data-role="y"]').bounding_box()
    page.locator("#columns .column").filter(has=page.get_by_text("y2", exact=True)).drag_to(
        page.locator('.zone[data-role="y"]'), target_position={"x": zone["width"] / 2, "y": zone["height"] * 0.97}
    )
    wait_idle(page)
    expect(page.locator('.zone[data-role="x"] .chip-name')).to_have_text(["x", "x2"])
    expect(page.locator('.zone[data-role="y"] .chip-name')).to_have_text(["y", "y2"])
    place(page, "many", "color")
    place(page, "f", "col")
    place(page, "r", "row")
    scroller = page.locator("#scroller")
    assert page.evaluate("(() => { const s = document.getElementById('scroller'); return [s.scrollWidth > s.clientWidth, s.scrollHeight > s.clientHeight]; })()") == [True, True]
    assert page.evaluate("(() => { const l = document.getElementById('legend'); return l.scrollHeight > l.clientHeight; })()")
    # Zoom the first panel with the menu's Zoom and a drag.
    open_menu(page)
    page.locator(".plot-menu .scale-menu-item", has_text="Zoom").click()
    box = page.evaluate(
        """() => {
          const gd = document.getElementById("plot");
          const { xaxis, yaxis } = gd._fullLayout;
          const rect = gd.getBoundingClientRect();
          return { x: rect.left + xaxis._offset, y: rect.top + yaxis._offset, w: xaxis._length, h: yaxis._length };
        }"""
    )
    wait_apart(page)
    page.mouse.move(box["x"] + box["w"] * 0.1, box["y"] + box["h"] * 0.1)
    page.mouse.down()
    page.mouse.move(box["x"] + box["w"] * 0.8, box["y"] + box["h"] * 0.8, steps=5)
    page.mouse.up()
    wait_idle(page)
    # Make the first color level inactive, and select a box.
    page.locator("#legend .legend-item").first.click()
    wait_apart(page)
    open_menu(page)
    page.locator(".plot-menu .scale-menu-item", has_text="Box Select").click()
    page.mouse.move(box["x"] + box["w"] * 0.2, box["y"] + box["h"] * 0.2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["w"] * 0.7, box["y"] + box["h"] * 0.7, steps=5)
    page.mouse.up()
    wait_idle(page)
    expect(page.locator("#table")).to_be_visible()
    page.wait_for_function("() => !document.querySelector('#plot').classList.contains('busy')")
    # Scroll the grid and the legend partway.
    scroller.evaluate("(s) => { s.scrollLeft = 120; s.scrollTop = 80; }")
    page.locator("#legend").evaluate("(l) => { l.scrollTop = 40; }")
    page.evaluate(FRAMES)
    before = page.evaluate(STATE)
    assert json.loads(before)["selection"]
    width, height = copy_image(page)
    page.evaluate(FRAMES)
    assert page.evaluate(STATE) == before
    scale = 300 / 96
    m = layout_of(page)
    fig = page.evaluate(FIGURE)
    origin = [m["pad"] + m["band"], m["pad"]]
    ox, oy = origin
    # The whole grid, at its own size: the PNG is wider than the scroller's area.
    assert width / scale > fig["width"] > scroller.evaluate("(s) => s.clientWidth")
    match = page.evaluate("([o, s]) => layerMatch(o, s)", [origin, scale])
    assert match["drawn"] > 500
    assert match["share"] > 0.9
    # The panel scrolled out of sight at the bottom right has its points.
    last = max(fig["panels"], key=lambda p: (p["bottom"], p["right"]))
    inner = [ox + last["left"] + 2, oy + last["top"] + 2, ox + last["right"] - 2, oy + last["bottom"] - 2]
    colored = "(p) => Math.max(p[0], p[1], p[2]) - Math.min(p[0], p[1], p[2]) > 60"
    assert page.evaluate(f"([s, r]) => countIn(s, r, {colored})", [scale, inner]) > 20
    # The strips' labels lie at the grid's edges once each: none inside a
    # plot area (where the scrolled strips would be), and every edge has them.
    for panel in fig["panels"]:
        inner = [ox + panel["left"] + 2, oy + panel["top"] + 2, ox + panel["right"] - 2, oy + panel["bottom"] - 2]
        assert dark_in(page, scale, inner) == 0
    left = min(p["left"] for p in fig["panels"])
    right = max(p["right"] for p in fig["panels"])
    top = min(p["top"] for p in fig["panels"])
    bottom = max(p["bottom"] for p in fig["panels"])
    for panel in fig["panels"]:
        if panel["left"] == left:
            assert dark_in(page, scale, [ox, oy + panel["top"], ox + left, oy + panel["bottom"]]) > 20
        if panel["right"] == right:
            assert dark_in(page, scale, [ox + right, oy + panel["top"], ox + fig["width"], oy + panel["bottom"]]) > 20
    columns = sorted({(p["left"], p["right"]) for p in fig["panels"]})
    for x0, x1 in columns:
        assert dark_in(page, scale, [ox + x0, oy + bottom, ox + x1, oy + fig["height"]]) > 20
    assert dark_in(page, scale, [ox + left, oy, ox + right, oy + top]) > 100
    # Both x names and both y names.
    assert dark_in(page, scale, [ox, oy + fig["height"], ox + fig["width"] / 2, oy + fig["height"] + m["band"]]) > 10
    assert dark_in(page, scale, [ox + fig["width"] / 2, oy + fig["height"], ox + fig["width"], oy + fig["height"] + m["band"]]) > 10
    # Every legend item, the last one scrolled out of sight too.
    legend = [ox + fig["width"] + m["gap"], oy, width / scale, height / scale]
    colors = page.evaluate(
        "[...document.querySelectorAll('#legend .legend-item .swatch')].map((s) => rgbOf(getComputedStyle(s).backgroundColor))"
    )
    assert len(colors) == COLORS
    for color in (colors[0], colors[-1]):
        found = page.evaluate("([s, r, c]) => countIn(s, r, (p) => near(p, c, 12))", [scale, legend, color])
        assert found > 20
    assert height / scale >= oy + 40 * 22
    # No page UI: the figure's margins are white, not the paper's gray, and
    # no pixel has the accent of the chips and buttons.
    white = "(p) => p[0] === 255 && p[1] === 255 && p[2] === 255"
    corner = [ox, oy, ox + left - 1, oy + top - 1]
    assert page.evaluate(f"([s, r]) => countIn(s, r, {white})", [scale, corner]) > 0
    assert page.evaluate("([s, r]) => countIn(s, r, (p) => !(p[0] === 255 && p[1] === 255 && p[2] === 255) && !darkGray(p))", [scale, [ox + 2, oy + 2, ox + 10, oy + 10]]) == 0
    accent = page.evaluate("(c) => rgbOf(c)", "#2a6fdb")
    whole = [0, 0, width / scale, height / scale]
    assert page.evaluate("([s, r, c]) => countIn(s, r, (p) => near(p, c, 0))", [scale, whole, accent]) == 0


def test_a_selection_panned_out_of_sight_is_cut_at_its_panel(page: Page) -> None:
    """A box selected, then moved partly above its panel by a pan, is cut at the panel's top edge: nothing of it in the top margin."""
    place(page, "x", "x")
    place(page, "y", "y")
    box = page.evaluate(
        """() => {
          const gd = document.getElementById("plot");
          const { xaxis, yaxis } = gd._fullLayout;
          const rect = gd.getBoundingClientRect();
          return { x: rect.left + xaxis._offset, y: rect.top + yaxis._offset, w: xaxis._length, h: yaxis._length };
        }"""
    )
    open_menu(page)
    page.locator(".plot-menu .scale-menu-item", has_text="Box Select").click()
    page.mouse.move(box["x"] + box["w"] * 0.3, box["y"] + box["h"] * 0.15)
    page.mouse.down()
    page.mouse.move(box["x"] + box["w"] * 0.7, box["y"] + box["h"] * 0.45, steps=5)
    page.mouse.up()
    wait_idle(page)
    expect(page.locator("#plot .selectionlayer path").first).to_be_attached()
    # Move the view down by a quarter (a pan, as plotly's relayout): the
    # box's top leaves the panel.
    page.evaluate(
        """() => {
          const gd = document.getElementById("plot");
          const [y0, y1] = gd._fullLayout.yaxis.range;
          const d = (y1 - y0) / 4;
          return Plotly.relayout(gd, { "yaxis.range": [y0 - d, y1 - d] });
        }"""
    )
    wait_idle(page)
    page.wait_for_function("() => !document.querySelector('#plot').classList.contains('busy')")
    top = page.evaluate(
        "() => Math.min(...[...document.querySelectorAll('#plot .selectionlayer path')].map((p) => p.getBBox().y))"
    )
    fig = page.evaluate(FIGURE)
    panel = fig["panels"][0]
    assert top < panel["top"] - 5
    copy_image(page)
    scale = 300 / 96
    m = layout_of(page)
    ox, oy = m["pad"] + m["band"], m["pad"]
    # The outline's gray: plotly's #444 at half opacity on white, and darker.
    gray = "(p) => Math.max(p[0], p[1], p[2]) < 200 && Math.max(p[0], p[1], p[2]) - Math.min(p[0], p[1], p[2]) < 24"
    margin = [ox + panel["left"], oy, ox + panel["right"], oy + panel["top"] - 2]
    assert page.evaluate(f"([s, r]) => countIn(s, r, {gray})", [scale, margin]) == 0
    # The outline still shows inside the panel.
    inside = [ox + panel["left"] + 3, oy + panel["top"] + 3, ox + panel["right"] - 3, oy + panel["bottom"] - 3]
    assert page.evaluate(f"([s, r]) => countIn(s, r, {gray})", [scale, inside]) > 20


def test_a_wrapped_grid_names_its_wrap_column(page: Page) -> None:
    """A wrapped grid has its levels over the panels and the Wrap column's name over the grid."""
    place(page, "x", "x")
    place(page, "y", "y")
    place(page, "f", "wrap")
    width, _ = copy_image(page)
    scale = 300 / 96
    m = layout_of(page)
    fig = page.evaluate(FIGURE)
    top = [m["pad"] + m["band"], m["pad"], m["pad"] + m["band"] + fig["width"], m["pad"] + m["band"]]
    assert dark_in(page, scale, top) > 10
    match = page.evaluate("([o, s]) => layerMatch(o, s)", [[m["pad"] + m["band"], m["pad"] + m["band"]], scale])
    assert match["share"] > 0.9
    assert width > 0


@pytest.mark.parametrize(
    "settings",
    [pytest.param(Settings(plot=PlotSettings(image_copy=ImageCopySettings(dpi=96))), id="96")],
)
def test_the_dpi_of_the_settings_sizes_the_png(page: Page) -> None:
    """At 96 DPI the PNG has as many pixels as CSS px."""
    place(page, "x", "x")
    place(page, "y", "y")
    width, height = copy_image(page)
    m = layout_of(page)
    fig = page.evaluate(FIGURE)
    assert width == math.ceil(m["pad"] + m["band"] + fig["width"] + m["pad"])
    assert height == math.ceil(m["pad"] + fig["height"] + m["band"] + m["pad"])


def test_the_menu_ends_with_the_copy_disabled_while_unsettled(page: Page) -> None:
    """The item follows Reset axes after a separator; it is disabled while a result is awaited and while a copy runs, and no copy starts from it."""
    place(page, "x", "x")
    place(page, "y", "y")
    open_menu(page)
    rows = page.locator(".plot-menu > *")
    expect(rows).to_have_count(7)
    texts = [rows.nth(i).text_content() for i in range(7)]
    classes = [rows.nth(i).get_attribute("class") for i in range(7)]
    assert texts[:3] == ["Zoom", "Pan", "Box Select"]
    assert "scale-menu-separator" in classes[3]
    assert texts[4] == "Reset axes"
    assert "scale-menu-separator" in classes[5]
    assert texts[6] == "Copy graph image"
    expect(rows.nth(6)).to_be_enabled()
    page.keyboard.press("Escape")
    # A copy that waits for the clipboard: the item is disabled meanwhile.
    page.evaluate("window.holdCopy = true")
    open_menu(page)
    page.locator(".plot-menu .scale-menu-item", has_text="Copy graph image").click()
    page.wait_for_function("typeof window.releaseCopy === 'function'")
    open_menu(page)
    expect(page.locator(".plot-menu .scale-menu-item", has_text="Copy graph image")).to_be_disabled()
    page.keyboard.press("Escape")
    page.evaluate("window.holdCopy = false; window.releaseCopy()")
    expect(page.locator("#toasts")).to_contain_text("グラフ画像をクリップボードにコピーしました")
    # A result held on its way: the item is disabled until it is drawn.
    held: list[Route] = []
    hold = [True]
    page.route("**/api/plot", lambda route: held.append(route) if hold[0] else route.continue_())
    place_without_wait(page, "c", "color")
    page.wait_for_function("document.getElementById('plot').classList.contains('busy')")
    open_menu(page)
    expect(page.locator(".plot-menu .scale-menu-item", has_text="Copy graph image")).to_be_disabled()
    page.keyboard.press("Escape")
    hold[0] = False
    for route in held:
        route.continue_()
    wait_idle(page)
    open_menu(page)
    expect(page.locator(".plot-menu .scale-menu-item", has_text="Copy graph image")).to_be_enabled()


def place_without_wait(page: Page, column: str, role: str) -> None:
    """Drag a column onto a role's zone without waiting for the plot."""
    page.locator("#columns .column").filter(has=page.get_by_text(column, exact=True)).drag_to(
        page.locator(f'.zone[data-role="{role}"]')
    )


def test_no_figure_opens_no_menu(page: Page) -> None:
    """Without a figure, a right click on the plot area opens no plot menu."""
    stage = page.locator("#stage").bounding_box()
    page.mouse.click(stage["x"] + stage["width"] / 2, stage["y"] + stage["height"] / 2, button="right")
    expect(page.locator(".plot-menu")).to_have_count(0)
