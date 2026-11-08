"""Deterministic, template-based recommendations (Stage 10, ADR-0021).

No model is involved. A recommendation is the finding's own remediation guidance,
verification criteria and evidence, regrouped and re-prioritised under configurable
rules. Recommendations that would make an unsupported claim are *rejected and
listed*, never silently rewritten or dropped.
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import Field, model_validator

from geoptimiser.diagnosis import Diagnosis
from geoptimiser.recommendations.claims import (
    authored_text,
    claim_problems,
    ungrounded_urls,
    urls_in,
)
from geoptimiser.schemas import (
    EvidenceRef,
    Finding,
    Identifier,
    Recommendation,
    SchemaModel,
    Severity,
    VersionedRecord,
)

GENERATOR_NAME = "template"
GENERATOR_VERSION = 1
Priority = Literal["P0", "P1", "P2", "P3"]
Effort = Literal["small", "medium", "large"]
Direction = Literal["positive", "neutral", "negative", "uncertain"]
_PRIORITIES: tuple[Priority, ...] = ("P0", "P1", "P2", "P3")
_EFFORTS: tuple[Effort, ...] = ("small", "medium", "large")
_SEVERITY_RANK: dict[Severity, int] = {
    "informational": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


class ImpactRule(SchemaModel):
    """An explicit, justified exception to the default ``uncertain`` direction."""

    feature_id: Identifier
    direction: Direction
    justification: str = Field(min_length=10)


class RecommendationConfig(SchemaModel):
    priority_by_severity: dict[Severity, Priority] = {
        "critical": "P0",
        "high": "P1",
        "medium": "P2",
        "low": "P3",
        "informational": "P3",
    }
    # A recommendation resting only on heuristic findings is ranked one step lower.
    demote_heuristic_only: bool = True
    default_effort: Effort = "medium"
    effort_by_category: dict[str, Effort] = {}
    effort_by_feature: dict[str, Effort] = {}
    # More affected pages than this raises effort one step (capped at "large").
    large_scope_pages: int = Field(default=20, ge=1)
    max_evidence_per_recommendation: int = Field(default=20, ge=1, le=200)
    impact_rules: tuple[ImpactRule, ...] = ()

    @model_validator(mode="after")
    def _complete_priority_table(self):  # type: ignore[no-untyped-def]
        missing = set(_SEVERITY_RANK) - set(self.priority_by_severity)
        if missing:
            raise ValueError(f"priority_by_severity lacks {sorted(missing)}")
        return self


class Rejected(SchemaModel):
    finding_ids: tuple[Identifier, ...]
    reason: str


class RecommendationSet(VersionedRecord):
    audit_id: Identifier
    generator: str
    generator_version: int
    recommendations: tuple[Recommendation, ...]
    rejected: tuple[Rejected, ...]
    # findings that produced no recommendation because they carry no remediation
    skipped_finding_ids: tuple[Identifier, ...]
    notes: tuple[str, ...]


class RecommendationGenerator(Protocol):
    name: str
    version: int

    def generate(
        self, diagnosis: Diagnosis, clock: Callable[[], datetime]
    ) -> RecommendationSet: ...


def _key(text: str) -> str:
    return " ".join(text.lower().split())


def _shift(order: Sequence[str], value: str, steps: int) -> str:
    return order[max(0, min(len(order) - 1, order.index(value) + steps))]


class TemplateGenerator:
    name = GENERATOR_NAME
    version = GENERATOR_VERSION

    def __init__(self, config: RecommendationConfig | None = None) -> None:
        self.config = config or RecommendationConfig()

    # --- rules -------------------------------------------------------------------

    def priority(self, findings: Sequence[Finding]) -> Priority:
        top = max(findings, key=lambda f: _SEVERITY_RANK[f.severity])
        priority = self.config.priority_by_severity[top.severity]
        if self.config.demote_heuristic_only and all(
            f.basis != "measured" for f in findings
        ):
            return _shift(_PRIORITIES, priority, 1)  # type: ignore[return-value]
        return priority

    def effort(self, findings: Sequence[Finding], pages: int) -> Effort:
        efforts = [
            self.config.effort_by_feature.get(fid)
            or self.config.effort_by_category.get(f.category)
            or self.config.default_effort
            for f in findings
            for fid in f.feature_ids
        ]
        effort = max(efforts, key=_EFFORTS.index)
        if pages > self.config.large_scope_pages:
            effort = _shift(_EFFORTS, effort, 1)
        return effort  # type: ignore[return-value]

    def direction(self, findings: Sequence[Finding]) -> tuple[Direction, str | None]:
        """``uncertain`` unless every feature has a justified impact rule saying so."""
        rules = {r.feature_id: r for r in self.config.impact_rules}
        features = {fid for f in findings for fid in f.feature_ids}
        chosen = [rules.get(fid) for fid in sorted(features)]
        if chosen and all(chosen) and len({r.direction for r in chosen if r}) == 1:
            first = chosen[0]
            assert first is not None
            return first.direction, first.justification
        return "uncertain", None

    # --- generation --------------------------------------------------------------

    def generate(
        self,
        diagnosis: Diagnosis,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> RecommendationSet:
        created_at = clock()
        groups: dict[str, list[Finding]] = defaultdict(list)
        skipped: list[str] = []
        for finding in diagnosis.findings:
            if not finding.remediation:
                skipped.append(finding.finding_id)
            else:
                groups[_key(finding.remediation)].append(finding)

        recommendations: list[Recommendation] = []
        rejected: list[Rejected] = []
        for key in sorted(groups):
            findings = sorted(groups[key], key=lambda f: f.finding_id)
            recommendation = self._build(
                findings, diagnosis.evidence, diagnosis.audit_id, created_at
            )
            problem = _screen(recommendation, findings, diagnosis.evidence)
            if problem:
                ids = tuple(f.finding_id for f in findings)
                rejected.append(Rejected(finding_ids=ids, reason=problem))
            else:
                recommendations.append(recommendation)
        notes = []
        if skipped:
            notes.append(
                f"{len(skipped)} finding(s) have no remediation guidance, so no "
                "recommendation was generated for them."
            )
        return RecommendationSet(
            audit_id=diagnosis.audit_id,
            generator=self.name,
            generator_version=self.version,
            recommendations=tuple(recommendations),
            rejected=tuple(rejected),
            skipped_finding_ids=tuple(skipped),
            notes=tuple(notes),
        )

    def _build(
        self,
        findings: Sequence[Finding],
        evidence: Mapping[str, EvidenceRef],
        audit_id: str,
        created_at: datetime,
    ) -> Recommendation:
        ids = tuple(f.finding_id for f in findings)
        evidence_ids: list[str] = []
        for finding in findings:
            evidence_ids += [e for e in finding.evidence_ids if e not in evidence_ids]
        evidence_ids = evidence_ids[: self.config.max_evidence_per_recommendation]
        pages = {evidence[e].source_url for e in evidence_ids if e in evidence}
        direction, justification = self.direction(findings)
        names = [f.title.split(":", 1)[0] for f in findings]
        title = (
            names[0] if len(names) == 1 else f"{names[0]} (+{len(names) - 1} related)"
        )
        measured = sum(1 for f in findings if f.basis == "measured")
        parts = [
            f"{len(findings)} finding(s) ({measured} measured, "
            f"{len(findings) - measured} heuristic) call for this change.",
            "Method: "
            + "; ".join(
                dict.fromkeys(f.measurement_method.rstrip(".") for f in findings)
            )
            + ".",
        ]
        if measured < len(findings):
            parts.append("Part of this rests on heuristic rules; review before acting.")
        if justification:
            parts.append(f"Expected direction ({direction}): {justification}")
        else:
            parts.append(
                "Impact on AI-search visibility is uncertain: no experiment supports a "
                "direction or size."
            )
        limits = list(dict.fromkeys(x for f in findings for x in f.limitations))
        if limits:
            parts.append("Limitations: " + " ".join(limits))
        plan = list(dict.fromkeys(c for f in findings for c in f.verification_criteria))
        digest = hashlib.sha256("|".join(ids).encode()).hexdigest()[:12]
        return Recommendation(
            audit_id=audit_id,
            recommendation_id=f"rec_{digest}",
            title=f"Address: {title}",
            rationale=" ".join(parts),
            proposed_change=findings[0].remediation or "",
            finding_ids=ids,
            evidence_ids=tuple(evidence_ids),
            expected_impact_direction=direction,
            confidence=min(f.confidence for f in findings),
            priority=self.priority(findings),
            estimated_effort=self.effort(findings, len(pages)),
            verification_plan=tuple(plan),
            created_at=created_at,
        )


def _text_of(rec: Recommendation) -> str:
    return " ".join(
        [rec.title, rec.rationale, rec.proposed_change, *rec.verification_plan]
    )


def _screen(
    rec: Recommendation,
    findings: Sequence[Finding],
    evidence: Mapping[str, EvidenceRef],
) -> str | None:
    """Why ``rec`` may not be issued, if it may not: a claim the evidence can't back."""
    found = claim_problems(authored_text(_text_of(rec)))
    if found:
        return f"unsupported claim ({', '.join(found)})"
    allowed = {evidence[e].source_url for e in rec.evidence_ids if e in evidence}
    for finding in findings:  # URLs a finding itself names (affected pages)
        allowed |= {u for c in finding.verification_criteria for u in urls_in(c)}
    stray = ungrounded_urls(_text_of(rec), allowed)
    if stray:
        return f"names a URL that is not in the findings' evidence ({stray[0]})"
    return None


