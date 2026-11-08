"""Shared data contracts used across Geoptimiser modules.

Conventions (see ``docs/SCHEMAS.md`` and ADR-0004):

- Models reject unknown fields, so a typo in a cross-module payload fails loudly.
- Timestamps must be timezone-aware and are normalized to UTC.
- URLs the platform itself requests are validated (``HttpUrl``). URLs observed in
  untrusted content (links, canonical tags, citations) stay raw strings, so a
  malformed value is recorded as an observation instead of rejecting the record.
- A missing measurement (``not_measured``, ``error``, failed collection) is never
  represented as a negative result.
- Records are immutable after validation: models are frozen, collections are
  tuples and ``FetchRecord.headers`` is read-only. Raw JSON values
  (``structured_data`` contents, ``observed_value``) are not deep-frozen. To
  change a record, validate a new one; ``model_copy(update=...)`` skips
  validation (see ``SchemaModel``).
"""

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PlainSerializer,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

_DOMAIN_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _require_true(value: bool) -> bool:
    if not value:
        raise ValueError("the user must attest that they may audit the target")
    return value


def normalize_domain(value: str) -> str:
    """Return a lowercase bare hostname, or raise ``ValueError``.

    This is a format check for a *domain* field, not a security control. It
    rejects URLs, ports, IP literals and single-label hosts such as ``localhost``,
    but performs no DNS resolution, so a valid-looking name may still resolve to
    a loopback or private address. DNS resolution, IP restrictions, redirect
    validation and SSRF protection are the crawler's responsibility (Stage 01).
    """
    domain = value.strip().lower().rstrip(".")
    if not domain or len(domain) > 253:
        raise ValueError("domain must be between 1 and 253 characters")
    if any(char in domain for char in "/?#@: "):
        raise ValueError("expected a bare domain such as 'example.com', not a URL")
    if not domain.isascii():
        raise ValueError("internationalized domains must be given in punycode")
    labels = domain.split(".")
    if len(labels) < 2:
        raise ValueError("domain must include a top-level domain, e.g. 'example.com'")
    if not all(_DOMAIN_LABEL.match(label) for label in labels):
        raise ValueError("domain contains an empty or invalid label")
    if labels[-1].isdigit():
        raise ValueError("IP addresses are not accepted; supply a domain name")
    return domain


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    ),
]
NonBlankStr = Annotated[str, AfterValidator(_reject_blank)]
Domain = Annotated[str, AfterValidator(normalize_domain)]
# StrictBool, not Literal[True]: Literal[True] also accepts 1, because 1 == True.
Attestation = Annotated[StrictBool, AfterValidator(_require_true)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# Held as a read-only MappingProxyType by its validator; serialized as a dict.
ReadOnlyStrMapping = Annotated[
    Mapping[str, str], PlainSerializer(dict, return_type=dict[str, str])
]

Severity = Literal["critical", "high", "medium", "low", "informational"]
FeatureStatus = Literal[
    "pass",
    "fail",
    "warning",
    "not_applicable",
    "not_measured",
    "error",
]
UNMEASURED_STATUSES: frozenset[str] = frozenset(
    {"not_applicable", "not_measured", "error"}
)

FetchOutcome = Literal[
    "success",
    "http_error",
    "redirect_not_followed",
    "transport_error",
]
TransportErrorType = Literal[
    "dns",
    "connection",
    "timeout",
    "tls",
    "too_many_redirects",
    "incomplete_response",
    "blocked_address",
    "blocked_port",
    "blocked_url",
    "other",
]
# Why a received 2xx/3xx/4xx/5xx response has no stored body (ADR-0008).
BodyNotStoredReason = Literal[
    "empty_response",
    "unsupported_content_type",
    "unsupported_content_encoding",
    "non_success_status",
]
# Why a received 3xx response was not followed (ADR-0009).
RedirectRefusalReason = Literal[
    "https_downgrade",
    "unsupported_scheme",
    "credentials_in_url",
    "blocked_address",
    "blocked_port",
    "cross_domain",
    "invalid_location",
    "missing_location",
    "not_a_redirect",
    "robots_disallowed",
]
_OUTCOME_STATUS_RANGES: dict[str, tuple[int, int]] = {
    "success": (200, 299),
    "redirect_not_followed": (300, 399),
    "http_error": (400, 599),
}
# Never persisted: they carry credentials or session state.
SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {"authorization", "cookie", "proxy-authorization", "set-cookie"}
)


