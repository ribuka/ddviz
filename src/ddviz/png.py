"""Minimal PNG encoder for one-color masks."""

from __future__ import annotations

import struct
import zlib

import numpy as np

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    """Return one PNG chunk with its length and CRC."""
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


def encode_mask(mask: np.ndarray, color: str, level: int = 1) -> bytes:
    """Encode a mask as a 1-bit palette PNG: transparent where False, `color` where True.

    Parameters
    ----------
    mask : numpy.ndarray
        Boolean array of shape ``(height, width)``; row 0 becomes the first row of the image.
    color : str
        Color as ``#rrggbb``.
    level : int
        zlib compression level.

    Returns
    -------
    bytes
        The PNG file.
    """
    height, width = mask.shape
    rgb = bytes.fromhex(color.removeprefix("#"))
    packed = np.packbits(mask.astype(bool), axis=1)
    raw = np.hstack([np.zeros((height, 1), np.uint8), packed]).tobytes()
    return (
        _SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 3, 0, 0, 0))
        + _chunk(b"PLTE", b"\x00\x00\x00" + rgb)
        + _chunk(b"tRNS", b"\x00\xff")
        + _chunk(b"IDAT", zlib.compress(raw, level))
        + _chunk(b"IEND", b"")
    )
