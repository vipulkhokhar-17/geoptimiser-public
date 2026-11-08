"""Everything the checks read: fetches, documents, robots files, link graph."""

import json
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from geoptimiser.crawler import LocalBodyStore, read_fetches
from geoptimiser.crawler.urls import host_in_scope
from geoptimiser.extraction import read_documents
from geoptimiser.schemas import ExtractionFailure, FetchRecord, PageDocument

_DEFAULT_PORTS = {"http": 80, "https": 443}


def url_key(url: str) -> str:
    """Canonical comparison key: lower-case scheme and host, no default port or
    fragment, empty path as ``/``. Query strings and path case are preserved."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port and port != _DEFAULT_PORTS.get(parts.scheme):
        host += f":{port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


@dataclass(frozen=True)
class CrawlFacts:
    """How the pages of an audit were discovered, from ``crawl_summary.json``.

    Absent (``None`` on ``AuditInputs``) when the pages did not come from this crawler
    (hand-built inputs, imported audits): checks and scoring then assume nothing.
    ``discovery`` is always ``"links"``: pages are found by following links from the
    entry page, which is why a crawled page cannot be an orphan (see F009).
    """

    max_depth: int | None = None
    max_pages: int | None = None
    follow_query_strings: bool | None = None
    stop_reason: str | None = None
    discovery: str = "links"


@dataclass(frozen=True)
class PageContext:
    """One fetched page with its extraction result (document or failure, if any)."""

    fetch: FetchRecord
    document: PageDocument | None = None
    failure: ExtractionFailure | None = None

    @property
    def url(self) -> str:
        return str(self.fetch.final_url or self.fetch.requested_url)

    @property
    def key(self) -> str:
        return url_key(self.url)


@dataclass(frozen=True)
class RobotsFile:
    origin: str
    record: FetchRecord
    text: str | None  # decoded body, if one was stored


class LinkGraph:
    """Internal link graph over the audit's crawled pages (redirects collapsed)."""

    def __init__(self, inputs: "AuditInputs") -> None:
        self.nodes: dict[str, PageContext] = {p.key: p for p in inputs.pages}
        self.alias: dict[str, str] = {}
        for page in inputs.pages:
            self.alias[page.key] = page.key
            self.alias.setdefault(url_key(str(page.fetch.requested_url)), page.key)
            for hop in page.fetch.redirects:
                self.alias.setdefault(url_key(str(hop.url)), page.key)
        self.internal_links: dict[str, tuple[str, ...]] = {}
        self.incoming: dict[str, set[str]] = {key: set() for key in self.nodes}
        for key, page in self.nodes.items():
            links = []
            if page.document is not None:
                for link in page.document.links:
                    host = urlsplit(link).hostname or ""
                    if host_in_scope(host, inputs.site_domain):
                        links.append(url_key(link))
            self.internal_links[key] = tuple(links)
            for link in links:
                target = self.alias.get(link)
                if target is not None and target != key:
                    self.incoming[target].add(key)
        self.entry = inputs.pages[0].key if inputs.pages else None
        self.depth = self._depths()

    def _depths(self) -> dict[str, int]:
        if self.entry is None:
            return {}
        depth = {self.entry: 0}
        queue = deque([self.entry])
        while queue:
            current = queue.popleft()
            for link in self.internal_links.get(current, ()):
                target = self.alias.get(link)
                if target is not None and target not in depth:
                    depth[target] = depth[current] + 1
                    queue.append(target)
        return depth


