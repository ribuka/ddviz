"""JS: plotimage.js sizes, makes and copies the graph image, with the clipboard replaced.

These tests replace `navigator.clipboard` and `ClipboardItem` (the blank page
is not a secure context) and plotly's `toImage`: they check what the page
hands the clipboard, not that the OS's clipboard gets it (`tests/e2e`, and the
WebView2 check in `docs/spec.md`, "グラフ画像のコピー").
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page

from .conftest import open_blank

pytestmark = pytest.mark.js

# A copy over a fake plot of `width` × `height` CSS px without panels or
# legend. plotly's SVG (`toImage`) has a red square under the layers and a
# blue one over them, at (10, 10) and (50, 10) of the figure, 20 px wide.
# `window.harness(options)` returns `{copy, toasts, writes, made, canvases}`:
# the toasts shown, the items written, the times `toImage` ran and the
# canvases made.
HARNESS = """
window.harness = async ({
  width = 200,
  height = 100,
  dpi = 300,
  ready = true,
  clipboard = "ok",
  toImage = "ok",
  item = true,
} = {}) => {
  const m = await import("/static/js/plotimage.js");
  const toasts = [];
  const writes = [];
  const made = { toImage: 0 };
  const canvases = [];
  const create = document.createElement.bind(document);
  document.createElement = (tag, ...rest) => {
    const element = create(tag, ...rest);
    if (tag === "canvas") canvases.push(element);
    return element;
  };
  let release;
  const held = new Promise((resolve) => (release = resolve));
  const write = async (items) => {
    const blobs = [];
    for (const it of items) for (const type of it.types) blobs.push([type, await it.getType(type)]);
    if (clipboard === "denied") throw new DOMException("Write permission denied.", "NotAllowedError");
    if (clipboard === "fail") throw new Error("書き込みの失敗");
    if (clipboard === "held") await held;
    writes.push(...blobs);
  };
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: clipboard === "none" ? undefined : { write },
  });
  window.ClipboardItem = item
    ? class {
        constructor(data) {
          this.data = data;
        }
        get types() {
          return Object.keys(this.data);
        }
        getType(type) {
          return Promise.resolve(this.data[type]);
        }
      }
    : undefined;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">` +
    '<defs/><rect x="10" y="10" width="20" height="20" fill="#f00"/>' +
    '<defs/><rect x="50" y="10" width="20" height="20" fill="#00f"/></svg>';
  const fakeToImage = async () => {
    made.toImage++;
    if (toImage === "fail") throw new Error("SVG の失敗");
    return `data:image/svg+xml,${encodeURIComponent(svg)}`;
  };
  const gd = {
    _fullLayout: { width, height, font: { family: "sans-serif", color: "#444" } },
    layout: { width, height },
    data: [],
    querySelector: () => null,
  };
  const meta = {
    panels: [], ncol: 1, x_columns: [], y_columns: [], scroll: false,
    facet_labels: [], wrap_column: null, one_band: false,
  };
  const legend = { entries: () => [] };
  const copier = new m.PlotImageCopy({
    capture: () => ({ gd, meta, layers: { meta: null, bitmaps: null, selection: null, legend }, legend }),
    ready: () => ready,
    dpi: () => dpi,
    toasts: { show: (text, kind = "error") => toasts.push([kind, text]) },
    toImage: fakeToImage,
  });
  return { m, copier, toasts, writes, made, canvases, release, restore: () => (document.createElement = create) };
};

// Returns the RGBA of pixel (x, y) of a PNG blob, and its size.
window.pixels = async (blob, points) => {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0);
  return {
    size: [bitmap.width, bitmap.height],
    at: points.map(([x, y]) => Array.from(ctx.getImageData(x, y, 1, 1).data)),
  };
};
"""

PAD = 16
NAME_BAND = 22


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    """Return a blank page of the test's own, whose clipboard and `createElement` it may replace."""
    page = open_blank(browser.new_page())
    page.add_script_tag(content=HARNESS)
    yield page
    page.close()


def _size(width: float, height: float, dpi: int) -> list[int]:
    """Return the PNG's size of a fake plot of `width` × `height` without a legend."""
    logical_w = PAD + NAME_BAND + width + PAD
    logical_h = PAD + height + NAME_BAND + PAD
    return [math.ceil(logical_w * dpi / 96), math.ceil(logical_h * dpi / 96)]


