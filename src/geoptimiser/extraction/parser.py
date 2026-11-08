"""Tolerant, bounded HTML parsing. Nothing in the page is executed or fetched.

The parser tokenizes markup with the standard library's ``html.parser`` and keeps
only what Stage 03 needs. It never evaluates scripts or styles, follows links, loads
resources, or resolves entities beyond text. Every limit in ``ExtractionConfig`` is
enforced while parsing, and a field cut by a limit is reported in
``ParsedPage.truncated`` instead of being silently shortened.
"""

import json
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from geoptimiser.crawler.urls import (
    INERT_LINK_CONTAINERS,
    resolve_base,
    resolve_link,
)
from geoptimiser.extraction.config import ExtractionConfig
from geoptimiser.extraction.rich import RichState

_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_BLOCK = frozenset(
    "address article aside blockquote body dd details dialog div dl dt fieldset "
    "figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre "
    "section summary table tbody td tfoot th thead tr ul".split()
)
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# Content here is data or inert, not visible page content.
_INERT = frozenset({"template", "noscript"})
_FOREIGN = frozenset({"svg", "math"})
_DATA = frozenset({"script", "style"})
# Start tags that can appear before the body; any other start tag ends the head.
_HEAD_TAGS = frozenset(
    "html head title meta link base script style noscript template".split()
)
_MOUNT_IDS = frozenset({"root", "app", "__next", "__nuxt", "___gatsby", "react-root"})
_MOUNT_ATTRS = ("ng-app", "data-reactroot", "ng-version", "data-server-rendered")
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_CHUNK = 64 * 1024
_MAX_TITLE = 2_000
_LINEBREAKS = {10: 32, 13: 32}
_MAX_JSON_NESTING_DEPTH = 1_000
_META_CHARSET = re.compile(r"charset\s*=\s*([A-Za-z0-9_.:+-]+)", re.I)


class ParseLimitExceeded(Exception):
    """Parsing ran past its time budget."""


@dataclass
class ParsedPage:
    """Fields measured from one HTML document (``None`` means absent)."""

    title: str | None = None
    meta_description: str | None = None
    meta_robots: str | None = None
    language: str | None = None
    canonical_url: str | None = None
    headings: list[tuple[int, str]] = field(default_factory=list)
    text: str = ""
    links: list[str] = field(default_factory=list)
    structured_data: list[dict[str, object]] = field(default_factory=list)
    structured_data_errors: int = 0
    structured_data_error_causes: dict[str, int] = field(default_factory=dict)
    head_complete: bool = False
    script_tags: int = 0
    external_scripts: int = 0
    inline_script_chars: int = 0
    mount_points: list[str] = field(default_factory=list)
    noscript_notice: str | None = None
    structured_data_types: list[str] = field(default_factory=list)
    truncated: set[str] = field(default_factory=set)
    # -- rich fields --
    viewport: str | None = None
    charset_declared: str | None = None
    images: list[dict[str, Any]] = field(default_factory=list)
    anchors: list[dict[str, Any]] = field(default_factory=list)
    landmarks: list[dict[str, Any]] = field(default_factory=list)
    semantic_counts: dict[str, int] = field(default_factory=dict)
    boilerplate_chars: int = 0
    main_chars: int = 0
    hidden_chars: int = 0
    tables: list[dict[str, Any]] = field(default_factory=list)
    lists: list[dict[str, Any]] = field(default_factory=list)
    media: list[dict[str, Any]] = field(default_factory=list)


def _squash(value: str) -> str:
    return " ".join(value.split())


def _json_nesting_exceeds_limit(raw: str, limit: int) -> bool:
    """Conservative depth check that ignores braces/brackets inside strings."""
    depth = 0
    in_string = False
    escaped = False

    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return True
        elif char in "]}":
            depth = max(depth - 1, 0)
    return False


