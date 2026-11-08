"""The audit report: one machine-readable JSON document and a matching HTML page.

Both are built only from artifacts the pipeline actually produced. Anything that was not
measured, failed, or was skipped is listed as such; there are no placeholder values, and
the report makes no promise about AI mentions or citations.
"""

import html
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from geoptimiser.app.models import AuditRecord, StageRecord
from geoptimiser.diagnosis import Diagnosis
from geoptimiser.features.audit import AuditRun
from geoptimiser.features.registry import default_registry
from geoptimiser.recommendations import RecommendationSet
from geoptimiser.schemas import (
    Chunk,
    EvidenceRef,
    FetchRecord,
    Finding,
    SchemaModel,
    VersionedRecord,
)

# 2: group scores carry reported_score/status/withheld_reason, findings say whether they
# score, and measurement gaps are listed. Version-1 reports remain readable (all new
# fields default) and are rendered with the same reportability rule.
REPORT_VERSION = 2
DISCLAIMER = (
    "This report describes measured properties of the audited pages and rule-based "
    "suggestions. No change is guaranteed to cause AI search engines to mention or "
    "cite the site, and the effect of any change on AI visibility is uncertain."
)
_TIMING_FIELDS = (
    "dns_ms",
    "connect_ms",
    "tls_ms",
    "ttfb_ms",
    "response_ms",
    "total_ms",
)


@dataclass
class PipelineState:
    """Whatever the pipeline had produced when the report was built."""

    fetches: Sequence[FetchRecord] = ()
    crawl_summary: dict[str, Any] = field(default_factory=dict)
    run: AuditRun | None = None
    chunks: Sequence[Chunk] = ()
    diagnosis: Diagnosis | None = None
    recommendations: RecommendationSet | None = None
    agent: dict[str, Any] | None = None
    retrieval: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    versions: dict[str, Any] = field(default_factory=dict)


class TimingStat(SchemaModel):
    measured: int
    not_measured: int
    p50_ms: float | None = None
    p95_ms: float | None = None
    max_ms: float | None = None


class NetworkSummary(SchemaModel):
    fetches: int
    fetches_ok: int
    redirects: int
    bytes_stored: int
    errors_by_type: dict[str, int]
    status_codes: dict[str, int]
    timings: dict[str, TimingStat]
    note: str


class ReportFinding(SchemaModel):
    finding: Finding
    evidence: tuple[EvidenceRef, ...]
    affected_urls: tuple[str, ...]
    measurements: tuple[dict[str, Any], ...]
    # "defect": a measured failure. "notice": an owner-controlled setting to confirm.
    kind: Literal["defect", "notice"] = "defect"
    # Whether the failing feature takes part in the aggregate score (False for notices,
    # unscored features and features excluded as redundant or non-discriminating).
    contributes_to_score: bool = True


class AuditReport(VersionedRecord):
    report_version: int = REPORT_VERSION
    audit: dict[str, Any]
    status: str
    status_reason: str
    pipeline: dict[str, Any]
    stages: tuple[dict[str, Any], ...]
    crawl: dict[str, Any]
    network: NetworkSummary | None
    scores: dict[str, Any] | None
    features: tuple[dict[str, Any], ...]
    findings: tuple[ReportFinding, ...]
    findings_available: bool
    recommendations: RecommendationSet | None
    recommendations_validated: bool
    agent: dict[str, Any]
    retrieval: dict[str, Any]
    pages: tuple[str, ...]
    failed_stages: tuple[str, ...]
    unmeasured: tuple[str, ...]
    # Checks that could not conclude on a page, with the reason (capped). Distinct from
    # a failure: nothing here says the page is wrong, only that it was not measured.
    measurement_gaps: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...]
    validation_problems: tuple[str, ...] = Field(default=())
    disclaimer: str = DISCLAIMER
    generated_at: datetime


def _stat(values: list[float], missing: int) -> TimingStat:
    if not values:
        return TimingStat(measured=0, not_measured=missing)
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return TimingStat(
        measured=len(values),
        not_measured=missing,
        p50_ms=round(statistics.median(ordered), 2),
        p95_ms=round(p95, 2),
        max_ms=round(ordered[-1], 2),
    )