class SchemaModel(BaseModel):
    """Base for shared contracts: strict, validated, immutable records.

    Unknown fields are errors, not silently dropped. Instances are frozen, so
    field reassignment raises a ``ValidationError``.

    ``model_copy(update=...)`` does **not** validate its updates, even on a frozen
    model, and can produce a record that breaks its invariants. To derive a
    changed record, validate a new instance instead::

        updated = type(record).model_validate(record.model_dump() | changes)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


SCHEMA_VERSION = 1


class VersionedRecord(SchemaModel):
    """Base for top-level artifact records, which declare their schema version.

    A reader refuses a record written under another version instead of guessing
    (ADR-0006). Nested value objects do not carry a version.
    """

    schema_version: Literal[1] = SCHEMA_VERSION


class AuditRequest(VersionedRecord):
    """An explicit request to audit one user-supplied target domain.

    The target is always supplied by the user; the product domain
    ``geoptimiser.me`` is never an implicit default.

    ``authorization_confirmed`` records the user's attestation that they own or
    are authorized to audit the target. It is not verified domain ownership and
    not a security control. Operational limits (such as how many competitors an
    audit may process) belong to configurable audit settings, not this schema.
    """

    audit_id: Identifier = Field(default_factory=lambda: f"aud_{uuid4().hex}")
    target_domain: Domain
    brand_name: NonBlankStr
    business_context: NonBlankStr
    target_audience: NonBlankStr
    competitor_domains: tuple[Domain, ...] = ()
    authorization_confirmed: Attestation = Field(
        description=(
            "User attestation of authorization to audit target_domain. "
            "Not verified ownership and not a security control."
        )
    )
    requested_at: UtcDatetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _check_competitors(self) -> Self:
        if self.target_domain in self.competitor_domains:
            raise ValueError("target_domain must not also be listed as a competitor")
        if len(set(self.competitor_domains)) != len(self.competitor_domains):
            raise ValueError("competitor_domains must not contain duplicates")
        return self


class RedirectHop(SchemaModel):
    """One redirect response that the fetcher followed."""

    url: HttpUrl
    status_code: int = Field(ge=300, le=399)
    # Raw Location header value: untrusted, possibly relative or malformed.
    location: NonBlankStr


class StoredBody(SchemaModel):
    """Reference to a response body kept in an artifact store, not inline."""

    ref: NonBlankStr
    sha256: Sha256Hex
    size_bytes: int = Field(ge=0)
    # True when the response was longer than the bytes stored (size limit hit).
    truncated: bool = False


class FetchTimings(SchemaModel):
    """Measured durations of one fetch, in milliseconds (additive, ADR-0024).

    ``None`` means *not measured*, with the reason in ``unmeasured``; it never means
    zero. DNS, connect, TLS, time-to-headers (``ttfb_ms``: request sent until the
    response status line and headers are parsed) and ``response_ms`` (request sent
    until the body has been read) describe the **final** exchange of the fetch, after
    any redirects. ``total_ms`` covers the whole fetch, all hops included. Durations
    are wall-clock on this host and include local scheduling, not just the network.
    """

    dns_ms: float | None = Field(default=None, ge=0)
    connect_ms: float | None = Field(default=None, ge=0)  # TCP handshake
    tls_ms: float | None = Field(default=None, ge=0)  # TLS handshake (https only)
    ttfb_ms: float | None = Field(default=None, ge=0)
    response_ms: float | None = Field(default=None, ge=0)
    total_ms: float = Field(ge=0)
    unmeasured: dict[str, str] = Field(default_factory=dict)


class FetchRecord(VersionedRecord):
    """One fetch attempt: a raw observation of what the network returned.

    A response without a stored body always has a reason (``body_not_stored_reason``
    on success): an empty, unsupported, or over-budget body is never confused with
    a missing measurement. ``StoredBody.truncated`` marks a size-limited body.

    ``outcome`` separates "no HTTP response was received" (``transport_error``,
    so ``status_code`` is ``None``) from "a response was received" (``success``,
    ``http_error`` or ``redirect_not_followed``, each with a status code). The
    body is referenced through ``StoredBody``; parsed content lives in
    ``PageDocument``.

    URL fields check format only and accept loopback and private-network hosts:
    deciding what may be fetched is the crawler's job (Stage 01), not this
    record's.
    """

    audit_id: Identifier
    fetch_id: Identifier
    requested_url: HttpUrl
    outcome: FetchOutcome
    status_code: int | None = None
    final_url: HttpUrl | None = None
    redirects: tuple[RedirectHop, ...] = ()
    headers: ReadOnlyStrMapping = Field(default_factory=dict, validate_default=True)
    body: StoredBody | None = None
    body_not_stored_reason: BodyNotStoredReason | None = None
    redirect_refusal_reason: RedirectRefusalReason | None = None
    error_type: TransportErrorType | None = None
    error_message: NonBlankStr | None = None
    started_at: UtcDatetime
    completed_at: UtcDatetime
    # None: this record predates timing, or the transport recorded none.
    timings: FetchTimings | None = None

    @field_validator("headers")
    @classmethod
    def _normalize_headers(cls, headers: Mapping[str, str]) -> Mapping[str, str]:
        normalized = {name.lower(): value for name, value in headers.items()}
        if len(normalized) != len(headers):
            raise ValueError("header names must be unique, ignoring case")
        sensitive = sorted(SENSITIVE_HEADERS & normalized.keys())
        if sensitive:
            raise ValueError(
                f"credential-bearing headers must not be stored: {sensitive}"
            )
        return MappingProxyType(normalized)

    @model_validator(mode="after")
    def _check_outcome_consistency(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        if self.redirects and self.redirects[0].url != self.requested_url:
            raise ValueError("the first redirect hop must start at requested_url")

        if self.outcome == "transport_error":
            if (
                self.status_code is not None
                or self.final_url is not None
                or self.headers
                or self.body is not None
                or self.body_not_stored_reason is not None
                or self.redirect_refusal_reason is not None
            ):
                raise ValueError(
                    "no HTTP response was received, so status_code, final_url, "
                    "headers, body and refusal/not-stored reasons must be empty"
                )
            if self.error_type is None or self.error_message is None:
                raise ValueError(
                    "outcome 'transport_error' requires error_type and error_message"
                )
            return self

        if self.error_type is not None or self.error_message is not None:
            raise ValueError(
                "error_type and error_message are only allowed for 'transport_error'"
            )
        if self.status_code is None or self.final_url is None:
            raise ValueError(
                f"outcome '{self.outcome}' means a response was received, so "
                "status_code and final_url are required"
            )
        if self.body is not None and self.body_not_stored_reason is not None:
            raise ValueError("a stored body cannot also have a not-stored reason")
        if (
            self.outcome == "success"
            and self.body is None
            and self.body_not_stored_reason is None
        ):
            raise ValueError(
                "a successful fetch without a body must say why it was not stored"
            )
        if (self.outcome == "redirect_not_followed") != (
            self.redirect_refusal_reason is not None
        ):
            raise ValueError(
                "redirect_refusal_reason is required for, and only allowed on, "
                "'redirect_not_followed'"
            )
        low, high = _OUTCOME_STATUS_RANGES[self.outcome]
        if not low <= self.status_code <= high:
            raise ValueError(
                f"outcome '{self.outcome}' requires a status code in {low}-{high}"
            )
        if not self.redirects and self.final_url != self.requested_url:
            raise ValueError("final_url differs from requested_url without redirects")
        return self


class Heading(SchemaModel):
    """One heading element, in document order."""

    level: int = Field(ge=1, le=6)
    text: str


TruncatedField = Literal[
    "title",
    "text",
    "headings",
    "links",
    "structured_data",
    "images",
    "anchors",
    "landmarks",
    "tables",
    "lists",
    "media",
]
# Why a JSON-LD block was present but produced no data. ``syntax_error``: a complete
# block that is not valid JSON (a site defect). ``unterminated``: the block never
# closed (a site defect in a complete document; a measurement limit if the stored
# body was cut). ``size_limit`` / ``nesting_limit``: skipped by an extraction limit
# (not a site defect).
JsonLdCause = Literal["syntax_error", "unterminated", "size_limit", "nesting_limit"]


class RenderSignals(SchemaModel):
    """Facts about the initial HTML that help tell a client-rendered shell from a
    page that really has no content. Observations only: the extractor never runs
    scripts, so nothing here says what a browser would show after rendering."""

    script_tags: int = Field(default=0, ge=0)
    external_scripts: int = Field(default=0, ge=0)
    inline_script_chars: int = Field(default=0, ge=0)
    # ids/attributes of typical app mount points, e.g. "#root", "#__next", "ng-app".
    mount_points: tuple[str, ...] = ()
    # First noscript text that mentions JavaScript ("You need to enable JavaScript").
    noscript_notice: str | None = None


# detail_level 1: Stage 02 fields only. 2: adds the "rich" fields below. Rich fields of
# a level-1 document are empty because they were not extracted, not because the page
# has none; checks must treat level 1 as "not measured".
RICH_DETAIL_LEVEL = 2


class ImageRef(SchemaModel):
    """One visible ``<img>``: its attributes and the text around it."""

    src: str | None = None  # absolute http(s) URL; "data:" for inline data URIs
    alt: str | None = None  # None: attribute absent; "": present but empty
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    loading: str | None = None
    decorative: bool = False  # empty alt, role=presentation/none, or aria-hidden
    caption: str | None = None  # <figcaption> text when inside a <figure>
    context_before: str = ""
    context_after: str = ""
    in_navigation: bool = False


class Anchor(SchemaModel):
    """One ``<a href>`` with a crawlable http(s) target."""

    href: str  # absolute, fragment removed
    text: str  # visible text, or the alt text of a contained image
    rel: tuple[str, ...] = ()  # lower-case tokens, e.g. ("nofollow", "ugc")
    # Relative to the page's own host (www and subdomains count as the same site).
    internal: bool
    region: Literal["content", "navigation"] = "content"
    has_image: bool = False


class Landmark(SchemaModel):
    """A landmark region, from a semantic element or an ARIA ``role``."""

    kind: Literal[
        "main",
        "navigation",
        "banner",
        "contentinfo",
        "complementary",
        "region",
        "article",
        "search",
    ]
    source: Literal["tag", "role"]
    labelled: bool = False  # has aria-label or aria-labelledby
    label: str | None = None  # aria-label text, if any
    text_chars: int = Field(default=0, ge=0)


class TableRef(SchemaModel):
    """One visible ``<table>``; cell text is bounded, the counts are not."""

    caption: str | None = None
    header_cells: tuple[str, ...] = ()  # <th> texts of the first row that has any
    rows: tuple[tuple[str, ...], ...] = ()  # cell texts of the first rows
    row_count: int = Field(default=0, ge=0)  # all <tr> elements
    column_count: int = Field(default=0, ge=0)  # widest row
    has_header_cells: bool = False
    presentational: bool = False  # role=presentation/none (a layout table)


class ListBlock(SchemaModel):
    """One ``<ul>``, ``<ol>`` or ``<dl>``; item text is bounded, the count is not."""

    kind: Literal["ul", "ol", "dl"]
    items: tuple[str, ...] = ()
    item_count: int = Field(default=0, ge=0)  # <li>, or <dt> for a definition list
    depth: int = Field(default=0, ge=0)  # nesting level, 0 for outermost
    in_navigation: bool = False


class MediaRef(SchemaModel):
    """Embedded audio/video, or a known video-platform iframe."""

    kind: Literal["video", "audio", "video_embed"]
    src: str | None = None
    # True/False for <video> (a captions/subtitles <track> exists); None for audio and
    # for embeds, whose captions cannot be seen from the page.
    has_captions: bool | None = None


class PageDocument(VersionedRecord):
    """Content extracted from one successful fetch by a versioned extractor.

    Derived data: it can be regenerated from the stored body by a newer
    extractor without re-fetching the page. ``url`` is the fetch's ``final_url``,
    and ``fetch_id`` joins to the ``FetchRecord`` (requested URL, headers, body
    reference) so a finding can cite the original page. Empty ``text`` is a valid
    measurement (the page has no extractable text), not an extraction failure;
    failures are recorded as ``ExtractionFailure``.

    ``None`` means "not present in the page"; an empty string means "present but
    blank". The canonical URL is a raw value observed in untrusted content (it may
    be relative or malformed); ``links`` are absolute http(s) URLs resolved against
    the page. ``truncated_fields`` lists fields cut by an extraction limit, and
    ``source_truncated`` says the stored body itself was cut at a crawl size limit:
    both mean "more existed than was measured", not "absent".
    """

    audit_id: Identifier
    document_id: Identifier
    fetch_id: Identifier
    url: HttpUrl
    extraction_version: Identifier
    title: str | None = None
    meta_description: str | None = None
    meta_robots: str | None = None
    language: str | None = None
    headings: tuple[Heading, ...] = ()
    text: str = ""
    links: tuple[str, ...] = ()
    canonical_url: str | None = None
    # Raw JSON-LD objects: the tuple is immutable, the dicts inside are not.
    structured_data: tuple[dict[str, Any], ...] = ()
    # JSON-LD blocks that were present but could not be parsed (not "no JSON-LD").
    structured_data_errors: int = Field(default=0, ge=0)
    # Cause of each unparsed block (counts add up to ``structured_data_errors``). Empty
    # for documents from an extractor that did not record causes: the cause is then
    # unknown, not "syntax error".
    structured_data_error_causes: dict[JsonLdCause, int] = Field(default_factory=dict)
    # Top-level and @graph JSON-LD @type values plus microdata itemtype values.
    structured_data_types: tuple[str, ...] = ()
    encoding: str | None = None
    source_truncated: bool = False
    truncated_fields: tuple[TruncatedField, ...] = ()
    # True: the parser saw the end of ``<head>`` (or the start of the body), so head
    # metadata that is absent really is absent. False: the document ended inside the
    # head. None: not recorded by the extractor that produced this document.
    head_complete: bool | None = None
    render_signals: RenderSignals | None = None
    detail_level: int = Field(default=1, ge=1)
    # -- rich fields (detail_level >= 2) --
    viewport: str | None = None  # <meta name=viewport> content
    charset_declared: str | None = None  # <meta charset> / http-equiv Content-Type
    images: tuple[ImageRef, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    landmarks: tuple[Landmark, ...] = ()
    semantic_counts: dict[str, int] = Field(default_factory=dict)
    # Approximate visible-text characters by region (not exact: whitespace-collapsed
    # per text chunk) and the characters hidden from view.
    boilerplate_chars: int = Field(default=0, ge=0)
    main_chars: int = Field(default=0, ge=0)
    hidden_chars: int = Field(default=0, ge=0)
    tables: tuple[TableRef, ...] = ()
    lists: tuple[ListBlock, ...] = ()
    media: tuple[MediaRef, ...] = ()
    extracted_at: UtcDatetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _check_detail_level(self) -> Self:
        if self.detail_level < RICH_DETAIL_LEVEL and (
            self.viewport is not None
            or self.charset_declared is not None
            or self.images
            or self.anchors
            or self.landmarks
            or self.semantic_counts
            or self.boilerplate_chars
            or self.main_chars
            or self.hidden_chars
            or self.tables
            or self.lists
            or self.media
        ):
            raise ValueError(
                "rich fields need detail_level >= 2: a level-1 document did not "
                "extract them, so it cannot carry values for them"
            )
        return self


class ExtractionFailure(VersionedRecord):
    """An extraction attempt that could not measure the page's content."""

    audit_id: Identifier
    fetch_id: Identifier
    extraction_version: Identifier
    error_type: Literal[
        "unsupported_content_type", "decode_error", "parse_error", "other"
    ]
    error_message: NonBlankStr
    occurred_at: UtcDatetime = Field(default_factory=_utc_now)


