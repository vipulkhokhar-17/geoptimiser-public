"""Before/after comparison of two completed audits of the same target.

A comparison reports *measured differences* between two audits. It never says a change
to the website caused them: other things move between audits (what was crawled, the
pipeline version, the site's content for unrelated reasons), and the caveats say which.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from geoptimiser.app.models import AuditRecord
from geoptimiser.app.report import AuditReport, shown_score
from geoptimiser.schemas import Identifier, SchemaModel, VersionedRecord

COMPARISON_VERSION = 1
STATEMENT = (
    "These are differences between two measurements. They do not show that any change "
    "to the website caused them, and they say nothing about AI mentions or citations."
)


class CompareError(ValueError):
    """The two audits cannot be compared. ``code`` is machine-readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Delta(SchemaModel):
    key: str
    name: str
    before: float | None
    after: float | None
    delta: float | None  # None unless both sides were measured
    note: str | None = None


class FindingChange(SchemaModel):
    finding_id: str
    title: str
    severity_before: str | None
    severity_after: str | None
    affected_before: int
    affected_after: int
    newly_affected_urls: tuple[str, ...] = ()
    no_longer_affected_urls: tuple[str, ...] = ()


class RecommendationCheck(SchemaModel):
    recommendation_id: str
    title: str
    finding_ids: tuple[str, ...]
    status: Literal["no_longer_failing", "still_failing", "not_measured"]
    detail: str


class AuditRef(SchemaModel):
    audit_id: str
    status: str
    created_at: datetime


class Comparison(VersionedRecord):
    comparison_id: Identifier
    comparison_version: int = COMPARISON_VERSION
    normalized_url: str
    before: AuditRef
    after: AuditRef
    reliability: Literal["comparable", "reduced"]
    caveats: tuple[str, ...]  # things that make the comparison less reliable
    notes: tuple[str, ...] = ()  # context that does not affect reliability
    overall: Delta
    pillars: tuple[Delta, ...]
    categories: tuple[Delta, ...]
    coverage: tuple[Delta, ...]
    features_changed: tuple[Delta, ...]
    findings_new: tuple[FindingChange, ...]
    findings_resolved: tuple[FindingChange, ...]
    findings_persistent: tuple[FindingChange, ...]
    recommendations: tuple[RecommendationCheck, ...]
    pages_only_before: tuple[str, ...] = Field(default=())
    pages_only_after: tuple[str, ...] = Field(default=())
    statement: str = STATEMENT


def _delta(
    key: str, name: str, before: Any, after: Any, note: str | None = None
) -> Delta:
    both = before is not None and after is not None
    return Delta(
        key=key, name=name,
        before=None if before is None else float(before),
        after=None if after is None else float(after),
        delta=round(float(after) - float(before), 4) if both else None,
        note=note if both else (note or "not measured on at least one side"),
    )  # fmt: skip


def check_compatible(
    before: AuditRecord,
    after: AuditRecord,
    rb: AuditReport | None,
    ra: AuditReport | None,
) -> None:
    if before.audit_id == after.audit_id:
        raise CompareError("same_audit", "an audit cannot be compared with itself")
    if before.normalized_url != after.normalized_url:
        raise CompareError(
            "different_targets", "the audits are for different target URLs"
        )
    for record in (before, after):
        if record.status != "completed":
            raise CompareError(
                "audit_not_completed",
                f"audit {record.audit_id} is {record.status}; only completed audits can be compared",
            )
    if rb is None or ra is None or rb.scores is None or ra.scores is None:
        raise CompareError(
            "report_unavailable", "both audits need a report with scores"
        )
    if before.created_at >= after.created_at:
        raise CompareError("wrong_order", "'before' must be the earlier audit")
    for key in ("catalog_version", "scoring_version"):
        if rb.pipeline.get(key) != ra.pipeline.get(key):
            raise CompareError(
                "incompatible_versions",
                f"the audits used different {key}s, so their scores are not comparable",
            )


def _caveats(
    before: AuditRecord, after: AuditRecord, rb: AuditReport, ra: AuditReport
) -> list[str]:
    caveats = []
    for key in ("pipeline_version", "extraction_version", "chunker_version",
                "diagnosis_version", "recommendation_generator"):  # fmt: skip
        if rb.pipeline.get(key) != ra.pipeline.get(key):
            caveats.append(
                f"{key} differs ({rb.pipeline.get(key)} vs {ra.pipeline.get(key)})"
            )
    if rb.pipeline.get("crawl") != ra.pipeline.get("crawl"):
        caveats.append("crawl limits differ, so different pages may have been audited")
    if rb.audit["options"] != ra.audit["options"]:
        caveats.append("audit options differ (retrieval or agent settings)")
    pb, pa = set(rb.pages), set(ra.pages)
    if pb != pa:
        union = len(pb | pa) or 1
        caveats.append(
            f"the crawled page sets differ ({len(pb - pa)} only before, {len(pa - pb)} only after; "
            f"overlap {len(pb & pa) / union:.0%}); score changes may reflect which pages were reached"
        )
    if rb.crawl.get("stop_reason") != ra.crawl.get("stop_reason"):
        caveats.append("the crawls ended for different reasons")
    ob, oa = rb.scores["overall"], ra.scores["overall"]
    cb, ca = ob.get("feature_coverage"), oa.get("feature_coverage")
    if cb is not None and ca is not None and abs(cb - ca) > 0.05:
        caveats.append("measurement coverage differs between the audits")
    return caveats


