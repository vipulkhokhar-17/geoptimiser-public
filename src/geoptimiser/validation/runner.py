"""Run one fixture through the real pipeline (crawl -> extract -> checks -> report)."""

import http.client
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from geoptimiser.crawler import (
    ArtifactWriter,
    CrawlConfig,
    Crawler,
    LocalBodyStore,
    SafeFetcher,
)
from geoptimiser.crawler.urls import host_in_scope
from geoptimiser.diagnosis import Diagnosis, diagnose
from geoptimiser.extraction import ExtractionWriter, extract_all
from geoptimiser.features import load_inputs
from geoptimiser.features.audit import AuditRun, run_audit
from geoptimiser.recommendations import RecommendationSet, TemplateGenerator
from geoptimiser.schemas import AuditRequest
from geoptimiser.validation.spec import FixtureSpec

DOMAIN = "fixture.test"
# A public-looking address: the fetcher's SSRF policy stays on while the TCP
# connection itself is redirected to the in-process server (as the demo does).
_PUBLIC_IP = "93.184.216.34"


class ServedSite:
    """The fixture's routes, served from memory on 127.0.0.1."""

    def __init__(self, spec: FixtureSpec) -> None:
        self.spec = spec
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?")[0]
                route = site.spec.site.get(path)
                if route is None:
                    body, status, ctype, headers = b"not found", 404, "text/plain", {}
                else:
                    if route.behavior == "drop":
                        self.connection.close()
                        return
                    if route.behavior == "hang":
                        time.sleep(5)
                        return
                    body = site.spec.body_for(path)
                    status, ctype, headers = (
                        route.status,
                        route.content_type,
                        route.headers,
                    )
                self.send_response(status)
                if ctype:
                    self.send_header("Content-Type", ctype)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@dataclass(frozen=True)
class FixtureRun:
    spec: FixtureSpec
    crawl_dir: Path
    run: AuditRun
    diagnosis: Diagnosis
    recommendations: RecommendationSet
    stop_reason: str


def run_fixture(spec: FixtureSpec, workdir: Path) -> FixtureRun:
    """Crawl the fixture site, extract, audit, diagnose and recommend. Offline."""
    audit_id = "aud_" + spec.id.replace("-", "_")[:40]
    crawl_dir = workdir / spec.id
    site = ServedSite(spec)
    try:
        config = CrawlConfig(
            max_pages=spec.crawl.max_pages,
            max_depth=spec.crawl.max_depth,
            max_response_bytes=spec.crawl.max_response_bytes,
            request_timeout_seconds=spec.crawl.request_timeout_seconds,
            max_fetch_seconds=max(spec.crawl.request_timeout_seconds * 2, 2.0),
            min_request_interval_seconds=0,
            respect_robots=spec.crawl.respect_robots,
        )
        store = LocalBodyStore(crawl_dir / "bodies")

        def connect(scheme, host, port, ip, timeout, policy):  # noqa: ANN001
            return http.client.HTTPConnection("127.0.0.1", site.port, timeout=timeout)

        fetcher = SafeFetcher(
            config,
            store,
            audit_id,
            host_allowed=lambda host: host_in_scope(host, DOMAIN),
            resolver=lambda host, port: [_PUBLIC_IP],
            connection_factory=connect,
        )
        request = AuditRequest(
            audit_id=audit_id,
            target_domain=DOMAIN,
            brand_name="Fixture",
            business_context="validation fixture",
            target_audience="n/a",
            authorization_confirmed=True,
        )
        with ArtifactWriter(crawl_dir) as sink:
            result = Crawler(
                request,
                config,
                fetcher,
                seed_url=f"https://{DOMAIN}/",
                sink=sink,
                sleep=lambda s: None,
            ).run()
        with ExtractionWriter(crawl_dir / "extraction") as ext_sink:
            extract_all(list(result.fetches), store, sink=ext_sink)
    finally:
        site.close()
    run = run_audit(load_inputs(crawl_dir))
    diagnosis = diagnose(run)
    recommendations = TemplateGenerator().generate(diagnosis)
    return FixtureRun(
        spec, crawl_dir, run, diagnosis, recommendations, result.stop_reason
    )
