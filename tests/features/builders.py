"""Deterministic builders: pages, sites and robots files without any network or crawl."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from geoptimiser.features import AuditInputs, FeatureConfig, run_feature
from geoptimiser.features.inputs import PageContext, RobotsFile, origin_of
from geoptimiser.schemas import FeatureResult, FetchRecord, Heading, PageDocument

AUDIT = "aud_feat"
NOW = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
SITE = "https://www.example.com"


def make_fetch(url: str, **overrides: Any) -> FetchRecord:
    fields: dict[str, Any] = {
        "audit_id": AUDIT,
        "fetch_id": "f_" + hashlib.sha1(url.encode()).hexdigest()[:12],
        "requested_url": url,
        "outcome": "success",
        "status_code": 200,
        "final_url": url,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": {
            "ref": "sha256:" + "a" * 64,
            "sha256": "a" * 64,
            "size_bytes": 4000,
        },
        "started_at": NOW - timedelta(seconds=1),
        "completed_at": NOW,
    }
    return FetchRecord.model_validate(fields | overrides)


def error_fetch(url: str, status: int = 404) -> FetchRecord:
    return make_fetch(
        url,
        outcome="http_error",
        status_code=status,
        body=None,
        body_not_stored_reason="non_success_status",
    )


def make_document(fetch: FetchRecord, **overrides: Any) -> PageDocument:
    path = fetch.final_url.path if fetch.final_url else "/"
    slug = path.strip("/") or "home"
    fields: dict[str, Any] = {
        "audit_id": AUDIT,
        "document_id": f"doc:{fetch.fetch_id}",
        "fetch_id": fetch.fetch_id,
        "url": str(fetch.final_url),
        "extraction_version": "html-extractor:2",
        "detail_level": 2,
        "title": f"{slug.replace('-', ' ').title()} guide for example",
        "meta_description": f"A page about {slug.replace('-', ' ')} for example visitors.",
        "language": "en",
        "headings": [Heading(level=1, text=f"{slug.replace('-', ' ').title()} guide")],
        "text": (
            f"{slug.replace('-', ' ').title()} guide\n"
            + f"Detailed {slug} content. " * 20
        ).strip(),
        "links": [],
        "canonical_url": str(fetch.final_url),
        "encoding": "utf-8",
        "extracted_at": NOW,
    }
    merged = fields | overrides
    if (
        "links" in overrides
        and "anchors" not in overrides
        and merged.get("detail_level", 2) >= 2
    ):
        # Tests that only state links get one plain content anchor per link.
        merged["anchors"] = [
            {
                "href": link,
                "text": "Link text",
                "internal": "example.com" in link,
                "region": "content",
            }
            for link in merged["links"]
        ]
    return PageDocument.model_validate(merged)


def page(
    url: str,
    *,
    fetch: dict[str, Any] | None = None,
    doc: dict[str, Any] | None = None,
    no_document: bool = False,
) -> PageContext:
    record = make_fetch(url, **(fetch or {}))
    document = (
        None
        if no_document or record.outcome != "success"
        else make_document(record, **(doc or {}))
    )
    return PageContext(record, document)


def robots_file(
    text: str | None, *, origin: str = SITE, status: int = 200, **fetch: Any
) -> RobotsFile:
    url = f"{origin}/robots.txt"
    if fetch.get("outcome") == "transport_error" or status >= 400:
        record = (
            make_fetch(
                url,
                outcome="transport_error",
                status_code=None,
                final_url=None,
                headers={},
                body=None,
                error_type="timeout",
                error_message="t",
            )
            if fetch.get("outcome") == "transport_error"
            else make_fetch(
                url,
                outcome="http_error",
                status_code=status,
                body=None,
                body_not_stored_reason="non_success_status",
                headers={},
            )
        )
        return RobotsFile(origin_of(url), record, None)
    return RobotsFile(
        origin_of(url), make_fetch(url, headers={"Content-Type": "text/plain"}), text
    )


def audit(*pages: PageContext, robots: tuple[RobotsFile, ...] = ()) -> AuditInputs:
    return AuditInputs(AUDIT, pages, robots, site_domain="example.com")


def run(feature_id: str, inputs: AuditInputs, **config: Any) -> list[FeatureResult]:
    return run_feature(feature_id, inputs, FeatureConfig(**config))


def status_of(feature_id: str, *pages: PageContext, **config: Any) -> str:
    """Status of ``feature_id`` for the first page of a site made of ``pages``."""
    results = run(feature_id, audit(*pages), **config)
    return results[0].status


def statuses(
    feature_id: str, inputs: AuditInputs, **config: Any
) -> dict[str | None, str]:
    return {r.subject_url: r.status for r in run(feature_id, inputs, **config)}


# Fetch overrides for the non-success outcomes.
FETCH_404 = {
    "outcome": "http_error",
    "status_code": 404,
    "body": None,
    "body_not_stored_reason": "non_success_status",
}
FETCH_TIMEOUT = {
    "outcome": "transport_error",
    "status_code": None,
    "final_url": None,
    "headers": {},
    "body": None,
    "error_type": "timeout",
    "error_message": "timed out",
}
FETCH_REFUSED = {
    "outcome": "redirect_not_followed",
    "status_code": 302,
    "body": None,
    "redirect_refusal_reason": "cross_domain",
}