class AuditInputs:
    """A read-only view of one audit's Stage 01/02 artifacts."""

    def __init__(
        self,
        audit_id: str,
        pages: Iterable[PageContext],
        robots: Iterable[RobotsFile] = (),
        site_domain: str | None = None,
        crawl: CrawlFacts | None = None,
    ) -> None:
        seen: set[str] = set()
        unique: list[PageContext] = []
        for page in pages:  # one page per final URL: the first fetch wins
            if page.key not in seen:
                seen.add(page.key)
                unique.append(page)
        self.audit_id = audit_id
        self.crawl = crawl
        self.pages = tuple(unique)
        self.robots = tuple(robots)
        first = urlsplit(self.pages[0].url).hostname if self.pages else None
        self.site_domain = (site_domain or first or "").removeprefix("www.")
        stamps = [p.fetch.completed_at for p in self.pages]
        stamps += [r.record.completed_at for r in self.robots]
        self.observed_at: datetime | None = max(stamps) if stamps else None

    @cached_property
    def graph(self) -> LinkGraph:
        return LinkGraph(self)

    @cached_property
    def known_urls(self) -> frozenset[str]:
        """Every URL an evidence reference may legitimately cite."""
        urls = {p.url for p in self.pages}
        urls |= {str(p.fetch.requested_url) for p in self.pages}
        urls |= {str(r.record.final_url or r.record.requested_url) for r in self.robots}
        return frozenset(urls)

    def robots_for(self, url: str) -> RobotsFile | None:
        origin = origin_of(url)
        return next((r for r in self.robots if r.origin == origin), None)

    @classmethod
    def build(
        cls,
        audit_id: str,
        fetches: Iterable[FetchRecord],
        documents: Iterable[PageDocument] = (),
        failures: Iterable[ExtractionFailure] = (),
        robots_bodies: Mapping[str, bytes] | None = None,
        site_domain: str | None = None,
        crawl: CrawlFacts | None = None,
    ) -> "AuditInputs":
        docs = {d.fetch_id: d for d in documents}
        fails = {f.fetch_id: f for f in failures}
        bodies = robots_bodies or {}
        pages: list[PageContext] = []
        robots: list[RobotsFile] = []
        for fetch in fetches:
            if fetch.final_url is not None and fetch.final_url.path == "/robots.txt":
                raw = bodies.get(fetch.fetch_id)
                text = raw.decode("utf-8", "replace") if raw is not None else None
                robots.append(
                    RobotsFile(origin_of(str(fetch.requested_url)), fetch, text)
                )
            elif fetch.requested_url.path == "/robots.txt" and not fetch.redirects:
                robots.append(
                    RobotsFile(origin_of(str(fetch.requested_url)), fetch, None)
                )
            else:
                pages.append(
                    PageContext(
                        fetch, docs.get(fetch.fetch_id), fails.get(fetch.fetch_id)
                    )
                )
        return cls(audit_id, pages, robots, site_domain, crawl)


def load_inputs(crawl_dir: Path, extraction_dir: Path | None = None) -> AuditInputs:
    """Load a finished crawl and its extraction (default ``<crawl_dir>/extraction``)."""
    extraction_dir = extraction_dir or crawl_dir / "extraction"
    fetches = read_fetches(crawl_dir / "fetches.jsonl")
    documents = read_documents(extraction_dir / "documents.jsonl")
    failures = _read_failures(extraction_dir / "extraction_failures.jsonl")
    store = LocalBodyStore(crawl_dir / "bodies")
    bodies: dict[str, bytes] = {}
    for fetch in fetches:
        if fetch.requested_url.path == "/robots.txt" and fetch.body is not None:
            try:
                bodies[fetch.fetch_id] = store.get(fetch.body.ref)
            except (OSError, ValueError):
                pass  # the robots file then counts as unreadable, not as empty
    audit_id = fetches[0].audit_id if fetches else "aud_unknown"
    return AuditInputs.build(
        audit_id, fetches, documents, failures, bodies, crawl=_read_crawl(crawl_dir)
    )


def _read_crawl(crawl_dir: Path) -> CrawlFacts | None:
    """Crawl limits from ``crawl_summary.json``; ``None`` if absent or unreadable."""
    path = crawl_dir / "crawl_summary.json"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
        config = summary["config"]
        return CrawlFacts(
            max_depth=int(config["max_depth"]),
            max_pages=int(config["max_pages"]),
            follow_query_strings=bool(config["follow_query_strings"]),
            stop_reason=summary.get("stop_reason"),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _read_failures(path: Path) -> list[ExtractionFailure]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").split("\n")[:-1]
    return [
        ExtractionFailure.model_validate(json.loads(line))
        for line in lines
        if line.strip()
    ]