def check_extraction_source(
    fetch: FetchRecord, result: PageDocument | ExtractionFailure
) -> None:
    """Raise ``ValueError`` unless ``result`` may come from extracting ``fetch``.

    Extraction runs only on successful fetches with a stored body. HTTP error
    pages, unfollowed redirects and transport failures are never extracted.
    """
    if (result.audit_id, result.fetch_id) != (fetch.audit_id, fetch.fetch_id):
        raise ValueError("result does not reference this fetch")
    if fetch.outcome != "success" or fetch.body is None:
        raise ValueError("only successful fetches with a stored body are extractable")
    if isinstance(result, PageDocument) and result.url != fetch.final_url:
        raise ValueError("document url must equal the fetch's final_url")


class EvidenceRef(SchemaModel):
    """Traceable reference to a source passage or observation."""

    evidence_id: Identifier
    source_url: NonBlankStr
    snippet: NonBlankStr
    source_type: Literal[
        "website",
        "competitor",
        "ai_search",
        "research",
        "historical_audit",
    ]
    retrieved_at: UtcDatetime = Field(default_factory=_utc_now)
    # Optional locators into a stored passage (Stage 09). All ``None`` for evidence
    # that observes a measurement rather than quotes page text. When present,
    # ``snippet`` is exactly the ``[char_start, char_end)`` slice of the extracted
    # text of ``document_id``, which ``chunk_id`` lies in.
    audit_id: Identifier | None = None
    chunk_id: Identifier | None = None
    document_id: Identifier | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_locator(self) -> Self:
        located = (self.chunk_id, self.document_id, self.char_start, self.char_end)
        if all(v is None for v in located):
            return self
        if any(v is None for v in located) or self.audit_id is None:
            raise ValueError(
                "a passage locator needs audit_id, chunk_id, document_id and a "
                "complete char range"
            )
        assert self.char_start is not None and self.char_end is not None
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if self.char_end - self.char_start != len(self.snippet):
            raise ValueError("char range does not match the length of the snippet")
        return self


