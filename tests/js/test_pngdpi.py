"""JS: pngdpi.js writes the pHYs chunk of a DPI into a PNG, with its CRC."""

from __future__ import annotations

import struct
import zlib

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.js

# A canvas's PNG, with pHYs set by the module to `dpi`.
WITH_DPI = """async (dpi) => {
  const m = await import("/static/js/pngdpi.js");
  const canvas = document.createElement("canvas");
  canvas.width = 3;
  canvas.height = 2;
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  let bytes = new Uint8Array(await blob.arrayBuffer());
  // Twice: a pHYs already there is replaced, not doubled.
  bytes = m.withDpi(m.withDpi(bytes, 72), dpi);
  return Array.from(bytes);
}"""


def _chunks(png: bytes) -> list[tuple[bytes, bytes, int]]:
    """Return the chunks of `png` as (type, data, crc)."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    chunks = []
    at = 8
    while at < len(png):
        (length,) = struct.unpack(">I", png[at : at + 4])
        kind = png[at + 4 : at + 8]
        data = png[at + 8 : at + 8 + length]
        (crc,) = struct.unpack(">I", png[at + 8 + length : at + 12 + length])
        chunks.append((kind, data, crc))
        at += 12 + length
    return chunks


@pytest.mark.parametrize(("dpi", "ppm"), [(96, 3780), (300, 11811)])
def test_phys_holds_the_dpi_in_pixels_per_metre(js_page: Page, dpi: int, ppm: int) -> None:
    """The pHYs chunk follows IHDR, once, with round(dpi / 0.0254) both ways, the metre as unit, and a right CRC."""
    png = bytes(js_page.evaluate(WITH_DPI, dpi))
    chunks = _chunks(png)
    kinds = [kind for kind, _, _ in chunks]
    assert kinds[:2] == [b"IHDR", b"pHYs"]
    assert kinds.count(b"pHYs") == 1
    assert kinds[-1] == b"IEND"
    for kind, data, crc in chunks:
        assert zlib.crc32(kind + data) == crc
    _, data, _ = chunks[1]
    assert struct.unpack(">IIB", data) == (ppm, ppm, 1)


def test_the_png_still_decodes(js_page: Page) -> None:
    """The browser decodes the PNG with its pHYs to the same size."""
    size = js_page.evaluate(
        """async () => {
          const m = await import("/static/js/pngdpi.js");
          const canvas = document.createElement("canvas");
          canvas.width = 5;
          canvas.height = 4;
          const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
          const bytes = m.withDpi(new Uint8Array(await blob.arrayBuffer()), 300);
          const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
          return [bitmap.width, bitmap.height];
        }"""
    )
    assert size == [5, 4]


def test_bytes_that_are_not_a_png_are_refused(js_page: Page) -> None:
    """Bytes without the PNG signature, or cut inside a chunk, throw."""
    errors = js_page.evaluate(
        """async () => {
          const m = await import("/static/js/pngdpi.js");
          const tryIt = (bytes) => {
            try {
              m.withDpi(bytes, 96);
              return null;
            } catch (error) {
              return error.message;
            }
          };
          const signature = [137, 80, 78, 71, 13, 10, 26, 10];
          return [
            tryIt(new Uint8Array(40)),
            tryIt(new Uint8Array([...signature, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0])),
          ];
        }"""
    )
    assert all(errors)