def validate_recommendations(
    result: RecommendationSet, diagnosis: Diagnosis
) -> list[str]:
    """Faithfulness checks; an empty list means every recommendation is traceable."""
    problems: list[str] = []
    findings = {f.finding_id: f for f in diagnosis.findings}
    seen: set[str] = set()
    if result.audit_id != diagnosis.audit_id:
        problems.append("recommendation set belongs to a different audit")
    for rec in result.recommendations:
        label = rec.recommendation_id
        if label in seen:
            problems.append(f"{label}: duplicate recommendation id")
        seen.add(label)
        if rec.audit_id != diagnosis.audit_id:
            problems.append(f"{label}: belongs to a different audit")
        linked = [findings.get(i) for i in rec.finding_ids]
        if any(f is None for f in linked):
            problems.append(f"{label}: cites a finding that does not exist")
            continue
        cited = {e for f in linked if f for e in f.evidence_ids}
        for evidence_id in rec.evidence_ids:
            if evidence_id not in diagnosis.evidence:
                problems.append(f"{label}: evidence {evidence_id!r} does not exist")
            elif evidence_id not in cited:
                problems.append(
                    f"{label}: evidence {evidence_id!r} is not cited by its findings"
                )
        found = claim_problems(authored_text(_text_of(rec)))
        if found:
            problems.append(f"{label}: unsupported claim ({', '.join(found)})")
    all_ids = [i for r in result.recommendations for i in r.finding_ids]
    if len(set(all_ids)) != len(all_ids):
        problems.append("a finding is covered by more than one recommendation")
    return problems
