"""Run checks and turn their outcomes into validated ``FeatureResult`` records."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from geoptimiser.features.catalog import CATALOG_VERSION, FeatureDefinition
from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.context import Ctx
from geoptimiser.features.evidence import apply_evidence_policy
from geoptimiser.features.inputs import AuditInputs, PageContext
from geoptimiser.features.outcome import Obs, Outcome
from geoptimiser.features.registry import Check, FeatureRegistry, default_registry
from geoptimiser.schemas import RICH_DETAIL_LEVEL, EvidenceRef, FeatureResult

_DEFAULT_LIMITATION = "None beyond the stated method."


def evidence_id(feature_id: str, obs: Obs) -> str:
    """Deterministic ID: the same observation of the same feature always matches."""
    digest = hashlib.sha256(f"{feature_id}|{obs.url}|{obs.text}".encode()).hexdigest()
    return f"ev_{feature_id}_{digest[:16]}"


def _evidence(
    feature_id: str, observations: Sequence[Obs], retrieved_at: datetime | None
) -> tuple[EvidenceRef, ...]:
    refs: dict[str, EvidenceRef] = {}
    for obs in observations:
        ref = EvidenceRef(
            evidence_id=evidence_id(feature_id, obs),
            source_url=obs.url,
            snippet=obs.text,
            source_type="website",
            **({"retrieved_at": retrieved_at} if retrieved_at else {}),
        )
        refs.setdefault(ref.evidence_id, ref)
    return tuple(refs.values())


def _limitations(defn: FeatureDefinition, outcome: Outcome | None) -> tuple[str, ...]:
    extra = outcome.limitations if outcome else ()
    return tuple(x for x in (*defn.limitations, *extra) if x != _DEFAULT_LIMITATION)


def _result(
    defn: FeatureDefinition,
    check: Check | None,
    inputs: AuditInputs,
    outcome: Outcome,
    *,
    page: PageContext | None = None,
    subject: str | None = None,
    error: str | None = None,
) -> FeatureResult:
    status = "error" if error else outcome.status
    measured = status in ("pass", "fail", "warning")
    retrieved = page.fetch.completed_at if page else inputs.observed_at
    scope = "page" if page else ("site" if check else "audit")
    return FeatureResult(
        audit_id=inputs.audit_id,
        feature_id=defn.feature_id,
        feature_version=check.version if check else 1,
        category=defn.category,
        status=status,
        observed_value=outcome.observed if measured else None,
        expected_value=outcome.expected if measured else None,
        severity=(outcome.severity or defn.base_severity)
        if status in ("fail", "warning")
        else "informational",
        evidence=_evidence(defn.feature_id, outcome.evidence, retrieved),
        measurement_method=defn.method,
        limitations=_limitations(defn, outcome),
        error_message=error,
        scope=scope,
        subject_url=page.url if page else subject,
        fetch_id=page.fetch.fetch_id if page else None,
        document_id=page.document.document_id if page and page.document else None,
        explanation=outcome.explanation,
        is_heuristic=defn.is_heuristic,
        catalog_version=CATALOG_VERSION,
        implementation_status=defn.implementation_status,
    )


def _unavailable_reason(page: PageContext) -> str:
    if page.document is not None:
        return ""
    fetch = page.fetch
    if fetch.outcome == "http_error":
        return (
            f"No extracted document: the fetch ended as http_error (HTTP "
            f"{fetch.status_code}); the error response is not a page to analyse."
        )
    if fetch.outcome != "success":
        return f"No extracted document: the fetch ended as {fetch.outcome}."
    if fetch.body is None and fetch.body_not_stored_reason == "empty_response":
        return (
            "No extracted document: the server answered HTTP "
            f"{fetch.status_code} with an empty response body (nothing to extract)."
        )
    if fetch.body is None and fetch.body_not_stored_reason:
        return (
            "No extracted document: the response body was not stored "
            f"({fetch.body_not_stored_reason})."
        )
    if page.failure is not None:
        return (
            "No extracted document: extraction failed "
            f"({page.failure.error_type}: {page.failure.error_message})."
        )
    return "No extracted document: extraction was not run for this page."


def _normalise(outcome: Outcome) -> Outcome:
    """Make observed/expected values JSON-native (tuples become lists) or raise."""
    return replace(
        outcome,
        observed=json.loads(json.dumps(outcome.observed)),
        expected=json.loads(json.dumps(outcome.expected)),
    )


def _guarded(defn, check, inputs, page, run) -> list[FeatureResult]:  # type: ignore[no-untyped-def]
    """Run one check call; any exception becomes an explicit ``error`` result."""
    try:
        outcome = _normalise(run())
        if outcome.status in ("fail", "warning") and not outcome.evidence:
            raise ValueError("a failing result must cite at least one observation")
    except Exception as exc:  # a broken check must not hide the other results
        message = f"{type(exc).__name__}: {exc}"[:300]
        empty = Outcome("error", "The check raised an exception.")
        return [_result(defn, check, inputs, empty, page=page, error=message)]
    return [_result(defn, check, inputs, outcome, page=page)]


def run_feature(
    feature_id: str,
    inputs: AuditInputs,
    config: FeatureConfig | None = None,
    registry: FeatureRegistry | None = None,
) -> list[FeatureResult]:
    """Execute one feature. Features without a check yield one ``not_measured`` result."""
    registry = registry or default_registry()
    config = config or FeatureConfig()
    defn = registry.catalog.get(feature_id)
    check = registry.checks.get(feature_id)
    if check is None:
        reason = "; ".join(defn.blocked_by)
        outcome = Outcome(
            "not_measured",
            f"Not measured: the feature is {defn.implementation_status} ({reason})",
        )
        return [_result(defn, None, inputs, outcome)]
    ctx = Ctx(inputs, config)
    results: list[FeatureResult] = []
    if check.scope == "page":
        for page in inputs.pages:
            needs_doc = check.requires in ("document", "rich_document")
            if needs_doc and page.document is None:
                outcome = Outcome("not_measured", _unavailable_reason(page))
                results.append(_result(defn, check, inputs, outcome, page=page))
            elif (
                check.requires == "rich_document"
                and page.document is not None
                and page.document.detail_level < RICH_DETAIL_LEVEL
            ):
                outcome = Outcome(
                    "not_measured",
                    "The document was extracted at detail level "
                    f"{page.document.detail_level}; re-run extraction (level "
                    f"{RICH_DETAIL_LEVEL}) to measure this.",
                )
                results.append(_result(defn, check, inputs, outcome, page=page))
            else:
                results += _guarded(
                    defn,
                    check,
                    inputs,
                    page,
                    lambda p=page: apply_evidence_policy(
                        defn.feature_id, check.fn(p, ctx), p, ctx.config
                    ),
                )
        return results
    try:
        produced = check.fn(ctx)
        produced = (
            [(u, _normalise(o)) for u, o in produced]
            if isinstance(produced, list)
            else _normalise(produced)
        )
    except Exception as exc:
        empty = Outcome("error", "The check raised an exception.")
        return [
            _result(
                defn, check, inputs, empty, error=f"{type(exc).__name__}: {exc}"[:300]
            )
        ]
    units = produced if isinstance(produced, list) else [(None, produced)]
    for subject, outcome in units:
        if outcome.status == "fail" and not outcome.evidence:
            outcome = Outcome("error", "The check returned a failure without evidence.")
            results.append(
                _result(
                    defn,
                    check,
                    inputs,
                    outcome,
                    subject=subject,
                    error="failure without evidence",
                )
            )
        else:
            results.append(_result(defn, check, inputs, outcome, subject=subject))
    return results


def run_category(
    code: str,
    inputs: AuditInputs,
    config: FeatureConfig | None = None,
    registry: FeatureRegistry | None = None,
) -> list[FeatureResult]:
    registry = registry or default_registry()
    return [
        r
        for f in registry.catalog.by_category(code)
        for r in run_feature(f.feature_id, inputs, config, registry)
    ]


def run_all(
    inputs: AuditInputs,
    config: FeatureConfig | None = None,
    registry: FeatureRegistry | None = None,
) -> list[FeatureResult]:
    registry = registry or default_registry()
    return [
        r
        for f in registry.catalog.features
        for r in run_feature(f.feature_id, inputs, config, registry)
    ]


@dataclass(frozen=True)
class FeatureRunSummary:
    results: int
    by_status: dict[str, int]


def summarize(results: Sequence[FeatureResult]) -> FeatureRunSummary:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return FeatureRunSummary(len(results), dict(sorted(counts.items())))
