"""Collect provider answers for a query set into ``VisibilityObservation`` records.

Raw observations only: no annotation happens here (Stage 06). Every attempt becomes a
record, including failures, so a missing answer is never confused with a negative one.
"""

import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from geoptimiser.benchmark.models import QuerySet
from geoptimiser.jsonl import JsonlWriter
from geoptimiser.schemas import (
    Identifier,
    SchemaModel,
    UtcDatetime,
    VersionedRecord,
    VisibilityObservation,
)
from geoptimiser.visibility.providers import (
    AnswerProvider,
    ProviderError,
    ProviderOrigin,
    ProviderUnavailable,
)

MAX_RESPONSE_CHARS = 20_000
MAX_CITATIONS = 50
_MAX_MESSAGE = 300


class DraftQuerySet(ValueError):
    """The query set is an unreviewed draft and drafts were not explicitly allowed."""


class BudgetExceeded(ValueError):
    """The planned number of provider calls exceeds ``max_calls``."""


class CollectionConfig(SchemaModel):
    repeats: int = Field(default=1, ge=1, le=10)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_calls: int = Field(default=1_000, ge=1)
    allow_draft_queries: bool = False
    max_response_chars: int = Field(default=MAX_RESPONSE_CHARS, ge=1)
    max_citations: int = Field(default=MAX_CITATIONS, ge=1)


class ProviderInfo(SchemaModel):
    name: str
    model: str
    origin: ProviderOrigin


class ProviderCounts(SchemaModel):
    provider: str
    model: str
    origin: ProviderOrigin
    attempted: int
    success: int
    error: int
    skipped: int


class CollectionManifest(VersionedRecord):
    """What was asked, of whom, and how it went (no response text)."""

    audit_id: Identifier
    query_set_name: Identifier
    query_set_version: int
    query_set_review_status: Literal["draft", "reviewed"]
    repeats: int
    planned_calls: int
    providers: tuple[ProviderCounts, ...]
    responses_clipped: int
    started_at: UtcDatetime
    completed_at: UtcDatetime


@dataclass(frozen=True)
class CollectionResult:
    observations: tuple[VisibilityObservation, ...]
    manifest: CollectionManifest


def _safe_message(prefix: str, error: Exception) -> str:
    text = str(error).strip() if isinstance(error, ProviderError) else ""
    return (f"{prefix}: {text}" if text else prefix)[:_MAX_MESSAGE]


def collect_visibility(
    audit_id: str,
    queries: QuerySet,
    providers: Sequence[AnswerProvider],
    config: CollectionConfig | None = None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sink: JsonlWriter | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> CollectionResult:
    """Ask every provider every query ``repeats`` times, sequentially and boundedly.

    Refuses (before any call) a draft query set unless ``allow_draft_queries`` is set,
    and a plan larger than ``max_calls``. There are no retries: one attempt per call.
    A provider whose ``check_available`` fails is *skipped* for all its calls; a
    provider error becomes an ``error`` record; an unexpected exception from an adapter
    is contained the same way. ``KeyboardInterrupt`` is not caught; records written to
    ``sink`` before it are kept.
    """
    config = config or CollectionConfig()
    if queries.review_status != "reviewed" and not config.allow_draft_queries:
        raise DraftQuerySet(
            f"query set {queries.name} v{queries.version} is a draft; review it or set "
            "allow_draft_queries"
        )
    planned = len(providers) * len(queries.queries) * config.repeats
    if planned > config.max_calls:
        raise BudgetExceeded(
            f"{planned} planned calls exceed max_calls={config.max_calls}"
        )
    started = clock()
    observations: list[VisibilityObservation] = []
    clipped = 0
    del monotonic  # reserved: providers enforce the per-call timeout themselves

    for provider in providers:
        unavailable: ProviderUnavailable | None = None
        try:
            provider.check_available()
        except ProviderUnavailable as exc:
            unavailable = exc
        for query in queries.queries:
            for repeat in range(config.repeats):
                base = {
                    "audit_id": audit_id,
                    "query_id": query.query_id,
                    "query_set_version": queries.version,
                    "provider": provider.name,
                    "model": provider.model,
                    "query": query.text,
                    "origin": provider.origin,
                    "repeat_index": repeat,
                }
                if unavailable is not None:
                    fields: dict[str, Any] = {
                        "collection_status": "skipped",
                        "error_message": _safe_message(
                            "provider unavailable", unavailable
                        ),
                    }
                else:
                    fields, was_clipped = _call(provider, query.text, config)
                    clipped += was_clipped
                record = VisibilityObservation.model_validate(
                    base | fields | {"observed_at": clock()}
                )
                observations.append(record)
                if sink is not None:
                    sink.write(record)

    counts = Counter(
        (o.provider, o.model, o.origin, o.collection_status) for o in observations
    )
    summary = []
    for p in providers:
        key = (p.name, p.model, p.origin)
        by_status = {st: counts[(*key, st)] for st in ("success", "error", "skipped")}
        summary.append(
            ProviderCounts(
                provider=p.name,
                model=p.model,
                origin=p.origin,
                attempted=sum(by_status.values()),
                **by_status,
            )
        )
    manifest = CollectionManifest(
        audit_id=audit_id,
        query_set_name=queries.name,
        query_set_version=queries.version,
        query_set_review_status=queries.review_status,
        repeats=config.repeats,
        planned_calls=planned,
        providers=tuple(summary),
        responses_clipped=clipped,
        started_at=started,
        completed_at=clock(),
    )
    return CollectionResult(tuple(observations), manifest)


def _call(
    provider: AnswerProvider, query: str, config: CollectionConfig
) -> tuple[dict[str, Any], int]:
    try:
        answer = provider.answer(query, timeout_seconds=config.timeout_seconds)
    except ProviderUnavailable as exc:
        return {
            "collection_status": "skipped",
            "error_message": _safe_message("provider unavailable", exc),
        }, 0
    except ProviderError as exc:
        label = type(exc).__name__
        return {
            "collection_status": "error",
            "error_message": _safe_message(label, exc),
        }, 0
    except Exception as exc:  # an adapter bug must not stop the collection
        return {
            "collection_status": "error",
            "error_message": f"unexpected {type(exc).__name__}",
        }, 0
    text = answer.text
    was_clipped = int(len(text) > config.max_response_chars)
    return {
        "collection_status": "success",
        "response_text": text[: config.max_response_chars],
        "citations": answer.citations[: config.max_citations],
    }, was_clipped
