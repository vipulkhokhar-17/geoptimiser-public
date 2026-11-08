"""Findings from failed results, and the evidence-provenance checks behind them."""

from collections.abc import Sequence

from geoptimiser.features.catalog import FeatureCatalog
from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.contribution import redundant_units
from geoptimiser.features.inputs import AuditInputs
from geoptimiser.schemas import EvidenceRef, FeatureResult, Finding, Severity

_RANK: dict[Severity, int] = {
    "informational": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
_DEFAULT_LIMITATION = "None beyond the stated method."


class EvidenceError(ValueError):
    """Evidence that cannot be traced to a real source in the audit."""


def collect_evidence(results: Sequence[FeatureResult]) -> dict[str, EvidenceRef]:
    """All evidence of an audit keyed by ID (identical observations are one record)."""
    found: dict[str, EvidenceRef] = {}
    for result in results:
        for ref in result.evidence:
            found.setdefault(ref.evidence_id, ref)
    return found


def build_findings(
    results: Sequence[FeatureResult],
    catalog: FeatureCatalog,
    config: FeatureConfig | None = None,
) -> list[Finding]:
    """One finding per scored feature that has failing results.

    Failing units of the same feature are merged (duplicate control): the finding
    lists the affected URLs through its evidence. Unscored features are reported in
    the results but do not raise findings, with one exception: a feature whose
    violation may be the owner's deliberate choice (``intent_dependent``) raises a
    *notice* finding from its ``warning`` results, asking to confirm intent. Failures
    that repeat another feature's root cause on the same URL are folded into the
    primary feature's finding (see ``contribution.UNIT_OVERLAPS``), which then names
    both features. Heuristic checks give ``basis="heuristic"``.
    """
    config = config or FeatureConfig()
    redundant = redundant_units(results, config)
    findings: list[Finding] = []
    for defn in catalog.features:
        notice = defn.intent_dependent
        if not defn.scored and not notice:
            continue
        flag = "warning" if notice else "fail"
        own = [r for r in results if r.feature_id == defn.feature_id]
        failing = [
            r
            for r in own
            if r.status == flag and (r.feature_id, r.subject_url) not in redundant
        ]
        if not failing:
            continue
        folded = [
            r
            for r in results
            if (r.feature_id, r.subject_url) in redundant
            and redundant[(r.feature_id, r.subject_url)].home == defn.feature_id
            and r.status in ("fail", "warning")
        ]
        measured = sum(1 for r in own if r.status in ("pass", "fail", "warning"))
        ids: list[str] = []
        for result in (*failing, *folded):
            ids += [e.evidence_id for e in result.evidence if e.evidence_id not in ids]
        shown = ids[: config.max_evidence_per_finding]
        explanations = list(
            dict.fromkeys(r.explanation or "" for r in failing if r.explanation)
        )
        unit = "page(s)" if defn.scope == "page" else "site-level unit(s)"
        limits = [x for x in defn.limitations if x != _DEFAULT_LIMITATION]
        # Limits of the measurement itself (for example "looks client-rendered").
        for result in failing:
            limits += [x for x in result.limitations if x not in limits]
        if notice:
            limits.insert(
                0,
                "Observation, not a verdict: the audit cannot tell whether this is "
                "deliberate. Confirm intent before changing anything.",
            )
        elif defn.is_heuristic:
            limits.insert(
                0,
                "Heuristic rule: treat as a prompt for review, not a verified defect.",
            )
        if defn.implementation_status == "partial":
            limits.append(
                "Partial implementation: the check covers only part of the feature."
            )
        if len(ids) > len(shown):
            limits.append(
                f"Evidence is capped: {len(shown)} of {len(ids)} items are linked."
            )
        affected = sorted({r.subject_url for r in failing if r.subject_url})
        feature_ids = (
            defn.feature_id,
            *dict.fromkeys(
                r.feature_id for r in folded if r.feature_id != defn.feature_id
            ),
        )
        if folded:
            reasons = dict.fromkeys(
                redundant[(r.feature_id, r.subject_url)].rule.reason for r in folded
            )
            limits.append(
                f"Also reported by {', '.join(feature_ids[1:])} for the same cause; "
                f"counted once. {' '.join(reasons)}"
            )
        headline = (
            f"{defn.name}: {len(failing)} of {measured} measured {unit} need "
            "intent confirmed"
            if notice
            else f"{defn.name}: {len(failing)} of {measured} measured {unit} fail"
        )
        findings.append(
            Finding(
                audit_id=failing[0].audit_id,
                finding_id=f"fnd_{defn.feature_id}",
                title=headline,
                description=f"{defn.description} Example: {'; '.join(explanations[:3])}",
                category=defn.category,
                severity=max((r.severity for r in failing), key=_RANK.__getitem__),
                basis="heuristic" if defn.is_heuristic else "measured",
                feature_ids=feature_ids,
                evidence_ids=tuple(shown),
                measurement_method=defn.method,
                confidence=config.heuristic_confidence
                if defn.is_heuristic or notice
                else config.measured_confidence,
                limitations=tuple(limits),
                verification_criteria=(
                    (
                        f"If the restriction is not intended, re-run {defn.feature_id} "
                        f"({defn.name}) after removing it; the affected URLs should "
                        "report pass. If it is intended, no change is needed.",
                    )
                    if notice
                    else (
                        f"Re-run {defn.feature_id} ({defn.name}) after the change; the affected URLs should report pass.",
                    )
                ),
                remediation=defn.remediation,
            )
        )
        if affected:
            last = findings[-1]
            findings[-1] = last.model_copy(
                update={
                    "verification_criteria": (
                        *last.verification_criteria,
                        f"Affected URLs include: {', '.join(affected[:3])}",
                    )
                }
            )
    return findings


def validate_provenance(
    results: Sequence[FeatureResult],
    findings: Sequence[Finding],
    inputs: AuditInputs,
) -> None:
    """Raise ``EvidenceError`` unless all evidence is traceable.

    Every evidence reference must cite a URL the audit actually fetched or read,
    every finding must cite evidence that exists and that a failing result of one of
    its own features produced, and a failing result must carry evidence.
    """
    known = inputs.known_urls
    for result in results:
        if result.status in ("fail", "warning") and not result.evidence:
            raise EvidenceError(f"{result.feature_id}: failing result without evidence")
        for ref in result.evidence:
            if ref.source_url not in known:
                raise EvidenceError(
                    f"{result.feature_id}: evidence cites an unknown URL {ref.source_url!r}"
                )
    by_feature: dict[str, set[str]] = {}
    for result in results:
        if result.status in ("fail", "warning"):
            by_feature.setdefault(result.feature_id, set()).update(
                e.evidence_id for e in result.evidence
            )
    for finding in findings:
        if not finding.feature_ids:
            raise EvidenceError(
                f"{finding.finding_id}: a finding must name its features"
            )
        allowed = set().union(*(by_feature.get(f, set()) for f in finding.feature_ids))
        missing = [e for e in finding.evidence_ids if e not in allowed]
        if missing:
            raise EvidenceError(
                f"{finding.finding_id}: evidence {missing[0]!r} does not come from a failing or warning result of its features"
            )
