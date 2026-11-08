import pytest

from geoptimiser.crawler.urls import extract_links, host_in_scope, normalize_url


@pytest.mark.parametrize(
    ("host", "domain", "expected"),
    [
        ("example.com", "example.com", True),
        ("www.example.com", "example.com", True),
        ("docs.example.com", "www.example.com", True),
        ("example.com", "www.example.com", True),
        ("EXAMPLE.com.", "example.com", True),
        ("evilexample.com", "example.com", False),
        ("example.com.evil.com", "example.com", False),
        ("other.org", "example.com", False),
    ],
)
def test_host_in_scope(host: str, domain: str, expected: bool) -> None:
    assert host_in_scope(host, domain) is expected


def norm(url: str, **kw: object) -> str | None:
    return normalize_url(url, max_length=2048, follow_query=bool(kw.get("q")))


def test_normalization_drops_fragment_and_default_port_and_lowercases_host() -> None:
    assert norm("HTTPS://Example.COM:443/a#frag") == "https://example.com/a"
    assert norm("http://example.com:8080") == "http://example.com:8080/"


@pytest.mark.parametrize(
    "url",
    [
        "mailto:a@b.com",
        "javascript:alert(1)",
        "ftp://example.com/",
        "https://user:pw@example.com/",
        "https://example.com/report.PDF",
        "https://example.com/img/logo.png",
        "https://example.com/?page=2",
        "https://example.com/" + "a" * 3000,
        "https://example.com:notaport/",
    ],
)
def test_uncrawlable_urls_are_rejected(url: str) -> None:
    assert norm(url) is None


def test_query_strings_allowed_when_configured() -> None:
    assert norm("https://example.com/?page=2", q=True) == "https://example.com/?page=2"


def test_extract_links_resolves_relative_and_skips_non_anchor() -> None:
    html = (
        '<a href="/a">1</a><link href="/css"><a href=" b ">2</a>'
        '<a name="x">3</a><a href="">4</a><a href="https://x.org/">5</a>'
    )
    assert extract_links(html, "https://e.com/dir/", limit=10) == [
        "https://e.com/a",
        "https://e.com/dir/b",
        "https://x.org/",
    ]


def test_extract_links_is_bounded_and_survives_malformed_html() -> None:
    html = "<a href=/1><a href=/2><a href=/3>" + "<<<>>" * 100 + '<a href="/4'
    assert len(extract_links(html, "https://e.com/", limit=2)) == 2
    assert extract_links("\x00<a", "https://e.com/", limit=5) == []