class _Collector(HTMLParser):
    def __init__(
        self, base_url: str, config: ExtractionConfig, deadline: float
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.page = ParsedPage()
        self._base = base_url
        self._cfg = config
        self._deadline = deadline
        # (tag, hides its content, what the rich collector attached to the element)
        self._stack: list[tuple[str, bool, Any]] = []
        self._events = 0
        self._text: list[str] = []
        self._text_chars = 0
        self._title: list[str] | None = None
        self._heading: tuple[int, list[str]] | None = None
        self._json: list[str] | None = None
        self._json_bytes = 0
        self._json_blocks = 0
        self._seen_types: set[str] = set()
        self._base_set = False
        self._link_set: set[str] = set()
        self._rich = RichState(
            config, urlsplit(base_url).hostname or "", self._resolve_http
        )

    # -- state helpers --------------------------------------------------------

    def _tick(self) -> None:
        self._events += 1
        if self._events % 256 == 0 and time.monotonic() > self._deadline:
            raise ParseLimitExceeded

    def _inside(self, names: frozenset[str] | set[str]) -> bool:
        return any(tag in names for tag, _, _ in self._stack)

    def _hidden(self) -> bool:
        return any(hides for _, hides, _ in self._stack)

    def _live(self) -> bool:
        """True if the current position is page content (not inert or foreign)."""
        return not self._inside(_INERT | _FOREIGN)

    def _add_type(self, value: str) -> None:
        value = value.strip()
        if not value or value in self._seen_types:
            return
        if len(self._seen_types) >= self._cfg.max_types:
            self.page.truncated.add("structured_data")
            return
        self._seen_types.add(value)
        self.page.structured_data_types.append(value)

    # -- tag handlers ---------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tick()
        attr = {name.lower(): (value or "") for name, value in attrs}
        hides = "hidden" in attr or bool(_HIDDEN_STYLE.search(attr.get("style", "")))
        hidden = hides or self._hidden()
        self._note_structure(tag, attr)
        self._open_effects(tag, attr, hides)
        if tag in _VOID:
            self._rich.on_void(tag, attr, self._live(), hidden)
            return
        if len(self._stack) < self._cfg.max_nesting_depth:
            extra = self._rich.on_start(tag, attr, self._live(), hidden)
            self._stack.append((tag, hides, extra))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tick()
        attr = {n.lower(): (v or "") for n, v in attrs}
        self._open_effects(tag, attr, False)
        if tag in _VOID:
            self._rich.on_void(tag, attr, self._live(), self._hidden())

    def _note_structure(self, tag: str, attr: dict[str, str]) -> None:
        """Head completion and signals of a client-rendered shell."""
        if tag not in _HEAD_TAGS and not self._inside(_INERT):
            self.page.head_complete = True
        if tag == "script":
            self.page.script_tags += 1
            if attr.get("src"):
                self.page.external_scripts += 1
        mount = attr.get("id", "")
        if mount in _MOUNT_IDS and f"#{mount}" not in self.page.mount_points:
            self.page.mount_points.append(f"#{mount}")
        for name in _MOUNT_ATTRS:
            if name in attr and name not in self.page.mount_points:
                self.page.mount_points.append(name)

    def handle_endtag(self, tag: str) -> None:
        self._tick()
        if tag == "head":
            self.page.head_complete = True
        if tag == "br":
            self._newline()
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                removed = self._stack[index:]
                popped = {t for t, _, _ in removed}
                del self._stack[index:]
                self._close_effects(tag, popped)
                self._rich.on_end([extra for _, _, extra in removed])
                return  # an end tag with no open match is ignored

    def _open_effects(self, tag: str, attr: dict[str, str], hides: bool) -> None:
        live = self._live()
        # Links follow the crawler's rules (crawler.urls): <noscript> anchors count,
        # <template>/<svg>/<math> anchors do not, <base href> applies everywhere.
        if tag == "base" and not self._base_set and "href" in attr:
            self._set_base(attr["href"])
        elif tag == "a" and "href" in attr and not self._inside(INERT_LINK_CONTAINERS):
            self._link(attr["href"])
        if tag in _BLOCK or tag in _HEADINGS:
            self._finish_heading()
            self._newline()
        if tag == "br":
            self._newline()
        if tag == "html" and self.page.language is None and "lang" in attr:
            self.page.language = attr["lang"].strip()
        if not live:
            return
        if "itemtype" in attr:
            for token in attr["itemtype"].split():
                self._add_type(token)
        if tag == "title" and self.page.title is None and self._title is None:
            self._title = []
        elif tag == "meta":
            self._meta(attr)
        elif tag == "link":
            rel = attr.get("rel", "").lower().split()
            if (
                "canonical" in rel
                and "href" in attr
                and self.page.canonical_url is None
            ):
                self.page.canonical_url = attr["href"].strip()
        elif tag in _HEADINGS and not (hides or self._hidden()):
            self._heading = (int(tag[1]), [])
        elif tag == "script" and self._json is None:
            kind = attr.get("type", "").split(";")[0].strip().lower()
            if kind == "application/ld+json":
                self._json = []
                self._json_bytes = 0

    def _close_effects(self, tag: str, popped: set[str]) -> None:
        if tag == "title" or "title" in popped:
            if self._title is not None:
                self.page.title = _squash("".join(self._title))[:_MAX_TITLE]
                self._title = None
        if tag in _HEADINGS or popped & _HEADINGS:
            self._finish_heading()
        if tag == "script" and self._json is not None:
            self._finish_json()
        if tag in _BLOCK:
            self._newline()

    def _meta(self, attr: dict[str, str]) -> None:
        if "charset" in attr and self.page.charset_declared is None:
            self.page.charset_declared = attr["charset"].strip().lower()[:50] or None
        name = attr.get("name", "").strip().lower()
        content = attr.get("content")
        if content is None:
            return
        if (
            attr.get("http-equiv", "").strip().lower() == "content-type"
            and self.page.charset_declared is None
        ):
            match = _META_CHARSET.search(content)
            if match:
                self.page.charset_declared = match.group(1).lower()
        if name == "viewport" and self.page.viewport is None:
            self.page.viewport = _squash(content)[:500]
        if name == "description" and self.page.meta_description is None:
            self.page.meta_description = _squash(content)
        elif name == "robots" and self.page.meta_robots is None:
            self.page.meta_robots = _squash(content)

    def _set_base(self, href: str) -> None:
        resolved = resolve_base(self._base, href)
        if resolved:
            self._base = resolved
            self._base_set = True

    def _resolve_http(self, raw: str) -> str | None:
        """Absolute http(s) URL for ``raw`` (against the current base), or ``None``."""
        return resolve_link(self._base, raw)

    def _link(self, href: str) -> None:
        if len(href.strip()) > self._cfg.max_url_length:
            return
        url = self._resolve_http(href)
        if url is None or len(url) > self._cfg.max_url_length or url in self._link_set:
            return
        if len(self.page.links) >= self._cfg.max_links:
            self.page.truncated.add("links")
            return
        self._link_set.add(url)
        self.page.links.append(url)

    # -- data handler ---------------------------------------------------------

    def handle_data(self, data: str) -> None:
        self._tick()
        if self._json is not None:
            self._json_bytes += len(data)
            if self._json_bytes <= self._cfg.max_json_ld_bytes:
                self._json.append(data)
            return
        if self._inside({"script"}):
            self.page.inline_script_chars += len(data)
        if self._inside({"noscript"}) and self.page.noscript_notice is None:
            if "javascript" in data.lower():
                self.page.noscript_notice = _squash(data)[:160]
        if self._inside(_DATA) or not self._live():
            return
        if self._title is not None:
            self._title.append(data)
            return
        if self._hidden():
            self._rich.on_hidden(data)
            return
        if self._heading is not None:
            self._heading[1].append(data)
        self._append_text(data)
        self._rich.on_text(data)

    def _append_text(self, data: str) -> None:
        # Source newlines are plain whitespace; only block tags start a new line.
        data = data.translate(_LINEBREAKS)
        room = self._cfg.max_text_chars - self._text_chars
        if room <= 0:
            if data.strip():
                self.page.truncated.add("text")
            return
        if len(data) > room:
            data = data[:room]
            self.page.truncated.add("text")
        self._text.append(data)
        self._text_chars += len(data)

    def _newline(self) -> None:
        self._rich.on_break()
        if self._text_chars < self._cfg.max_text_chars:
            self._text.append("\n")

    def _finish_heading(self) -> None:
        if self._heading is None:
            return
        level, parts = self._heading
        self._heading = None
        if len(self.page.headings) >= self._cfg.max_headings:
            self.page.truncated.add("headings")
            return
        text = _squash("".join(parts))
        if len(text) > self._cfg.max_heading_chars:
            text = text[: self._cfg.max_heading_chars]
            self.page.truncated.add("headings")
        self.page.headings.append((level, text))

    # -- JSON-LD ----------------------------------------------------------------

    def _json_failed(self, cause: str) -> None:
        self.page.structured_data_errors += 1
        causes = self.page.structured_data_error_causes
        causes[cause] = causes.get(cause, 0) + 1

    def _finish_json(self) -> None:
        raw = "".join(self._json or [])
        too_big = self._json_bytes > self._cfg.max_json_ld_bytes
        self._json = None
        if self._json_blocks >= self._cfg.max_json_ld_blocks:
            self.page.truncated.add("structured_data")
            return
        self._json_blocks += 1
        if too_big:
            self._json_failed("size_limit")
            self.page.truncated.add("structured_data")
            return
        if _json_nesting_exceeds_limit(raw, _MAX_JSON_NESTING_DEPTH):
            self._json_failed("nesting_limit")
            self.page.truncated.add("structured_data")
            return
        try:
            parsed = json.loads(raw)
        except (ValueError, RecursionError):
            self._json_failed("syntax_error")
            return
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if isinstance(item, dict):
                self.page.structured_data.append(item)
                self._collect_types(item)

    def _collect_types(self, item: dict[str, object]) -> None:
        """Record ``@type`` of an object and of the members of its ``@graph``."""
        types = item.get("@type")
        for value in types if isinstance(types, list) else [types]:
            if isinstance(value, str):
                self._add_type(value)
        graph = item.get("@graph")
        if isinstance(graph, list):
            for member in graph:
                if isinstance(member, dict):
                    self._collect_types(
                        {k: v for k, v in member.items() if k != "@graph"}
                    )

    def finish(self) -> ParsedPage:
        self._finish_heading()
        if self._title is not None:  # unterminated <title> swallows the rest
            self.page.title = _squash("".join(self._title))[:_MAX_TITLE]
            self.page.truncated.add("title")  # its end was never seen
        if self._json is not None:  # unterminated JSON-LD script: unreadable
            self._json_failed("unterminated")
        lines = (_squash(line) for line in "".join(self._text).split("\n"))
        self.page.text = "\n".join(line for line in lines if line)
        rich = self._rich
        rich.finish()
        self.page.images = rich.images
        self.page.anchors = rich.anchors
        self.page.landmarks = rich.landmarks
        self.page.semantic_counts = dict(sorted(rich.semantic_counts.items()))
        self.page.boilerplate_chars = rich.boilerplate_chars
        self.page.main_chars = rich.main_chars
        self.page.hidden_chars = rich.hidden_chars
        self.page.tables = rich.tables
        self.page.lists = rich.lists
        self.page.media = rich.media
        self.page.truncated |= rich.truncated
        return self.page


def parse_html(html: str, base_url: str, config: ExtractionConfig) -> ParsedPage:
    """Parse ``html`` (already decoded text). Raises ``ParseLimitExceeded``.

    ``base_url`` is the page's own URL, used to resolve links; a ``<base href>``
    changes it for the rest of the document. Any other exception from the standard
    parser is for the caller to report as a parse failure.
    """
    deadline = time.monotonic() + config.max_seconds
    collector = _Collector(base_url, config, deadline)
    for start in range(0, len(html), _CHUNK):
        if time.monotonic() > deadline:
            raise ParseLimitExceeded
        collector.feed(html[start : start + _CHUNK])
    collector.close()
    return collector.finish()