def _group_deltas(rb: AuditReport, ra: AuditReport, section: str) -> tuple[Delta, ...]:
    assert rb.scores is not None and ra.scores is not None
    left = {g["key"]: g for g in rb.scores[section]}
    right = {g["key"]: g for g in ra.scores[section]}
    out = []
    for key in sorted(set(left) | set(right)):
        b, a = left.get(key), right.get(key)
        name = (b or a)["name"]  # type: ignore[index]
        out.append(
            _delta(
                key,
                name,
                b and shown_score(b),
                a and shown_score(a),
            )
        )
    return tuple(out)


def _change(rf_before: Any, rf_after: Any) -> FindingChange:
    f = (rf_after or rf_before).finding
    ub = set(rf_before.affected_urls) if rf_before else set()
    ua = set(rf_after.affected_urls) if rf_after else set()
    return FindingChange(
        finding_id=f.finding_id, title=f.title,
        severity_before=rf_before.finding.severity if rf_before else None,
        severity_after=rf_after.finding.severity if rf_after else None,
        affected_before=len(ub), affected_after=len(ua),
        newly_affected_urls=tuple(sorted(ua - ub))[:50],
        no_longer_affected_urls=tuple(sorted(ub - ua))[:50],
    )  # fmt: skip


def _recommendation_checks(
    rb: AuditReport, ra: AuditReport
) -> tuple[RecommendationCheck, ...]:
    if rb.recommendations is None:
        return ()
    feats = {f["feature_id"]: f for f in ra.features}
    by_finding = {rf.finding.finding_id: rf.finding for rf in rb.findings}
    out = []
    for rec in rb.recommendations.recommendations:
        ids = {
            fid
            for f in rec.finding_ids
            if f in by_finding
            for fid in by_finding[f].feature_ids
        }
        measured = still = 0
        for fid in ids:
            f = feats.get(fid)
            if f and f["passed"] + f["failed"] + f["warned"] > 0:
                measured += 1
                still += 1 if f["failed"] > 0 else 0
        if not ids or measured == 0:
            status, detail = (
                "not_measured",
                "the related features were not measured in the later audit",
            )
        elif still:
            status, detail = (
                "still_failing",
                f"{still} related feature(s) still fail in the later audit",
            )
        elif measured < len(ids):
            status, detail = (
                "not_measured",
                "only some related features were measured later, and none fail",
            )
        else:
            status, detail = (
                "no_longer_failing",
                "no related feature fails in the later audit (a measurement, not proof of cause)",
            )
        out.append(RecommendationCheck(
            recommendation_id=rec.recommendation_id, title=rec.title,
            finding_ids=rec.finding_ids, status=status, detail=detail,
        ))  # fmt: skip
    return tuple(out)


def compare_reports(
    comparison_id: str,
    before: AuditRecord,
    after: AuditRecord,
    rb: AuditReport,
    ra: AuditReport,
) -> Comparison:
    check_compatible(before, after, rb, ra)
    assert rb.scores is not None and ra.scores is not None
    ob, oa = rb.scores["overall"], ra.scores["overall"]
    fb = {f["feature_id"]: f for f in rb.features}
    fa = {f["feature_id"]: f for f in ra.features}
    changed = tuple(
        _delta(fid, (fa.get(fid) or fb[fid])["name"],
               fb.get(fid, {}).get("pass_rate"), fa.get(fid, {}).get("pass_rate"))
        for fid in sorted(set(fb) | set(fa))
        if fb.get(fid, {}).get("pass_rate") != fa.get(fid, {}).get("pass_rate")
        or fb.get(fid, {}).get("failed") != fa.get(fid, {}).get("failed")
    )  # fmt: skip
    mb = {rf.finding.finding_id: rf for rf in rb.findings}
    ma = {rf.finding.finding_id: rf for rf in ra.findings}
    caveats = _caveats(before, after, rb, ra)
    notes = []
    if not (ob["reportable"] and oa["reportable"]):
        notes.append(
            "the overall score is not reportable on at least one side (coverage is below "
            "the reporting threshold), so only category and feature changes are shown"
        )
    pb, pa = set(rb.pages), set(ra.pages)
    return Comparison(
        comparison_id=comparison_id,
        normalized_url=before.normalized_url,
        before=AuditRef(audit_id=before.audit_id, status=before.status, created_at=before.created_at),
        after=AuditRef(audit_id=after.audit_id, status=after.status, created_at=after.created_at),
        reliability="reduced" if caveats else "comparable",
        caveats=tuple(caveats),
        notes=tuple(notes),
        overall=_delta("overall", "Overall score", shown_score(ob), shown_score(oa)),
        pillars=_group_deltas(rb, ra, "pillars"),
        categories=_group_deltas(rb, ra, "categories"),
        coverage=(
            _delta("feature_coverage", "Feature coverage", ob["feature_coverage"], oa["feature_coverage"]),
            _delta("unit_coverage", "Unit coverage", ob["unit_coverage"], oa["unit_coverage"]),
        ),
        features_changed=changed,
        findings_new=tuple(_change(None, ma[i]) for i in sorted(set(ma) - set(mb))),
        findings_resolved=tuple(_change(mb[i], None) for i in sorted(set(mb) - set(ma))),
        findings_persistent=tuple(_change(mb[i], ma[i]) for i in sorted(set(mb) & set(ma))),
        recommendations=_recommendation_checks(rb, ra),
        pages_only_before=tuple(sorted(pb - pa))[:100],
        pages_only_after=tuple(sorted(pa - pb))[:100],
    )  # fmt: skip