FeatureScope = Literal["page", "site", "audit"]
ImplementationStatus = Literal["implemented", "partial", "planned", "unavailable"]


class FeatureResult(VersionedRecord):
    """Result of one versioned GEO feature check.

    ``feature_version`` is the version of the check implementation and
    ``catalog_version`` the version of the catalog entry it ran under.
    ``scope`` says what was measured: one ``page`` (``subject_url`` and
    ``fetch_id`` identify it, ``document_id`` the extracted document), the
    whole ``site``, or the ``audit`` as a whole (including features that are
    not implemented yet, which are always ``not_measured``).
    """

    audit_id: Identifier
    feature_id: Identifier
    feature_version: int = Field(ge=1)
    category: NonBlankStr
    status: FeatureStatus
    observed_value: Any = None
    expected_value: Any = None
    severity: Severity = "informational"
    evidence: tuple[EvidenceRef, ...] = ()
    measurement_method: NonBlankStr
    limitations: tuple[str, ...] = ()
    error_message: str | None = None
    scope: FeatureScope = "audit"
    subject_url: NonBlankStr | None = None
    fetch_id: Identifier | None = None
    document_id: Identifier | None = None
    explanation: NonBlankStr | None = None
    # True when the criterion is a heuristic rather than an exact rule.
    is_heuristic: bool = False
    catalog_version: int | None = Field(default=None, ge=1)
    implementation_status: ImplementationStatus | None = None

    @model_validator(mode="after")
    def _check_status_consistency(self) -> Self:
        if self.status in UNMEASURED_STATUSES and self.observed_value is not None:
            raise ValueError(
                f"status '{self.status}' means nothing was measured, "
                "so observed_value must be None"
            )
        if self.status == "error" and not self.error_message:
            raise ValueError("status 'error' requires an error_message")
        if self.status != "error" and self.error_message is not None:
            raise ValueError("error_message is only allowed when status is 'error'")
        if self.scope == "page" and self.subject_url is None:
            raise ValueError("a page-scope result must name its subject_url")
        if self.implementation_status in ("planned", "unavailable") and (
            self.status != "not_measured"
        ):
            raise ValueError(
                f"a '{self.implementation_status}' feature has no working check, "
                "so its only honest status is 'not_measured'"
            )
        return self