def summarize_network(fetches: Sequence[FetchRecord]) -> NetworkSummary | None:
    if not fetches:
        return None
    timings: dict[str, TimingStat] = {}
    for name in _TIMING_FIELDS:
        values, missing = [], 0
        for f in fetches:
            value = getattr(f.timings, name, None) if f.timings else None
            if value is None:
                missing += 1
            else:
                values.append(float(value))
        timings[name] = _stat(values, missing)
    return NetworkSummary(
        fetches=len(fetches),
        fetches_ok=sum(1 for f in fetches if f.outcome == "success"),
        redirects=sum(len(f.redirects) for f in fetches),
        bytes_stored=sum(f.body.size_bytes for f in fetches if f.body),
        errors_by_type=dict(
            Counter(f.error_type for f in fetches if f.error_type is not None)
        ),
        status_codes=dict(
            Counter(str(f.status_code) for f in fetches if f.status_code is not None)
        ),
        timings=timings,
        note=(
            "Durations are measured on the audit host. `not_measured` counts fetches "
            "whose transport did not expose that step (for example plain HTTP has no "
            "TLS handshake). ttfb_ms is request sent until response headers parsed."
        ),
    )


def _findings(state: PipelineState) -> tuple[ReportFinding, ...]:
    if state.diagnosis is None or state.run is None:
        return ()
    evidence = state.diagnosis.evidence
    catalog = default_registry().catalog
    defs = {d.feature_id: d for d in catalog.features}
    contributing = {
        f.feature_id: f.scored and f.contributes for f in state.run.scores.features
    }
    failing: dict[str, list[Any]] = {}
    for result in state.run.results:
        if result.status in ("fail", "warning"):
            failing.setdefault(result.feature_id, []).append(result)
    out = []
    for finding in state.diagnosis.findings:
        results = [r for fid in finding.feature_ids for r in failing.get(fid, [])]
        primary = finding.feature_ids[0] if finding.feature_ids else ""
        out.append(
            ReportFinding(
                kind="notice"
                if primary in defs and defs[primary].intent_dependent
                else "defect",
                contributes_to_score=contributing.get(primary, False)
                and not finding.finding_id.startswith("syn_"),
                finding=finding,
                evidence=tuple(
                    evidence[e] for e in finding.evidence_ids if e in evidence
                ),
                affected_urls=tuple(
                    sorted({r.subject_url for r in results if r.subject_url})
                ),
                measurements=tuple(
                    {
                        "feature_id": r.feature_id,
                        "url": r.subject_url,
                        "status": r.status,
                        "observed_value": r.observed_value,
                        "expected_value": r.expected_value,
                        "explanation": r.explanation,
                        "limitations": [x for x in r.limitations][:3],
                    }
                    for r in results[:10]
                ),
            )
        )
    return tuple(out)


