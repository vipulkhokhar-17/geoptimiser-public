import codecs

import pytest

from geoptimiser.extraction.decode import (
    DecodeError,
    decode_html,
    detect_encoding,
    media_type,
)


def decode(data: bytes, content_type: str | None = None) -> tuple[str, str]:
    result = decode_html(data, content_type, max_replacement_ratio=0.1)
    return result.text, result.encoding


def test_default_is_utf8() -> None:
    assert decode("café".encode()) == ("café", "utf-8")


def test_http_charset_is_used() -> None:
    assert decode("café".encode("latin-1"), "text/html; charset=ISO-8859-1") == (
        "café",
        "iso8859-1",
    )


def test_meta_charset_is_used_when_the_header_has_none() -> None:
    data = b'<meta charset="windows-1252"><p>caf\xe9</p>'
    text, encoding = decode(data, "text/html")
    assert "café" in text and encoding == "cp1252"


def test_http_header_beats_meta() -> None:
    data = b'<meta charset="windows-1252">caf\xc3\xa9'
    assert decode(data, "text/html; charset=utf-8")[0].endswith("café")


@pytest.mark.parametrize(
    ("bom", "expected"),
    [
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF32_LE, "utf-32"),
    ],
)
def test_bom_wins_over_everything(bom: bytes, expected: str) -> None:
    assert detect_encoding(bom + b"x", "text/html; charset=latin-1") == expected


def test_utf8_bom_is_removed_from_the_text() -> None:
    assert decode(codecs.BOM_UTF8 + b"<p>x</p>")[0] == "<p>x</p>"


@pytest.mark.parametrize("label", ["not-a-charset", "zlib", "hex", "rot13"])
def test_unknown_or_non_text_labels_fall_back_to_utf8(label: str) -> None:
    assert detect_encoding(b"<p>x</p>", f"text/html; charset={label}") == "utf-8"


def test_a_few_bad_bytes_are_replaced_not_fatal() -> None:
    text, _ = decode(b"<p>" + b"valid text " * 50 + b"\xff</p>")
    assert "�" in text


def test_mostly_undecodable_text_is_a_decode_error() -> None:
    with pytest.raises(DecodeError, match="undecodable"):
        decode(b"\xff\xfe\xfd" * 100, "text/html; charset=utf-8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("text/html; charset=utf-8", "text/html"),
        ("TEXT/HTML", "text/html"),
        (" application/xhtml+xml ;x=y", "application/xhtml+xml"),
        ("", ""),
        (None, ""),
    ],
)
def test_media_type(value: str | None, expected: str) -> None:
    assert media_type(value) == expected
