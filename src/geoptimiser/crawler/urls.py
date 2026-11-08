"""URL scope, normalization and link discovery for the crawler.

Link discovery here only finds ``<a href>`` targets so the crawl can continue.
It is not content extraction (Stage 02): page text, headings and metadata are
not read.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

_SKIPPED_EXTENSIONS = frozenset(
    ".pdf .zip .gz .tar .rar .7z .exe .dmg .iso .png .jpg .jpeg .gif .webp .svg "
    ".ico .bmp .mp3 .mp4 .avi .mov .wav .woff .woff2 .ttf .css .js .json .xml "
    ".doc .docx .xls .xlsx .ppt .pptx".split()
)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def scope_base(domain: str) -> str:
    """The audited site's base: the target domain without a leading ``www.``."""
    return domain.removeprefix("www.")


def host_in_scope(host: str, domain: str) -> bool:
    """True for the target domain, its ``www`` form, and its subdomains."""
    base = scope_base(domain)
    host = host.lower().rstrip(".")
    return host == base or host.endswith("." + base)


_ASCII_HOST = re.compile(r"^[a-z0-9.-]+$")


def normalize_url(url: str, *, max_length: int, follow_query: bool) -> str | None:
    """Return a canonical crawl key for ``url``, or ``None`` if it is not crawlable."""
    if len(url) > max_length:
        return None
    parts = urlsplit(url)
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    # The fetcher re-parses keys with a WHATWG parser (pydantic HttpUrl), which reads a
    # backslash in the authority as "/". urlsplit does not, so "http://evil.com\\.x.example.com/"
    # would pass the scope check here and then connect to evil.com. Refuse any authority
    # the two parsers could read differently (security audit run 1, scope differential).
    if "\\" in parts.netloc or "%" in parts.netloc:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if parts.query and not follow_query:
        return None
    path = parts.path or "/"
    if "." in path.rsplit("/", 1)[-1]:
        ext = "." + path.rsplit(".", 1)[-1].lower()
        if ext in _SKIPPED_EXTENSIONS:
            return None
    try:
        port = parts.port
    except ValueError:
        return None
    netloc = parts.hostname.lower()
    if ":" not in netloc:
        # Canonical ASCII host (IDNA), so the scope check sees the same name the fetcher
        # will connect to; any other character than letters, digits, dots and hyphens
        # is refused.
        try:
            netloc = netloc.encode("idna").decode("ascii")
        except UnicodeError:
            return None
        if not _ASCII_HOST.match(netloc):
            return None
    else:
        netloc = f"[{netloc}]"
    if port and port != _DEFAULT_PORTS[parts.scheme]:
        netloc += f":{port}"
    return urlunsplit((parts.scheme, netloc, path, parts.query, ""))


# Containers whose anchors are not links a non-scripting client can follow: the
# content of <template> is inert, and <svg>/<math> are foreign content. Anchors in
# <noscript> *are* links: the crawler does not run scripts, so the browser's
# "scripting disabled" parse is the one that applies. The extractor imports these
# rules so that crawling and extraction agree on what a link is (docs/validation).
INERT_LINK_CONTAINERS = frozenset({"template", "svg", "math"})


def clean_href(raw: str) -> str | None:
    """The href as a browser would read it, or ``None`` if it names no new page.

    Surrounding whitespace is dropped, tabs/newlines inside are removed, inner spaces
    are escaped, and an empty or fragment-only value is not a link.
    """
    href = raw.strip()
    if not href or href.startswith("#"):
        return None
    return href.translate({9: None, 10: None, 13: None}).replace(" ", "%20")


def resolve_link(base_url: str, raw: str) -> str | None:
    """Absolute, fragment-free http(s) URL for an ``href``, or ``None``."""
    href = clean_href(raw)
    if href is None:
        return None
    url = urldefrag(urljoin(base_url, href))[0]
    parts = urlsplit(url)
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    return url


def resolve_base(page_url: str, raw: str) -> str | None:
    """The document base URL declared by ``<base href>``, if it is http(s)."""
    resolved = urljoin(page_url, raw.strip())
    return resolved if urlsplit(resolved).scheme in _DEFAULT_PORTS else None


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self._base = base_url
        self._base_set = False
        self._limit = limit
        self._inert_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in INERT_LINK_CONTAINERS:
            self._inert_depth += 1
            return
        if tag == "base" and not self._base_set:
            for name, value in attrs:
                if name == "href" and value:
                    resolved = resolve_base(self._base, value)
                    if resolved:
                        self._base, self._base_set = resolved, True
                    break
            return
        if tag != "a" or self._inert_depth or len(self.links) >= self._limit:
            return
        for name, value in attrs:
            if name == "href" and value is not None:
                url = resolve_link(self._base, value)
                if url:
                    self.links.append(url)
                return

    def handle_endtag(self, tag: str) -> None:
        if tag in INERT_LINK_CONTAINERS and self._inert_depth:
            self._inert_depth -= 1


def extract_links(html: str, base_url: str, *, limit: int) -> list[str]:
    """Absolute ``<a href>`` targets in document order (at most ``limit``).

    Untrusted markup is only tokenized, never executed. Malformed HTML yields
    whatever links the tolerant parser could read. ``<base href>`` is honoured and
    anchors inside ``<noscript>`` are included (see ``INERT_LINK_CONTAINERS``).
    """
    parser = _LinkParser(base_url, limit)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - the stdlib parser can raise on pathological input
        pass
    return parser.links