def _limitations(
    state: PipelineState, stages: Sequence[StageRecord], unmeasured: Sequence[str]
) -> tuple[str, ...]:
    notes = [
        "Findings come from deterministic checks on the pages that were crawled; pages "
        "that were not crawled are not assessed.",
        "Heuristic findings are prompts for review, not verified defects.",
        "Recommendation priority and effort come from fixed, documented rules; the "
        "direction of impact on AI visibility is recorded as uncertain unless an "
        "explicit, justified rule says otherwise.",
    ]
    if state.run is not None:
        catalog = default_registry().catalog
        todo = sum(1 for d in catalog.features if d.implementation_status == "planned")
        if todo:
            notes.append(
                f"{todo} catalog features are not implemented yet and are reported as "
                "not measured; scores cover measured features only."
            )
    notes.append(
        "The audit reads the HTML each URL returns and does not execute JavaScript. "
        "Text, titles or links that a script adds after loading are not evaluated; "
        "where the initial HTML looks client-rendered the affected results say so."
    )
    if unmeasured:
        notes.append(
            f"{len(unmeasured)} measurement(s) are unavailable; see 'unmeasured'."
        )
    if state.run is not None and state.run.scores.excluded_features:
        notes.append(
            "Excluded from the aggregate score (still listed, with reasons): "
            + "; ".join(
                f"{fid} ({why})"
                for fid, why in sorted(state.run.scores.excluded_features.items())
            )
        )
    truncated = int(state.crawl_summary.get("truncated_bodies", 0))
    cut_docs = int(state.crawl_summary.get("truncated_documents", 0))
    if truncated or cut_docs:
        notes.append(
            f"{truncated} page(s) were truncated at the response-size limit and "
            f"{cut_docs} extracted document(s) were cut by an extraction limit. "
            "Content beyond a cut was not read: a check that would need it reports "
            "'not measured' instead of a failure (see measurement gaps), and checks "
            "the readable part can still decide are kept."
        )
    for stage in stages:
        if stage.status == "failed":
            notes.append(f"Stage '{stage.name}' failed ({stage.error_category}).")
    return tuple(notes)


_MAX_GAPS = 100


def _measurement_gaps(state: PipelineState) -> tuple[dict[str, Any], ...]:
    """Implemented checks that could not conclude on a page, and why."""
    if state.run is None:
        return ()
    names = {d.feature_id: d.name for d in default_registry().catalog.features}
    gaps = [
        {
            "feature_id": r.feature_id,
            "name": names.get(r.feature_id, r.feature_id),
            "url": r.subject_url,
            "status": r.status,
            "reason": r.explanation or r.error_message,
        }
        for r in state.run.results
        if r.status in ("not_measured", "error")
        and r.implementation_status in ("implemented", "partial")
    ]
    return tuple(gaps[:_MAX_GAPS])


def _unmeasured(state: PipelineState) -> tuple[str, ...]:
    out = []
    if state.run is not None:
        for score in state.run.scores.features:
            if (
                score.scored
                and score.contributes
                and score.pass_rate is None
                and score.applicable
            ):
                out.append(f"feature {score.feature_id}: no measured result")
    net = summarize_network(state.fetches)
    if net:
        for name, stat in net.timings.items():
            if stat.not_measured:
                out.append(
                    f"timing {name}: not measured for {stat.not_measured} fetch(es)"
                )
    return tuple(out)


def build_report(
    record: AuditRecord,
    stages: Sequence[StageRecord],
    state: PipelineState,
    *,
    status: str,
    reason: str,
    generated_at: datetime,
) -> AuditReport:
    scores = names = None
    features: tuple[dict[str, Any], ...] = ()
    if state.run is not None:
        scores = state.run.scores.model_dump(mode="json", exclude={"features"})
        catalog = default_registry().catalog
        names = {d.feature_id: (d.name, d.category) for d in catalog.features}
        features = tuple(
            {
                **f.model_dump(mode="json"),
                "name": names[f.feature_id][0],
                "category": names[f.feature_id][1],
            }
            for f in state.run.scores.features
        )
    findings = _findings(state)
    validated = not state.problems and state.diagnosis is not None
    unmeasured = _unmeasured(state)
    return AuditReport(
        audit={
            "audit_id": record.audit_id,
            "target_url": record.target_url,
            "normalized_url": record.normalized_url,
            "domain": record.domain,
            "brand_name": record.brand_name,
            "created_at": record.created_at.isoformat(),
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "options": record.options.model_dump(mode="json"),
        },
        status=status,
        status_reason=reason,
        pipeline={"pipeline_version": record.pipeline_version, **state.versions},
        stages=tuple(s.model_dump(mode="json") for s in stages),
        crawl=state.crawl_summary,
        network=summarize_network(state.fetches),
        scores=scores,
        features=features,
        findings=findings if validated else (),
        findings_available=validated,
        recommendations=state.recommendations if validated else None,
        recommendations_validated=validated and state.recommendations is not None,
        agent=state.agent or {"requested": False, "status": "not_requested"},
        retrieval=state.retrieval,
        pages=tuple(
            sorted(
                {
                    str(f.final_url)
                    for f in state.fetches
                    if f.outcome == "success"
                    and f.final_url
                    and f.requested_url.path != "/robots.txt"
                }
            )
        )[:500],
        failed_stages=tuple(s.name for s in stages if s.status == "failed"),
        unmeasured=unmeasured,
        measurement_gaps=_measurement_gaps(state),
        limitations=_limitations(state, stages, unmeasured),
        validation_problems=tuple(state.problems[:20]),
        generated_at=generated_at,
    )


