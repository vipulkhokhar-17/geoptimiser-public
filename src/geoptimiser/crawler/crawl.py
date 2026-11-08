"""Bounded breadth-first crawl of one audited site, producing ``FetchRecord``s."""

import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from geoptimiser.crawler.artifacts import ArtifactWriter
from geoptimiser.crawler.config import CrawlConfig
from geoptimiser.crawler.fetcher import FetchResult, SafeFetcher, _canonical
from geoptimiser.crawler.robots import RobotsPolicy
from geoptimiser.crawler.urls import extract_links, host_in_scope, normalize_url
from geoptimiser.schemas import AuditRequest, FetchRecord, Identifier, UtcDatetime

StopReason = Literal[
    "completed", "max_pages", "audit_byte_budget", "audit_timeout", "aborted"
]


SkipReason = Literal["robots_disallowed", "byte_budget_exhausted", "invalid_url"]


class SkippedUrl(BaseModel):
    """A URL deliberately not requested: absence of a fetch, not a failed fetch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: Identifier
    url: str
    reason: SkipReason
    discovered_from: str | None = None


class CrawlResult(BaseModel):
    """Everything one crawl produced, with the limits it ran under.

    ``stop_reason="aborted"`` means an exception ended the crawl; ``error`` then
    holds only the exception class name.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: Identifier
    config: CrawlConfig
    fetches: tuple[FetchRecord, ...]
    skipped: tuple[SkippedUrl, ...]
    stop_reason: StopReason
    error: str | None = None
    started_at: UtcDatetime
    completed_at: UtcDatetime