@pytest.mark.parametrize("dpi", [96, 300])
def test_the_copy_is_a_png_of_the_dpi_on_white(page: Page, dpi: int) -> None:
    """The PNG is ceil(W·dpi/96) × ceil(H·dpi/96), opaque white, the SVG under and over at their places; one success toast after the write."""
    result = page.evaluate(
        """async (dpi) => {
          const h = await harness({ dpi });
          const ok = await h.copier.copy();
          const [[type, blob]] = h.writes;
          const k = dpi / 96;
          const fig = [38, 16];
          const at = (x, y) => [Math.floor((fig[0] + x) * k), Math.floor((fig[1] + y) * k)];
          const px = await pixels(blob, [[0, 0], at(20, 20), at(60, 20), at(150, 80)]);
          return { ok, type, blobType: blob.type, ...px, toasts: h.toasts, running: h.copier.running };
        }""",
        dpi,
    )
    assert result["ok"] is True
    assert result["type"] == result["blobType"] == "image/png"
    assert result["size"] == _size(200, 100, dpi)
    white, red, blue, inside = result["at"]
    assert white == [255, 255, 255, 255]
    assert red == [255, 0, 0, 255]
    assert blue == [0, 0, 255, 255]
    assert inside == [255, 255, 255, 255]
    assert result["toasts"] == [["success", "グラフ画像をクリップボードにコピーしました"]]
    assert result["running"] is False


def test_the_size_does_not_follow_the_device_pixel_ratio(page: Page) -> None:
    """A device pixel ratio of 2 gives the same PNG size as 1."""
    sizes = page.evaluate(
        """async () => {
          const sizes = [];
          for (const ratio of [1, 2]) {
            Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: ratio });
            const h = await harness({ dpi: 300 });
            await h.copier.copy();
            h.restore();
            sizes.push((await pixels(h.writes[0][1], [])).size);
          }
          return sizes;
        }"""
    )
    assert sizes[0] == sizes[1] == _size(200, 100, 300)


def test_the_png_has_the_dpi_in_its_phys(page: Page) -> None:
    """The copied PNG's pHYs holds the DPI's pixels per metre."""
    ppm = page.evaluate(
        """async () => {
          const h = await harness({ dpi: 96 });
          await h.copier.copy();
          const bytes = new Uint8Array(await h.writes[0][1].arrayBuffer());
          const view = new DataView(bytes.buffer);
          // The signature, IHDR (25 bytes), then pHYs.
          const at = 8 + 25;
          return [String.fromCharCode(...bytes.subarray(at + 4, at + 8)), view.getUint32(at + 8), bytes[at + 16]];
        }"""
    )
    assert ppm == ["pHYs", 3780, 1]


@pytest.mark.parametrize(
    ("size", "fails"),
    [
        ((32767, 1000), False),
        ((32768, 1000), True),
        ((1000, 32767), False),
        ((1000, 32768), True),
        ((8000, 8000), False),
        ((8000, 8001), True),
        ((16000, 4000), False),
        ((16000, 4001), True),
    ],
)
def test_the_limits_of_a_side_and_the_area(js_page: Page, size: tuple[int, int], fails: bool) -> None:
    """A side up to 32,767 px and an area up to 64,000,000 px pass; one more fails."""
    error = js_page.evaluate(
        """async ([width, height]) => {
          const m = await import("/static/js/plotimage.js");
          return m.sizeError({ width, height }, 300);
        }""",
        list(size),
    )
    assert (error is not None) == fails


def test_the_limits_advise_by_the_dpi(js_page: Page) -> None:
    """At 300 DPI the advice names the setting and the panels; at 96, the panels only."""
    advice = js_page.evaluate(
        """async () => {
          const m = await import("/static/js/plotimage.js");
          return [m.sizeError({ width: 40000, height: 10 }, 300), m.sizeError({ width: 40000, height: 10 }, 96)];
        }"""
    )
    assert "40000 × 10 px、300 DPI" in advice[0]
    assert "Preferences… でグラフ画像のコピーの解像度を 96 DPI にするか、パネル数を減らしてください" in advice[0]
    assert "96 DPI" in advice[1]
    assert "plot.image_copy.dpi" not in advice[1]
    assert advice[1].endswith("パネル数を減らしてください")