# --- HTML ----------------------------------------------------------------------------


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _link(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return f'<a href="{_e(url)}" rel="noopener noreferrer nofollow">{_e(url)}</a>'
    return _e(url)


def shown_score(group: dict[str, Any]) -> float | None:
    """The score that may be displayed for a group: only a reportable one.

    Reports from before ``reported_score`` existed are handled with the same rule.
    """
    if "reported_score" in group:
        return group["reported_score"]
    return group["score"] if group.get("reportable") else None


def _score_cell(group: dict[str, Any]) -> str:
    value = shown_score(group)
    if value is not None:
        return _num(value)
    measured, applicable = group["measured_features"], group["applicable_features"]
    if group.get("score") is None:
        return f"not measured ({measured}/{applicable} features)"
    return f"withheld ({measured}/{applicable} features measured)"


def _num(value: object, digits: int = 3) -> str:
    return "not measured" if value is None else f"{float(value):.{digits}f}"  # type: ignore[arg-type]


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


_STYLE = """
body{font:15px/1.5 system-ui,sans-serif;margin:0;color:#1b1f23;background:#fff}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:.2em 0}h2{font-size:1.2rem;margin:2em 0 .5em;border-bottom:1px solid #d0d7de;padding-bottom:.2em}
table{border-collapse:collapse;width:100%;margin:.5em 0}th,td{border:1px solid #d0d7de;padding:4px 8px;text-align:left;vertical-align:top;font-size:.9rem}
th{background:#f6f8fa}code,pre{font:12px ui-monospace,monospace;background:#f6f8fa;padding:1px 4px;border-radius:3px;word-break:break-word}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.8rem;font-weight:600;color:#fff}
.completed{background:#1a7f37}.incomplete{background:#9a6700}.failed,.interrupted{background:#cf222e}.queued,.running{background:#0969da}
.sev-critical,.sev-high{color:#cf222e;font-weight:600}.sev-medium{color:#9a6700}.muted{color:#57606a}
details{margin:.4em 0;border:1px solid #d0d7de;border-radius:6px;padding:6px 10px}summary{cursor:pointer;font-weight:600}
blockquote{margin:.3em 0;padding:2px 10px;border-left:3px solid #d0d7de;color:#444;white-space:pre-wrap}
.notice{background:#fff8c5;border:1px solid #d4a72c;padding:8px 12px;border-radius:6px}
"""


# The served report carries a CSP header; a downloaded copy opened from disk has no
# headers, so the same script-free policy is repeated in the document (frame-ancestors
# is not honoured in <meta>, so it is omitted). Security audit run 1, hardening.
_META_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
)


