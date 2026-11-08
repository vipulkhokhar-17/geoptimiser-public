"""Contracts shared by the application layer: submissions, statuses, stage records.

Everything an API client can send is validated here before it reaches the pipeline.
Whether a target may actually be *fetched* is still decided only by the crawler's SSRF
policy at fetch time; the checks below merely reject obviously unusable input early.
"""

import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, StrictBool

from geoptimiser.schemas import (
    Identifier,
    NonBlankStr,
    SchemaModel,
    UtcDatetime,
    VersionedRecord,
    normalize_domain,
)

PIPELINE_VERSION = "geoptimiser-pipeline/1"

AuditStatus = Literal[
    "queued", "running", "completed", "incomplete", "failed", "interrupted"
]
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "incomplete", "failed", "interrupted"}
)
StageName = Literal[
    "validate",
    "crawl",
    "extract",
    "features",
    "chunk",
    "retrieval",
    "diagnose",
    "recommend",
    "agent",
    "validate_output",
    "report",
]
STAGES: tuple[str, ...] = (
    "validate", "crawl", "extract", "features", "chunk", "retrieval",
    "diagnose", "recommend", "agent", "validate_output", "report",
)  # fmt: skip
# A failure in these stages fails the audit; elsewhere it leaves the audit incomplete.
CRITICAL_STAGES: frozenset[str] = frozenset(
    {"validate", "crawl", "extract", "features", "diagnose", "recommend",
     "validate_output", "report"}
)  # fmt: skip
StageStatus = Literal["pending", "running", "ok", "skipped", "failed"]
ErrorCategory = Literal[
    "invalid_target",
    "blocked_target",
    "dns",
    "connection",
    "tls",
    "timeout",
    "http_error",
    "no_content",
    "crawl_error",
    "extraction_error",
    "feature_error",
    "retrieval_unavailable",
    "diagnosis_error",
    "validation_failed",
    "agent_unavailable",
    "agent_failed",
    "agent_incomplete",
    "interrupted",
    "internal_error",
]
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp")


class TargetError(ValueError):
    """The submitted URL cannot be audited."""


class NormalizedTarget(SchemaModel):
    url: str  # the seed URL: no query, fragment or credentials
    normalized_url: str  # comparison key (lower-case host, canonical path)
    domain: str  # scope of the crawl


def normalize_target(raw: str) -> NormalizedTarget:
    """Validate a user-supplied URL and reduce it to a crawl seed and a comparison key.

    Rejects non-http(s) schemes, embedded credentials, IP literals, single-label and
    local-looking host names, and non-default ports. This is an early, cheap filter:
    the crawler independently re-validates every resolved address.
    """
    text = raw.strip()
    if not text or len(text) > 2048 or any(c.isspace() or ord(c) < 32 for c in text):
        raise TargetError("enter a single http(s) URL of at most 2048 characters")
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise TargetError("the URL is not valid") from None
    if parts.scheme not in {"http", "https"}:
        raise TargetError("only http and https URLs can be audited")
    if parts.username is not None or parts.password is not None:
        raise TargetError("URLs containing credentials are not accepted")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise TargetError("the URL has no host name")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise TargetError("enter a domain name, not an IP address")
    try:
        domain = normalize_domain(host)
    except ValueError as exc:
        raise TargetError(str(exc)) from None
    if domain.endswith(_BLOCKED_SUFFIXES) or domain == "localhost":
        raise TargetError("local and internal host names cannot be audited")
    default = 443 if parts.scheme == "https" else 80
    if port not in (None, default):
        raise TargetError("only the default http/https ports are accepted")
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    seed = urlunsplit((parts.scheme, domain, path, "", ""))
    key_path = path if path == "/" else path.rstrip("/")
    return NormalizedTarget(
        url=seed,
        normalized_url=urlunsplit((parts.scheme, domain, key_path, "", "")),
        domain=domain,
    )


class AuditOptions(SchemaModel):
    """What the user may choose. Everything else (limits, robots, SSRF policy) is
    fixed by the server and cannot be loosened through the API."""

    max_pages: int = Field(default=10, ge=1, le=100)
    max_depth: int = Field(default=2, ge=0, le=5)
    # lexical: BM25 passage ranking; semantic: needs the sentence-transformers extra;
    # off: measurement evidence only.
    retrieval: Literal["off", "lexical", "semantic"] = "lexical"
    use_agent: bool = False  # explicit opt-in; needs OPENROUTER_API_KEY and the extra


class AuditSubmission(SchemaModel):
    url: str = Field(min_length=3, max_length=2048)
    brand_name: str | None = Field(default=None, min_length=1, max_length=100)
    authorization_confirmed: StrictBool
    options: AuditOptions = AuditOptions()


class StageRecord(SchemaModel):
    name: StageName
    status: StageStatus
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    duration_ms: float | None = None
    error_category: ErrorCategory | None = None
    error_message: str | None = None
    detail: dict[str, object] = Field(default_factory=dict)


class AuditRecord(VersionedRecord):
    audit_id: Identifier
    target_url: NonBlankStr
    normalized_url: NonBlankStr
    domain: NonBlankStr
    brand_name: str | None
    status: AuditStatus
    stage: str | None
    error_category: ErrorCategory | None
    error_message: str | None
    created_at: UtcDatetime
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    pipeline_version: str
    options: AuditOptions
    pipeline: dict[str, object]  # component versions recorded when the audit ran
    summary: dict[str, object]