class Citation(SchemaModel):
    """A citation surfaced by an AI-search provider."""

    url: NonBlankStr
    title: str | None = None


class VisibilityObservation(VersionedRecord):
    """One provider response for one versioned benchmark query.

    ``brand_mentioned`` is ``None`` until the response has been annotated, and
    must stay ``None`` when collection did not succeed.
    """

    audit_id: Identifier
    query_id: Identifier
    query_set_version: int = Field(ge=1)
    provider: NonBlankStr
    model: NonBlankStr
    query: NonBlankStr
    response_text: str = ""
    citations: tuple[Citation, ...] = ()
    brand_mentioned: bool | None = None
    competitors_mentioned: tuple[str, ...] = ()
    observed_at: UtcDatetime = Field(default_factory=_utc_now)
    collection_status: Literal["success", "error", "skipped"] = "success"
    error_message: str | None = None
    # Where the answer came from: a real provider ("live"), a scripted test double
    # ("mock") or a replayed recording ("fixture"). None: not recorded (never "live").
    origin: Literal["live", "mock", "fixture"] | None = None
    repeat_index: int = Field(default=0, ge=0)  # 0-based repeat of the same query

    @model_validator(mode="after")
    def _check_collection_consistency(self) -> Self:
        if self.collection_status == "error" and not self.error_message:
            raise ValueError("collection_status 'error' requires an error_message")
        if self.collection_status == "success" and self.error_message is not None:
            raise ValueError("error_message is not allowed for a successful collection")
        if self.collection_status != "success" and (
            self.response_text
            or self.citations
            or self.brand_mentioned is not None
            or self.competitors_mentioned
        ):
            raise ValueError(
                "an unsuccessful collection must not carry a response or "
                "annotations; a missing observation is not a negative result"
            )
        return self