def test_too_large_an_image_fails_before_any_canvas(page: Page) -> None:
    """Past the limits: an error toast with the size, no output canvas, no SVG, no write, and no lower DPI."""
    result = page.evaluate(
        """async () => {
          const h = await harness({ width: 11000, height: 100, dpi: 300 });
          const ok = await h.copier.copy();
          return {
            ok, toasts: h.toasts, writes: h.writes.length, svg: h.made.toImage,
            widest: Math.max(0, ...h.canvases.map((c) => c.width)), running: h.copier.running,
          };
        }"""
    )
    assert result["ok"] is False
    assert result["writes"] == 0
    assert result["svg"] == 0
    assert result["widest"] <= 300
    assert result["running"] is False
    [(kind, text)] = result["toasts"]
    assert kind == "error"
    assert text.startswith("グラフ画像をコピーできませんでした：画像が大きすぎます（34544 × 482 px")
    assert "300 DPI" in text


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"clipboard": "none"}, "対応していません"),
        ({"item": False}, "対応していません"),
        ({"clipboard": "denied"}, "許可されませんでした"),
        ({"clipboard": "fail"}, "書き込みの失敗"),
        ({"toImage": "fail"}, "SVG の失敗"),
    ],
)
def test_failures_toast_their_reason_and_clean_up(page: Page, options: dict, reason: str) -> None:
    """No API, a refused or failed write, and a failed image: one error toast with the reason, nothing written, the canvas freed, no rejection left."""
    result = page.evaluate(
        """async (options) => {
          const rejections = [];
          addEventListener("unhandledrejection", (event) => rejections.push(String(event.reason)));
          const h = await harness(options);
          const ok = await h.copier.copy();
          await new Promise((resolve) => setTimeout(resolve, 50));
          return {
            ok, toasts: h.toasts, writes: h.writes.length, running: h.copier.running,
            available: h.copier.available(), rejections,
            sizes: h.canvases.map((c) => c.width * c.height),
          };
        }""",
        options,
    )
    assert result["ok"] is False
    assert result["writes"] == 0
    assert result["running"] is False
    assert result["available"] is True
    assert result["rejections"] == []
    [(kind, text)] = result["toasts"]
    assert kind == "error"
    assert text.startswith("グラフ画像をコピーできませんでした：")
    assert reason in text
    # The output canvas, if made, is emptied; the measuring one is 300 × 150.
    assert all(size in (0, 300 * 150) for size in result["sizes"])


def test_one_copy_at_a_time_and_the_toast_after_the_write(page: Page) -> None:
    """While a copy runs the item is unavailable and a second copy does nothing; the success toast waits for the write."""
    result = page.evaluate(
        """async () => {
          const h = await harness({ clipboard: "held" });
          const first = h.copier.copy();
          const during = [h.copier.running, h.copier.available()];
          const second = await h.copier.copy();
          await new Promise((resolve) => setTimeout(resolve, 100));
          const toastsBefore = h.toasts.length;
          h.release();
          const ok = await first;
          return {
            during, second, toastsBefore, ok, toasts: h.toasts, svg: h.made.toImage,
            after: [h.copier.running, h.copier.available()],
          };
        }"""
    )
    assert result["during"] == [True, False]
    assert result["second"] is False
    assert result["toastsBefore"] == 0
    assert result["ok"] is True
    assert result["svg"] == 1
    assert [kind for kind, _ in result["toasts"]] == ["success"]
    assert result["after"] == [False, True]


def test_an_unsettled_figure_or_no_setting_is_not_copied(page: Page) -> None:
    """While the figure is not ready, or before the DPI comes, the copy is unavailable and does nothing."""
    result = page.evaluate(
        """async () => {
          const busy = await harness({ ready: false });
          const none = await harness({ dpi: null });
          return [busy.copier.available(), await busy.copier.copy(), none.copier.available(), await none.copier.copy(),
                  busy.toasts.length + none.toasts.length, busy.made.toImage + none.made.toImage];
        }"""
    )
    assert result == [False, False, False, False, 0, 0]


def test_axis_names_span_the_panels_of_their_column(js_page: Page) -> None:
    """Each x column is named once under the panel columns it spans, each y column left of its panel rows; the one band has no x name."""
    names = js_page.evaluate(
        """async () => {
          const m = await import("/static/js/plotimage.js");
          const axis = (offset, length) => ({ _offset: offset, _length: length });
          const full = {
            xaxis: axis(50, 100), xaxis2: axis(151, 100), xaxis3: axis(252, 100), xaxis4: axis(353, 100),
            yaxis: axis(10, 80), yaxis2: axis(10, 80), yaxis3: axis(10, 80), yaxis4: axis(10, 80),
          };
          const panel = (n, x) => ({ xaxis: n === 1 ? "x" : `x${n}`, yaxis: n === 1 ? "y" : `y${n}`, x, y: 0 });
          const meta = {
            panels: [panel(1, 0), panel(2, 0), panel(3, 1), panel(4, 1)],
            ncol: 4, x_columns: ["a", "b"], y_columns: ["v"], one_band: false,
          };
          return [m.axisNames(full, meta), m.axisNames(full, { ...meta, one_band: true })];
        }"""
    )
    assert names[0] == [
        {"role": "x", "text": "a", "from": 50, "to": 251},
        {"role": "x", "text": "b", "from": 252, "to": 453},
        {"role": "y", "text": "v", "from": 10, "to": 90},
    ]
    assert names[1] == [{"role": "y", "text": "v", "from": 10, "to": 90}]