class Crawler:
    """Crawls ``https://<target_domain>/`` and in-scope links, within ``config``."""

    def __init__(
        self,
        request: AuditRequest,
        config: CrawlConfig,
        fetcher: SafeFetcher,
        *,
        seed_url: str | None = None,
        sink: ArtifactWriter | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """``seed_url`` defaults to ``https://<domain>/``; it must be in scope.

        With a ``sink``, every record is written durably as it is produced.
        """
        if seed_url is not None:
            host = urlsplit(seed_url).hostname
            if not host or not host_in_scope(host, request.target_domain):
                raise ValueError("seed_url must be inside the target domain")
        self.seed_url = seed_url
        self.request = request
        self.config = config
        self.fetcher = fetcher
        self.sink = sink
        self._clock, self._sleep = clock, sleep
        self._fetches: list[FetchRecord] = []
        self._skipped: list[SkippedUrl] = []
        self._bytes_used = 0
        self._last_request = float("-inf")
        self._robots: dict[str, RobotsPolicy] = {}
        self._queued: set[str] = set()  # discovered; never enqueued twice
        self._visited: set[str] = set()  # requested, including redirect hops

    def run(self) -> CrawlResult:
        started = datetime.now(UTC)
        try:
            stop = self._crawl()
        except BaseException as exc:
            self._finish(started, "aborted", type(exc).__name__)
            raise
        return self._finish(started, stop, None)

    # -- main loop ------------------------------------------------------------

    def _crawl(self) -> StopReason:
        t0 = self._clock()
        seed = self.seed_url or f"https://{self.request.target_domain}/"
        seed = self._key(seed) or seed
        queue: deque[tuple[str, int]] = deque([(seed, 0)])
        self._queued.add(seed)
        pages = 0
        while queue:
            if pages >= self.config.max_pages:
                return "max_pages"
            if self._clock() - t0 > self.config.max_audit_seconds:
                return "audit_timeout"
            if self._remaining_bytes() <= 0:
                return "audit_byte_budget"
            url, depth = queue.popleft()
            if url in self._visited:
                continue  # already fetched as a redirect destination
            if self.config.respect_robots and not self._robots_for(url).allows(url):
                self._skip(url, "robots_disallowed")
                continue
            if self._remaining_bytes() <= 0:  # robots.txt used the last bytes
                self._skip(url, "byte_budget_exhausted")
                return "audit_byte_budget"
            self._visited.add(url)
            try:
                result = self._fetch(
                    url, "page", self.config.max_response_bytes, self._redirect_allowed
                )
            except ValueError:
                # A discovered link that the fetcher's URL parser rejects is skipped and
                # recorded; it must not abort the whole audit (security audit run 1).
                self._skip(url, "invalid_url")
                continue
            pages += 1
            self._mark_visited(result.record)
            for link in self._discover(result, depth):
                if link not in self._queued:
                    self._queued.add(link)
                    queue.append((link, depth + 1))
        return "completed"

    def _finish(
        self, started: datetime, stop: StopReason, error: str | None
    ) -> CrawlResult:
        result = CrawlResult(
            audit_id=self.request.audit_id,
            config=self.config,
            fetches=tuple(self._fetches),
            skipped=tuple(self._skipped),
            stop_reason=stop,
            error=error,
            started_at=started,
            completed_at=datetime.now(UTC),
        )
        if self.sink is not None:
            summary = result.model_dump(mode="json", exclude={"fetches", "skipped"})
            summary |= {
                "fetch_count": len(result.fetches),
                "skipped_count": len(result.skipped),
            }
            self.sink.write_summary(summary)
        return result

    # -- helpers --------------------------------------------------------------

    def _remaining_bytes(self) -> int:
        return self.config.max_audit_bytes - self._bytes_used

    def _key(self, url: str) -> str | None:
        return normalize_url(
            url,
            max_length=self.config.max_url_length,
            follow_query=self.config.follow_query_strings,
        )

    def _skip(self, url: str, reason: SkipReason) -> None:
        skipped = SkippedUrl(audit_id=self.request.audit_id, url=url, reason=reason)
        self._skipped.append(skipped)
        if self.sink is not None:
            self.sink.write_skipped(skipped)

    def _fetch(
        self,
        url: str,
        kind: Literal["page", "robots"],
        cap: int,
        redirect_allowed: Callable[[str], bool] | None = None,
    ) -> FetchResult:
        """Fetch within the remaining audit budget (the caller checked it is > 0)."""
        wait = self.config.min_request_interval_seconds - (
            self._clock() - self._last_request
        )
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()
        result = self.fetcher.fetch(
            url,
            kind=kind,
            max_bytes=min(cap, self._remaining_bytes()),
            redirect_allowed=redirect_allowed,
        )
        record = result.record
        if record.body is not None:
            self._bytes_used += record.body.size_bytes
        self._fetches.append(record)
        if self.sink is not None:
            self.sink.write_fetch(record)
        return result

    def _robots_for(self, url: str) -> RobotsPolicy:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            if self._remaining_bytes() <= 0:
                return RobotsPolicy(allow_all=False)  # unknown: assume disallowed
            result = self._fetch(
                origin + "/robots.txt", "robots", self.config.max_robots_bytes
            )
            self._robots[origin] = RobotsPolicy.from_fetch(
                result.record, result.body, self.config.user_agent
            )
        return self._robots[origin]

    def _redirect_allowed(self, target: str) -> bool:
        """Robots check for a redirect destination, before it is fetched."""
        return not self.config.respect_robots or self._robots_for(target).allows(target)

    def _mark_visited(self, record: FetchRecord) -> None:
        """Remember every URL this fetch requested so none is fetched again."""
        urls = [str(record.requested_url), *(str(h.url) for h in record.redirects)]
        if record.final_url is not None:
            urls.append(str(record.final_url))
        for url in urls:
            key = self._key(url)
            if key:
                self._visited.add(key)
                self._queued.add(key)

    def _discover(self, result: FetchResult, depth: int) -> list[str]:
        record = result.record
        if (
            depth >= self.config.max_depth
            or result.body is None
            or record.final_url is None
        ):
            return []
        html = result.body.decode(
            _charset(record.headers.get("content-type")), "replace"
        )
        found: list[str] = []
        for href in extract_links(
            html, str(record.final_url), limit=self.config.max_links_per_page
        ):
            key = self._key(href)
            # Decide scope on the canonical form the fetcher will connect to, so the two
            # URL parsers cannot disagree about the host (security audit run 1).
            canonical = _canonical(key) if key else None
            host = urlsplit(str(canonical)).hostname if canonical else None
            if key and host and host_in_scope(host, self.request.target_domain):
                found.append(key)
        return found


def _charset(content_type: str | None) -> str:
    for part in (content_type or "").split(";")[1:]:
        name, _, value = part.strip().partition("=")
        if name.lower() == "charset":
            try:
                "".encode(value.strip("\"' "))
            except LookupError:
                break
            return value.strip("\"' ")
    return "utf-8"
