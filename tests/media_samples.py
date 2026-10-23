"""Tiny generated media for tests. Never real screenshots."""

from __future__ import annotations

import struct
import zlib


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png(*, text: bytes | None = None, colour: int = 0) -> bytes:
    """A 1x1 greyscale PNG, optionally carrying a tEXt chunk."""
    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    pixels = zlib.compress(bytes([0, colour]))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + (_png_chunk(b"tEXt", text) if text is not None else b"")
        + _png_chunk(b"IDAT", pixels)
        + _png_chunk(b"IEND", b"")
    )
