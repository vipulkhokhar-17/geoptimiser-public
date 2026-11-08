"""Stored fetches to ``PageDocument`` / ``ExtractionFailure`` records."""

import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from geoptimiser.crawler.storage import BodyStore
from geoptimiser.extraction.artifacts import ExtractionWriter
from geoptimiser.extraction.config import (
    DETAIL_LEVEL,
    EXTRACTION_VERSION,
    ExtractionConfig,
)
from geoptimiser.extraction.decode import (
    HTML_TYPES,
    DecodeError,
    decode_html,
    media_type,
)
from geoptimiser.extraction.parser import ParseLimitExceeded, parse_html
from geoptimiser.schemas import (
    ExtractionFailure,
    FetchRecord,
    Heading,
    Identifier,
    PageDocument,
    RenderSignals,
    check_extraction_source,
)

SkipReason = Literal["not_successful_fetch", "no_stored_body", "robots_txt"]
FailureType = Literal[
    "unsupported_content_type", "decode_error", "parse_error", "other"
]
_TRUNCATION_ORDER = (
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
)


class SkippedFetch(BaseModel):
    """A fetch that is not a page to extract: no extraction was attempted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: Identifier
    fetch_id: Identifier
    reason: SkipReason


@dataclass(frozen=True)
class ExtractionResult:
    documents: tuple[PageDocument, ...]
    failures: tuple[ExtractionFailure, ...]
    skipped: tuple[SkippedFetch, ...]


class _Failed(Exception):
    def __init__(self, error_type: FailureType, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def skip_reason(fetch: FetchRecord) -> SkipReason | None:
    """Why ``fetch`` is not extracted, or ``None`` if it is a page to extract.

    Only successful fetches with a stored body are extractable
    (``check_extraction_source``). The crawler's own ``robots.txt`` fetches are
    plain text, not pages, and are recognised by their final path.
    """
    if fetch.outcome != "success":
        return "not_successful_fetch"
    if fetch.body is None:
        return "no_stored_body"
    if fetch.final_url is not None and fetch.final_url.path == "/robots.txt":
        return "robots_txt"
    return None


def _load_html(fetch: FetchRecord, store: BodyStore, config: ExtractionConfig) -> bytes:
    body = fetch.body
    assert body is not None
    if body.size_bytes > config.max_input_bytes:
        raise _Failed("other", f"stored body exceeds {config.max_input_bytes} bytes")
    try:
        data = store.get(body.ref)
    except FileNotFoundError:
        raise _Failed("other", "stored body not found") from None
    except ValueError:  # the store re-hashes on read and rejects a changed file
        raise _Failed("other", "stored body failed its integrity check") from None
    except OSError as exc:
        raise _Failed("other", f"stored body unreadable: {type(exc).__name__}") from exc
    if len(data) != body.size_bytes or hashlib.sha256(data).hexdigest() != body.sha256:
        raise _Failed("other", "stored body failed its integrity check (size/hash)")
    return data


def _extract(
    fetch: FetchRecord,
    store: BodyStore,
    config: ExtractionConfig,
    now: datetime,
) -> PageDocument:
    assert fetch.body is not None and fetch.final_url is not None
    content_type = fetch.headers.get("content-type")
    if media_type(content_type) not in HTML_TYPES:
        raise _Failed(
            "unsupported_content_type",
            f"{media_type(content_type) or 'missing content type'} is not HTML",
        )
    data = _load_html(fetch, store, config)
    try:
        decoded = decode_html(
            data, content_type, max_replacement_ratio=config.max_replacement_ratio
        )
    except DecodeError as exc:
        raise _Failed("decode_error", str(exc)) from exc
    try:
        page = parse_html(decoded.text, str(fetch.final_url), config)
    except ParseLimitExceeded:
        raise _Failed(
            "parse_error", f"exceeded {config.max_seconds}s time limit"
        ) from None
    except Exception as exc:  # the standard parser can raise on pathological input
        raise _Failed("parse_error", f"parser raised {type(exc).__name__}") from exc
    return PageDocument(
        audit_id=fetch.audit_id,
        document_id=f"doc:{fetch.fetch_id}:{EXTRACTION_VERSION}",
        fetch_id=fetch.fetch_id,
        url=fetch.final_url,
        extraction_version=EXTRACTION_VERSION,
        title=page.title,
        meta_description=page.meta_description,
        meta_robots=page.meta_robots,
        language=page.language,
        headings=tuple(Heading(level=lv, text=tx) for lv, tx in page.headings),
        text=page.text,
        links=tuple(page.links),
        canonical_url=page.canonical_url,
        structured_data=tuple(page.structured_data),
        structured_data_errors=page.structured_data_errors,
        structured_data_error_causes=page.structured_data_error_causes,  # type: ignore[arg-type]
        structured_data_types=tuple(page.structured_data_types),
        encoding=decoded.encoding,
        source_truncated=fetch.body.truncated,
        truncated_fields=tuple(f for f in _TRUNCATION_ORDER if f in page.truncated),
        head_complete=page.head_complete,
        render_signals=RenderSignals(
            script_tags=page.script_tags,
            external_scripts=page.external_scripts,
            inline_script_chars=page.inline_script_chars,
            mount_points=tuple(page.mount_points),
            noscript_notice=page.noscript_notice,
        ),
        detail_level=DETAIL_LEVEL,
        viewport=page.viewport,
        charset_declared=page.charset_declared,
        images=tuple(page.images),
        anchors=tuple(page.anchors),
        landmarks=tuple(page.landmarks),
        semantic_counts=page.semantic_counts,
        boilerplate_chars=page.boilerplate_chars,
        main_chars=page.main_chars,
        hidden_chars=page.hidden_chars,
        tables=tuple(page.tables),
        lists=tuple(page.lists),
        media=tuple(page.media),
        extracted_at=now,
    )


def extract_fetch(
    fetch: FetchRecord,
    store: BodyStore,
    config: ExtractionConfig | None = None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PageDocument | ExtractionFailure:
    """Extract one fetch. Every failure mode is a returned ``ExtractionFailure``.

    Raises ``ValueError`` if ``fetch`` is not extractable at all (see
    ``skip_reason``): that is a caller error, not a page-level failure.
    """
    reason = skip_reason(fetch)
    if reason is not None:
        raise ValueError(f"fetch {fetch.fetch_id} is not extractable: {reason}")
    config = config or ExtractionConfig()
    now = clock()
    try:
        result: PageDocument | ExtractionFailure = _extract(fetch, store, config, now)
    except _Failed as failed:
        result = _failure(fetch, failed.error_type, str(failed), now)
    except Exception as exc:  # one bad page must never stop the audit
        result = _failure(fetch, "other", f"unexpected {type(exc).__name__}", now)
    check_extraction_source(fetch, result)
    return result


def _failure(
    fetch: FetchRecord, error_type: FailureType, message: str, now: datetime
) -> ExtractionFailure:
    return ExtractionFailure(
        audit_id=fetch.audit_id,
        fetch_id=fetch.fetch_id,
        extraction_version=EXTRACTION_VERSION,
        error_type=error_type,
        error_message=message,
        occurred_at=now,
    )


def extract_all(
    fetches: Iterable[FetchRecord],
    store: BodyStore,
    config: ExtractionConfig | None = None,
    *,
    sink: ExtractionWriter | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    """Extract every page among ``fetches``; with a ``sink``, write each record
    durably as it is produced so an interrupted run keeps its progress."""
    documents: list[PageDocument] = []
    failures: list[ExtractionFailure] = []
    skipped: list[SkippedFetch] = []
    started = time.monotonic()
    for fetch in fetches:
        reason = skip_reason(fetch)
        if reason is not None:
            skip = SkippedFetch(
                audit_id=fetch.audit_id, fetch_id=fetch.fetch_id, reason=reason
            )
            skipped.append(skip)
            if sink:
                sink.write_skipped(skip)
            continue
        result = extract_fetch(fetch, store, config, clock=clock)
        if isinstance(result, PageDocument):
            documents.append(result)
            if sink:
                sink.write_document(result)
        else:
            failures.append(result)
            if sink:
                sink.write_failure(result)
    if sink:
        sink.write_summary(
            {
                "extraction_version": EXTRACTION_VERSION,
                "config": (config or ExtractionConfig()).model_dump(mode="json"),
                "documents": len(documents),
                "failures": len(failures),
                "skipped": len(skipped),
                "failures_by_type": {
                    t: sum(1 for f in failures if f.error_type == t)
                    for t in sorted({f.error_type for f in failures})
                },
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        )
    return ExtractionResult(tuple(documents), tuple(failures), tuple(skipped))
