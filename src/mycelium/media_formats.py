"""Which bytes count as media, and the same bytes without their metadata.

The type comes from the bytes, never from a file name or a declared type, and
only raster images and two video containers qualify: nothing that can carry
script (SVG, HTML, PDF) has a signature here. Stripping walks the container's
own structure and drops what describes the capture rather than the picture:
EXIF (with its GPS block), XMP, comments and text chunks. A file whose
structure does not parse is refused rather than passed through.

Video is stripped in place, so the sample offsets a container records stay
valid: an MP4 metadata box becomes a `free` box of the same size, a WebM
metadata element a `Void` element of the same size.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Kind = Literal["png", "jpeg", "gif", "webp", "mp4", "webm"]

CONTENT_TYPES: dict[Kind, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
}
EXTENSIONS: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/webm": "webm",
}
VIDEO: frozenset[Kind] = frozenset({"mp4", "webm"})


class Rejected(ValueError):
    """The bytes are not media Mycelium accepts."""


@dataclass(frozen=True)
class Cleaned:
    kind: Kind
    data: bytes

    @property
    def content_type(self) -> str:
        return CONTENT_TYPES[self.kind]

    @property
    def is_video(self) -> bool:
        return self.kind in VIDEO


_MP4_BRANDS = frozenset(
    {b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash"}
)


def sniff(data: bytes) -> Kind | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in _MP4_BRANDS:
        return "mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3") and b"\x42\x82\x84webm" in data[:64]:
        return "webm"
    return None


def clean(data: bytes) -> Cleaned:
    """The media in `data`, metadata removed. Raises `Rejected`."""
    kind = sniff(data)
    if kind is None:
        raise Rejected(
            "Unsupported file: upload a PNG, JPEG, WebP or GIF image, or an "
            "MP4 or WebM video."
        )
    try:
        return Cleaned(kind, _STRIPPERS[kind](data))
    except (IndexError, struct.error, ValueError) as exc:
        raise Rejected(f"The {kind.upper()} file is damaged: {exc}") from None


# --- PNG ---------------------------------------------------------------------

#: Chunks that draw the picture; text, time and EXIF chunks are dropped.
_PNG_KEEP = frozenset(
    {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"gAMA",
        b"cHRM",
        b"sRGB",
        b"iCCP",
        b"sBIT",
        b"bKGD",
        b"pHYs",
        b"acTL",
        b"fcTL",
        b"fdAT",
    }
)


def _png(data: bytes) -> bytes:
    out = bytearray(data[:8])
    pos = 8
    first = True
    while True:
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("a chunk runs past the end of the file")
        if first and kind != b"IHDR":
            raise ValueError("the header chunk is missing")
        first = False
        if kind in _PNG_KEEP:
            out += data[pos:end]
        pos = end
        if kind == b"IEND":
            return bytes(out)


# --- JPEG --------------------------------------------------------------------


def _jpeg(data: bytes) -> bytes:
    out = bytearray(b"\xff\xd8")
    pos = 2
    while True:
        if data[pos] != 0xFF:
            raise ValueError("expected a segment marker")
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker == 0xD9:
            out += b"\xff\xd9"
            return bytes(out)
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[pos : pos + 2]
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        end = pos + 2 + length
        if length < 2 or end > len(data):
            raise ValueError("a segment runs past the end of the file")
        segment = data[pos:end]
        if marker == 0xDA:
            # The scan's entropy-coded data runs to the end; nothing that
            # describes the capture follows it.
            out += data[pos:]
            return bytes(out)
        if _jpeg_keeps(marker, segment[4:]):
            out += segment
        pos = end


def _jpeg_keeps(marker: int, payload: bytes) -> bool:
    if marker == 0xFE:
        return False
    if 0xE0 <= marker <= 0xEF:
        # JFIF, the ICC colour profile and Adobe's colour transform change how
        # the picture decodes; EXIF, XMP and the rest only describe it.
        return (
            (marker == 0xE0 and payload.startswith(b"JFIF\x00"))
            or (marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"))
            or (marker == 0xEE and payload.startswith(b"Adobe"))
        )
    return True


# --- GIF ---------------------------------------------------------------------

_GIF_LOOPING = (b"NETSCAPE2.0", b"ANIMEXTS1.0")


def _gif(data: bytes) -> bytes:
    flags = data[10]
    pos = 13 + (3 * 2 ** ((flags & 0x07) + 1) if flags & 0x80 else 0)
    out = bytearray(data[:pos])
    while True:
        introducer = data[pos]
        if introducer == 0x3B:
            out += b"\x3b"
            return bytes(out)
        if introducer == 0x21:
            label = data[pos + 1]
            end = _gif_sub_blocks(data, pos + 2)
            # The graphic control extension times frames; an application
            # extension is kept only when it loops the animation.
            if label == 0xF9 or (
                label == 0xFF and data[pos + 3 : pos + 14] in _GIF_LOOPING
            ):
                out += data[pos:end]
            pos = end
            continue
        if introducer == 0x2C:
            local = data[pos + 9]
            start = pos + 10 + (3 * 2 ** ((local & 0x07) + 1) if local & 0x80 else 0)
            end = _gif_sub_blocks(data, start + 1)
            out += data[pos:end]
            pos = end
            continue
        raise ValueError(f"unexpected block {introducer:#04x}")


def _gif_sub_blocks(data: bytes, pos: int) -> int:
    while True:
        size = data[pos]
        pos += 1 + size
        if size == 0:
            if pos > len(data):
                raise ValueError("a block runs past the end of the file")
            return pos


# --- WebP --------------------------------------------------------------------

_WEBP_DROP = frozenset({b"EXIF", b"XMP "})
_VP8X_EXIF = 0x08
_VP8X_XMP = 0x04


def _webp(data: bytes) -> bytes:
    (size,) = struct.unpack("<I", data[4:8])
    if size + 8 > len(data):
        raise ValueError("the file is shorter than its header says")
    chunks = bytearray()
    pos = 12
    while pos < size + 8:
        kind = data[pos : pos + 4]
        (length,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        end = pos + 8 + length + (length & 1)
        if end > size + 8:
            raise ValueError("a chunk runs past the end of the file")
        chunk = bytearray(data[pos:end])
        if kind == b"VP8X":
            chunk[8] &= ~(_VP8X_EXIF | _VP8X_XMP) & 0xFF
        if kind not in _WEBP_DROP:
            chunks += chunk
        pos = end
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WEBP" + bytes(chunks)


# --- MP4 ---------------------------------------------------------------------

_MP4_CONTAINERS = frozenset({b"moov", b"trak", b"mdia", b"minf"})
_MP4_METADATA = frozenset({b"udta", b"meta", b"uuid"})


def _mp4(data: bytes) -> bytes:
    out = bytearray(data)
    _mp4_boxes(out, 0, len(out))
    return bytes(out)


def _mp4_boxes(out: bytearray, pos: int, end: int) -> None:
    while pos < end:
        (size,) = struct.unpack(">I", out[pos : pos + 4])
        kind = bytes(out[pos + 4 : pos + 8])
        header = 8
        if size == 1:
            (size,) = struct.unpack(">Q", out[pos + 8 : pos + 16])
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise ValueError("a box runs past the end of its container")
        if kind in _MP4_METADATA:
            out[pos + 4 : pos + 8] = b"free"
            out[pos + header : pos + size] = bytes(size - header)
        elif kind in _MP4_CONTAINERS:
            _mp4_boxes(out, pos + header, pos + size)
        pos += size


# --- WebM --------------------------------------------------------------------

_EBML_SEGMENT = 0x18538067
_EBML_INFO = 0x1549A966
#: Tags, Attachments (files riding along), and Info's Title and DateUTC.
_EBML_METADATA = frozenset({0x1254C367, 0x1941A469, 0x7BA9, 0x4461})
_EBML_VOID = 0xEC


def _webm(data: bytes) -> bytes:
    out = bytearray(data)
    pos = 0
    while pos < len(out):
        element, start, size = _ebml_element(out, pos)
        if element == _EBML_SEGMENT:
            _webm_children(out, start, len(out) if size is None else start + size)
            return bytes(out)
        if size is None:
            raise ValueError("an element before the segment has no size")
        pos = start + size
    raise ValueError("the file holds no segment")


def _webm_children(out: bytearray, pos: int, end: int) -> None:
    while pos < end:
        element, start, size = _ebml_element(out, pos)
        # Clusters of a recording often have no size, and nothing is read
        # past the first one that cannot be skipped.
        if size is None:
            return
        if start + size > end:
            raise ValueError("an element runs past the end of its parent")
        if element in _EBML_METADATA:
            _ebml_void(out, pos, start + size)
        elif element == _EBML_INFO:
            _webm_children(out, start, start + size)
        pos = start + size


def _ebml_element(out: bytearray, pos: int) -> tuple[int, int, int | None]:
    """An element's id, where its data starts and its size (None: unknown)."""
    first = out[pos]
    width = _vint_width(first, 4)
    element = int.from_bytes(out[pos : pos + width], "big")
    pos += width
    size_width = _vint_width(out[pos], 8)
    value = int.from_bytes(out[pos : pos + size_width], "big")
    value &= (1 << (7 * size_width)) - 1
    unknown = value == (1 << (7 * size_width)) - 1
    return element, pos + size_width, None if unknown else value


def _vint_width(first: int, limit: int) -> int:
    for width in range(1, limit + 1):
        if first & (0x80 >> (width - 1)):
            return width
    raise ValueError("an element has an invalid length")


def _ebml_void(out: bytearray, pos: int, end: int) -> None:
    total = end - pos
    if total >= 9:
        size = (1 << 56) | (total - 9)
        out[pos:end] = bytes([_EBML_VOID]) + size.to_bytes(8, "big") + bytes(total - 9)
    else:
        out[pos:end] = bytes([_EBML_VOID, 0x80 | (total - 2)]) + bytes(total - 2)


_STRIPPERS: dict[Kind, Callable[[bytes], bytes]] = {
    "png": _png,
    "jpeg": _jpeg,
    "gif": _gif,
    "webp": _webp,
    "mp4": _mp4,
    "webm": _webm,
}
