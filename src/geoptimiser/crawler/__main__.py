"""CLI: ``python -m geoptimiser.crawler --domain example.com --out runs/example``."""

import argparse
from pathlib import Path

from geoptimiser.crawler import (
    ArtifactWriter,
    CrawlConfig,
    Crawler,
    LocalBodyStore,
    SafeFetcher,
)
from geoptimiser.crawler.urls import host_in_scope
from geoptimiser.schemas import AuditRequest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crawl one authorized website.")
    parser.add_argument("--domain", required=True, help="bare domain, e.g. example.com")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--max-pages", type=int, default=CrawlConfig().max_pages)
    parser.add_argument("--max-depth", type=int, default=CrawlConfig().max_depth)
    parser.add_argument(
        "--confirm-authorized",
        action="store_true",
        help="attest that you own or are authorized to audit the domain",
    )
    args = parser.parse_args(argv)
    if not args.confirm_authorized:
        parser.error("--confirm-authorized is required")

    request = AuditRequest(
        target_domain=args.domain,
        brand_name=args.domain,
        business_context="crawl only",
        target_audience="n/a",
        authorization_confirmed=True,
    )
    config = CrawlConfig(max_pages=args.max_pages, max_depth=args.max_depth)
    store = LocalBodyStore(args.out / "bodies")
    fetcher = SafeFetcher(
        config,
        store,
        request.audit_id,
        host_allowed=lambda host: host_in_scope(host, request.target_domain),
    )
    with ArtifactWriter(args.out) as sink:
        result = Crawler(request, config, fetcher, sink=sink).run()
    print(
        f"audit {result.audit_id}: {len(result.fetches)} fetches, "
        f"{len(result.skipped)} skipped, stopped: {result.stop_reason}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