class Finding(VersionedRecord):
    """An evidence-linked diagnostic conclusion (ADR-0002).

    ``basis`` keeps deterministic measurements, heuristic rules and model
    judgements distinguishable, as required by the project specification.
    """

    audit_id: Identifier
    finding_id: Identifier
    title: NonBlankStr
    description: NonBlankStr
    category: NonBlankStr
    severity: Severity
    basis: Literal["measured", "heuristic", "model_judgement"]
    feature_ids: tuple[Identifier, ...] = ()
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    measurement_method: NonBlankStr
    confidence: float = Field(ge=0, le=1)
    limitations: tuple[NonBlankStr, ...] = ()
    verification_criteria: tuple[NonBlankStr, ...] = Field(min_length=1)
    # Guidance only; reviewable Recommendations are produced in Stage 10.
    remediation: NonBlankStr | None = None
    created_at: UtcDatetime = Field(default_factory=_utc_now)


class Recommendation(VersionedRecord):
    """An evidence-backed, reviewable optimization recommendation.

    Every recommendation originates from at least one ``Finding`` and also cites
    evidence directly; neither link is optional. Only the expected *direction* of
    impact is recorded: the platform never promises a specific visibility or
    citation increase.
    """

    audit_id: Identifier
    recommendation_id: Identifier
    title: NonBlankStr
    rationale: NonBlankStr
    proposed_change: NonBlankStr
    finding_ids: tuple[Identifier, ...] = Field(min_length=1)
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    expected_impact_direction: Literal["positive", "neutral", "negative", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    priority: Literal["P0", "P1", "P2", "P3"]
    estimated_effort: Literal["small", "medium", "large"]
    verification_plan: tuple[NonBlankStr, ...] = Field(min_length=1)
    created_at: UtcDatetime = Field(default_factory=_utc_now)


class Chunk(VersionedRecord):
    """A contiguous span of one ``PageDocument.text``, the unit of retrieval.

    Derived data (Stage 07). ``text`` is exactly ``document.text[char_start:char_end]``
    (half-open, Python string indices), so a chunk is evidence that can be located in
    the source rather than a paraphrase of it. ``heading_path`` is the chain of
    headings (outermost first) that was in force at ``char_start``. ``overlap_chars``
    is how many leading characters repeat the end of the previous chunk of the same
    section; every other character belongs to exactly one chunk.
    ``source_truncated`` is copied from the document: the stored body was cut, so the
    page may continue beyond this chunk's source.
    """

    audit_id: Identifier
    chunk_id: Identifier
    document_id: Identifier
    fetch_id: Identifier
    url: HttpUrl
    chunker_version: int = Field(ge=1)
    ordinal: int = Field(ge=0)
    heading_path: tuple[str, ...] = ()
    text: NonBlankStr
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    text_sha256: Sha256Hex
    overlap_chars: int = Field(default=0, ge=0)
    source_truncated: bool = False

    @model_validator(mode="after")
    def _check_span(self) -> Self:
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("char range does not match the length of text")
        if self.overlap_chars >= len(self.text):
            raise ValueError("overlap_chars must be smaller than the chunk")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.text_sha256:
            raise ValueError("text_sha256 does not match text")
        return self
