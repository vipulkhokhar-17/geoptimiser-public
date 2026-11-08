"""Bytes to text: charset detection with an explicit, bounded failure mode."""

import codecs
import re
from dataclasses import dataclass

_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
_HEADER_CHARSET = re.compile(r"charset\s*=\s*[\"']?([A-Za-z0-9_.:+-]+)", re.I)
_META_CHARSET = re.compile(
    rb"<meta[^>]{0,200}?charset\s*=\s*[\"']?([A-Za-z0-9_.:+-]+)", re.I
)
_SNIFF_BYTES = 4096
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})


class DecodeError(Exception):
    """The body cannot be turned into text that is worth parsing."""


@dataclass(frozen=True)
class DecodedHtml:
    text: str
    encoding: str


def media_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def _usable(label: str) -> str | None:
    """The canonical codec name if ``label`` is a known *text* encoding."""
    try:
        name = codecs.lookup(label).name
        b"a".decode(name, "replace")  # bytes-to-bytes codecs (hex, zlib) raise
    except (LookupError, TypeError):
        return None
    return name


def detect_encoding(data: bytes, content_type: str | None) -> str:
    """Pick an encoding: BOM, then HTTP header, then ``<meta charset>``, else UTF-8.

    An unknown or non-text label is ignored (the next source is tried), as a
    browser would, so an odd label never blocks extraction by itself.
    """
    for bom, name in _BOMS:
        if data.startswith(bom):
            return name
    header = _HEADER_CHARSET.search(content_type or "")
    if header and (name := _usable(header.group(1))):
        return name
    meta = _META_CHARSET.search(data[:_SNIFF_BYTES])
    if meta and (name := _usable(meta.group(1).decode("ascii", "replace"))):
        return name
    return "utf-8"


def decode_html(
    data: bytes, content_type: str | None, *, max_replacement_ratio: float
) -> DecodedHtml:
    """Decode with replacement, but fail if the result is mostly undecodable."""
    encoding = detect_encoding(data, content_type)
    try:
        text = data.decode(encoding, errors="replace")
    except Exception as exc:  # noqa: BLE001 - e.g. a malformed UTF-16 stream
        raise DecodeError(f"cannot decode as {encoding}: {type(exc).__name__}") from exc
    if text and text.count("�") / len(text) > max_replacement_ratio:
        raise DecodeError(
            f"over {max_replacement_ratio:.0%} of the text is undecodable as {encoding}"
        )
    return DecodedHtml(text=text, encoding=encoding)
