"""Tests of the 1-bit mask PNG encoder."""

from __future__ import annotations

import struct
import zlib

import numpy as np

from ddviz.png import encode_mask


def _chunks(data: bytes) -> dict[bytes, bytes]:
    """Split a PNG into its chunks by type, checking each CRC."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, pos = {}, 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + body)
        chunks[kind] = chunks.get(kind, b"") + body
        pos += 12 + length
    return chunks


def test_encode_mask_round_trips_bits_and_color() -> None:
    """The pixels decode back to the mask, with a transparent and a colored palette entry."""
    rng = np.random.default_rng(1)
    mask = rng.random((7, 13)) < 0.3
    chunks = _chunks(encode_mask(mask, "#1f77b4"))

    width, height, depth, color_type = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (width, height, depth, color_type) == (13, 7, 1, 3)
    assert chunks[b"PLTE"] == bytes([0, 0, 0, 0x1F, 0x77, 0xB4])
    assert chunks[b"tRNS"] == b"\x00\xff"
    raw = np.frombuffer(zlib.decompress(chunks[b"IDAT"]), np.uint8).reshape(7, -1)
    assert (raw[:, 0] == 0).all()
    assert (np.unpackbits(raw[:, 1:], axis=1)[:, :13].astype(bool) == mask).all()
