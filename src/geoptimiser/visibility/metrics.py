"""Visibility metrics from annotated observations (Stage 06, ADR-0017).

Every rate carries its numerator, denominator and a Wilson 95% interval. A rate whose
denominator is zero is ``not_measured`` (``rate=None``), never 0. Failed and skipped
attempts are counted but never enter a denominator. Groups never mix origins, and only
``live`` groups are real measurements.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from geoptimiser.jsonl import write_json_atomic
from geoptimiser.schemas import (
    Identifier,
    SchemaModel,
    VersionedRecord,
    VisibilityObservation,
)
from geoptimiser.visibility.annotate import (
    ANNOTATOR_VERSION,
    BrandSpec,
    annotate_all,
    cited_urls,
)
from geoptimiser.visibility.collect import CollectionManifest

METRICS_VERSION = 1
_Z = 1.96  # 95% two-sided
_NO_ANSWERS = "no successful answers"


class RateEstimate(SchemaModel):
    numerator: int
    denominator: int
    rate: float | None
    ci_low: float | None
    ci_high: float | None
    status: Literal["measured", "not_measured"]
    reason: str | None = None


def wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    """Wilson score interval for a proportion (95%)."""
    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("need 0 <= successes <= trials and trials > 0")
    p = successes / trials
    z2 = _Z * _Z
    denom = 1 + z2 / trials
    centre = (p + z2 / (2 * trials)) / denom
    half = _Z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(numerator: int, denominator: int, why_not: str) -> RateEstimate:
    if denominator == 0:
        return RateEstimate(
            numerator=0, denominator=0, rate=None, ci_low=None, ci_high=None,
            status="not_measured", reason=why_not,
        )  # fmt: skip
    low, high = wilson_interval(numerator, denominator)
    return RateEstimate(
        numerator=numerator, denominator=denominator, rate=numerator / denominator,
        ci_low=round(low, 6), ci_high=round(high, 6), status="measured",
    )  # fmt: skip


class GroupMetrics(SchemaModel):
    provider: str
    model: str
    origin: Literal["live", "mock", "fixture", "unrecorded"]
    real_measurement: bool
    attempted: int
    succeeded: int
    errors: int
    skipped: int
    query_coverage: RateEstimate  # queries with >= 1 successful answer / queries asked
    mention_rate: RateEstimate  # answers naming the brand / successful answers
    citation_rate: (
        RateEstimate  # answers citing the brand's domain / successful answers
    )
    unique_cited_pages: int
    cited_pages: tuple[str, ...]
    competitor_mentions: dict[str, int]
    consistency: (
        RateEstimate  # queries with an identical mention outcome across repeats
    )


class VisibilityMetrics(VersionedRecord):
    metrics_version: int = METRICS_VERSION
    annotator_version: int = ANNOTATOR_VERSION
    audit_id: Identifier
    brand: str
    query_set_name: str | None
    query_set_version: int | None
    query_set_review_status: Literal["draft", "reviewed"] | None
    groups: tuple[GroupMetrics, ...]
    has_real_measurements: bool
    notes: tuple[str, ...]


def compute_metrics(
    observations: Sequence[VisibilityObservation],
    spec: BrandSpec,
    audit_id: str,
    manifest: CollectionManifest | None = None,
) -> VisibilityMetrics:
    """Annotate (idempotently) and aggregate observations per provider/model/origin."""
    annotated = annotate_all(observations, spec)
    buckets: dict[tuple[str, str, str], list[VisibilityObservation]] = defaultdict(list)
    for obs in annotated:
        buckets[(obs.provider, obs.model, obs.origin or "unrecorded")].append(obs)

    groups = []
    for (provider, model, origin), items in sorted(buckets.items()):
        ok = [o for o in items if o.collection_status == "success"]
        asked = {o.query_id for o in items}
        answered = {o.query_id for o in ok}
        mentioned = sum(1 for o in ok if o.brand_mentioned)
        cites = [(o, cited_urls(o, spec.brand)) for o in ok]
        pages = sorted({u for _, urls in cites for u in urls})
        competitors: dict[str, int] = {c.name: 0 for c in spec.competitors}
        for o in ok:
            for name in o.competitors_mentioned:
                competitors[name] += 1
        by_query: dict[str, set[bool]] = defaultdict(set)
        runs: dict[str, int] = defaultdict(int)
        for o in ok:
            by_query[o.query_id].add(bool(o.brand_mentioned))
            runs[o.query_id] += 1
        repeated = [q for q, n in runs.items() if n >= 2]
        groups.append(
            GroupMetrics(
                provider=provider, model=model, origin=origin,  # type: ignore[arg-type]
                real_measurement=origin == "live",
                attempted=len(items), succeeded=len(ok),
                errors=sum(1 for o in items if o.collection_status == "error"),
                skipped=sum(1 for o in items if o.collection_status == "skipped"),
                query_coverage=rate(len(answered), len(asked), "no queries were asked"),
                mention_rate=rate(mentioned, len(ok), _NO_ANSWERS),
                citation_rate=rate(sum(1 for _, u in cites if u), len(ok), _NO_ANSWERS),
                unique_cited_pages=len(pages), cited_pages=tuple(pages),
                competitor_mentions=competitors,
                consistency=rate(
                    sum(1 for q in repeated if len(by_query[q]) == 1), len(repeated),
                    "no query was answered at least twice",
                ),
            )
        )  # fmt: skip
    live = any(g.real_measurement and g.succeeded for g in groups)
    notes = []
    if not groups:
        notes.append("No observations were provided.")
    elif not live:
        notes.append(
            "No successful live-provider observations: every figure comes from mock or "
            "fixture sources, or from attempts that failed or were skipped. None of it "
            "measures real AI-search visibility."
        )
    if manifest and manifest.query_set_review_status == "draft":
        notes.append("The query set was an unreviewed draft.")
    return VisibilityMetrics(
        audit_id=audit_id,
        brand=spec.brand.name,
        query_set_name=manifest.query_set_name if manifest else None,
        query_set_version=manifest.query_set_version if manifest else None,
        query_set_review_status=manifest.query_set_review_status if manifest else None,
        groups=tuple(groups),
        has_real_measurements=live,
        notes=tuple(notes),
    )


def write_metrics(path: Path, metrics: VisibilityMetrics) -> None:
    """Write ``metrics`` as JSON; refuses to overwrite an existing file."""
    write_json_atomic(path, metrics.model_dump(mode="json"))