def render_html(report: AuditReport) -> str:
    a = report.audit
    parts = [
        f"<h1>GEO audit: {_e(a['domain'])}</h1>",
        f'<p><span class="badge {_e(report.status)}">{_e(report.status)}</span> '
        f"{_e(report.status_reason)}</p>",
        f"<p>Target: {_link(a['target_url'])}"
        + (f"<br>Brand: {_e(a['brand_name'])}" if a.get("brand_name") else "")
        + f"<br>Audit <code>{_e(a['audit_id'])}</code> "
        f"created {_e(a['created_at'])}; pipeline <code>{_e(report.pipeline.get('pipeline_version'))}</code></p>",
        f'<p class="notice">{_e(report.disclaimer)}</p>',
    ]
    if report.status != "completed":
        parts.append(
            '<p class="notice"><strong>This audit did not complete.</strong> Sections '
            "below show only what was actually produced.</p>"
        )
    # scores
    parts.append("<h2>Scores and measurement coverage</h2>")
    if report.scores is None:
        parts.append(
            '<p class="muted">Feature checks did not run, so there are no scores.</p>'
        )
    else:
        overall = report.scores["overall"]
        shown = _score_cell(overall)
        parts.append(
            f"<p>Overall score: <strong>{_e(shown)}</strong>. Feature coverage "
            f"{_e(_num(overall['feature_coverage']))}; unit coverage {_e(_num(overall['unit_coverage']))}. "
            f"{_e(overall.get('withheld_reason') or overall['note'])}</p>"
        )
        rows = [
            [_e(c["name"]), _e(_score_cell(c)), _e(_num(c["feature_coverage"])),
             f"{c['measured_features']}/{c['applicable_features']}",
             _e(c.get("withheld_reason") or "")]
            for c in report.scores["categories"]
        ]  # fmt: skip
        parts.append(
            _table(
                ["Category", "Score", "Feature coverage", "Measured", "Why withheld"],
                rows,
            )
        )
        parts.append(
            '<p class="muted">A score is shown only when at least '
            f"{_e(_num(report.scores['min_reportable_coverage'], 2))} of the applicable "
            "scored features were measured. A withheld value covers only a subset of "
            "the group and is not a result for it. Coverage describes what was "
            "measured, not how well the site performs.</p>"
        )
        excluded = report.scores.get("excluded_features") or {}
        if excluded:
            parts.append(
                "<p class='muted'>Not part of the aggregate: "
                + "; ".join(f"<code>{_e(k)}</code> {_e(v)}" for k, v in sorted(excluded.items()))
                + "</p>"
            )  # fmt: skip
    # stages
    parts.append("<h2>Pipeline stages</h2>")
    parts.append(
        _table(
            ["Stage", "Status", "Duration (ms)", "Error"],
            [
                [_e(s["name"]), _e(s["status"]), _e(s.get("duration_ms")),
                 _e(s.get("error_category") or "") + (f": {_e(s['error_message'])}" if s.get("error_message") else "")]
                for s in report.stages
            ],
        )
    )  # fmt: skip
    # network
    if report.network:
        n = report.network
        parts.append("<h2>Network measurements</h2>")
        parts.append(
            f"<p>{n.fetches} fetches, {n.fetches_ok} successful, {n.redirects} redirects, "
            f"{n.bytes_stored} bytes stored. Errors: {_e(n.errors_by_type or 'none')}.</p>"
        )
        parts.append(
            _table(
                ["Metric", "Measured", "Not measured", "p50 ms", "p95 ms", "max ms"],
                [
                    [_e(k), str(v.measured), str(v.not_measured), _e(_num(v.p50_ms, 1)),
                     _e(_num(v.p95_ms, 1)), _e(_num(v.max_ms, 1))]
                    for k, v in n.timings.items()
                ],
            )
        )  # fmt: skip
        parts.append(f'<p class="muted">{_e(n.note)}</p>')
    # findings
    parts.append(f"<h2>Findings ({len(report.findings)})</h2>")
    if not report.findings_available:
        parts.append(
            '<p class="muted">Findings are unavailable for this audit (see stages).</p>'
        )
    for rf in report.findings:
        f = rf.finding
        items = "".join(
            f"<li>{_link(e.source_url)} <span class='muted'>({_e(e.source_type)}"
            + (
                f", chunk {_e(e.chunk_id)}, chars {e.char_start}–{e.char_end}"
                if e.chunk_id
                else ""
            )
            + f")</span><blockquote>{_e(e.snippet)}</blockquote></li>"
            for e in rf.evidence
        )
        meas = "".join(
            f"<tr><td>{_link(m['url'] or '')}</td><td>{_e(m['status'])}</td>"
            f"<td><code>{_e(m['observed_value'])}</code></td><td><code>{_e(m['expected_value'])}</code></td>"
            f"<td>{_e(m.get('explanation'))}</td></tr>"
            for m in rf.measurements
        )
        parts.append(
            f"<details><summary><span class='sev-{_e(f.severity)}'>{_e(f.severity)}</span> "
            f"{'[notice] ' if rf.kind == 'notice' else ''}{_e(f.title)}</summary><p>{_e(f.description)}</p>"
            f"<p>Basis: {_e(f.basis)}; confidence {f.confidence:.2f}; method: {_e(f.measurement_method)}. "
            f"{'Counts toward the score.' if rf.contributes_to_score else 'Does not count toward the score.'}"
            f"{' This is an observation about a setting the owner controls; confirm it is intended.' if rf.kind == 'notice' else ''}</p>"
            + (f"<table><tr><th>URL</th><th>Status</th><th>Observed</th><th>Expected</th><th>Why</th></tr>{meas}</table>" if meas else "")
            + f"<p><strong>Evidence</strong></p><ul>{items}</ul>"
            + ("<p><strong>Limitations</strong></p><ul>" + "".join(f"<li>{_e(x)}</li>" for x in f.limitations) + "</ul>" if f.limitations else "")
            + "</details>"
        )  # fmt: skip
    # recommendations
    recs = report.recommendations.recommendations if report.recommendations else ()
    parts.append(f"<h2>Recommendations ({len(recs)})</h2>")
    if report.recommendations is None:
        parts.append('<p class="muted">No validated recommendations are available.</p>')
    for r in recs:
        parts.append(
            f"<details><summary>{_e(r.priority)} · {_e(r.title)}</summary>"
            f"<p>{_e(r.proposed_change)}</p><p>{_e(r.rationale)}</p>"
            f"<p>Effort: {_e(r.estimated_effort)}; expected impact: {_e(r.expected_impact_direction)}; "
            f"confidence {r.confidence:.2f}. Findings: {_e(', '.join(r.finding_ids))}.</p>"
            "<p><strong>How to verify</strong></p><ul>"
            + "".join(f"<li>{_e(v)}</li>" for v in r.verification_plan)
            + "</ul></details>"
        )
    if report.recommendations and report.recommendations.rejected:
        parts.append(
            "<p class='muted'>Held back: "
            + _e(len(report.recommendations.rejected))
            + " recommendation(s) failed claim validation.</p>"
        )
    # agent & retrieval
    parts.append("<h2>Retrieval and agent</h2>")
    parts.append(f"<p>Retrieval: <code>{_e(report.retrieval)}</code></p>")
    parts.append(f"<p>Agent: <code>{_e(report.agent)}</code></p>")
    if report.measurement_gaps:
        parts.append(
            f"<h2>Not measured ({len(report.measurement_gaps)} shown)</h2>"
            '<p class="muted">These checks could not conclude. This is a limit of the '
            "measurement, not a finding about the page.</p>"
            + _table(
                ["Feature", "URL", "Why"],
                [
                    [_e(f"{g['feature_id']} {g['name']}"), _link(g["url"] or ""), _e(g["reason"])]
                    for g in report.measurement_gaps
                ],
            )
        )  # fmt: skip
    # limits
    parts.append(
        "<h2>Limitations</h2><ul>"
        + "".join(f"<li>{_e(x)}</li>" for x in report.limitations)
        + "</ul>"
    )
    if report.validation_problems:
        parts.append(
            "<h2>Validation problems</h2><ul>"
            + "".join(f"<li>{_e(x)}</li>" for x in report.validation_problems)
            + "</ul>"
        )
    if report.unmeasured:
        parts.append(
            f"<details><summary>Unmeasured ({len(report.unmeasured)})</summary><ul>"
            + "".join(f"<li>{_e(x)}</li>" for x in report.unmeasured)
            + "</ul></details>"
        )
    parts.append(
        f'<p class="muted">Generated {_e(report.generated_at.isoformat())}.</p>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_META_CSP}">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>GEO audit — {_e(a['domain'])}</title><style>{_STYLE}</style></head>"
        f"<body><main>{''.join(parts)}</main></body></html>"
    )
