"""Evidence-linked diagnosis (Stage 09, ADR-0020).

Extends the deterministic audit findings without replacing them:

* each original finding keeps its id, severity, basis and evidence, and gains
  *located passage evidence* (chunk id and character range) from the pages it affects;
* scoped cross-feature rules add findings for co-occurring failures on one page.

Nothing here calls a model, and the diagnosis works with no retriever or no chunks.
Page text, retrieved or not, is untrusted data: it is quoted into evidence snippets
and never read as an instruction or used to choose severity, rules or queries.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from pydantic import Field

from geoptimiser.diagnosis.grounding import grounding_problems, passage_evidence
from geoptimiser.diagnosis.rules import DEFAULT_RULES, SynthesisRule, validate_rules
from geoptimiser.features.audit import AuditRun
from geoptimiser.features.catalog import FeatureCatalog
from geoptimiser.features.inputs import url_key
from geoptimiser.features.registry import default_registry
from geoptimiser.retrieval import Retriever
from geoptimiser.retrieval.retriever import Mode
from geoptimiser.schemas import (
    Chunk,
    EvidenceRef,
    FeatureResult,
    Finding,
    Identifier,
    SchemaModel,
    VersionedRecord,
)

DIAGNOSIS_VERSION = 1
_SYNTHESIS_PREFIX = "syn_"
_SHELL_NOTE = "looks client-rendered"


class DiagnosisError(ValueError):
    """The diagnosis would not be traceable; this indicates a bug, not bad input."""


class DiagnosisConfig(SchemaModel):
    max_passages_per_finding: int = Field(default=3, ge=0, le=20)
    snippet_max_chars: int = Field(default=400, ge=20, le=2000)
    max_evidence_per_finding: int = Field(default=20, ge=1, le=200)
    retrieval_mode: Mode = "lexical"
    synthesized_confidence: float = Field(default=0.5, ge=0, le=1)
    rules: tuple[SynthesisRule, ...] = DEFAULT_RULES


class DiagnosisStats(SchemaModel):
    base_findings: int
    synthesized_findings: int
    passages_attached: int
    passage_source: str  # "retrieval+page_lead", "page_lead" or "none"
    chunks_used: int
    chunks_ignored: int  # chunks from a different audit


class Diagnosis(VersionedRecord):
    diagnosis_version: int = DIAGNOSIS_VERSION
    audit_id: Identifier
    findings: tuple[Finding, ...]
    evidence: dict[str, EvidenceRef]
    notes: tuple[str, ...]
    stats: DiagnosisStats


def _failing(run: AuditRun) -> dict[str, list[FeatureResult]]:
    out: dict[str, list[FeatureResult]] = defaultdict(list)
    for result in run.results:
        if result.status in ("fail", "warning"):
            out[result.feature_id].append(result)
    return out


def _urls(results: Sequence[FeatureResult]) -> list[str]:
    return sorted({r.subject_url for r in results if r.subject_url})


def _extend(finding: Finding, evidence_ids: Sequence[str], limit: int, note: str):
    """A copy of ``finding`` with extra evidence ids appended (cap respected)."""
    merged = list(finding.evidence_ids)
    merged += [e for e in evidence_ids if e not in merged]
    merged = merged[: max(limit, len(finding.evidence_ids))]
    data = finding.model_dump() | {
        "evidence_ids": tuple(merged),
        "limitations": (*finding.limitations, note),
    }
    return Finding.model_validate(data)


class _Passages:
    """Chunk lookup for one audit, with retrieval as an optional ranking source."""

    def __init__(self, chunks: Sequence[Chunk], audit_id: str) -> None:
        usable = [c for c in chunks if c.audit_id == audit_id]
        self.ignored = len(chunks) - len(usable)
        self.by_id = {c.chunk_id: c for c in usable}
        self.by_url: dict[str, list[Chunk]] = defaultdict(list)
        for chunk in sorted(usable, key=lambda c: (c.document_id, c.ordinal)):
            self.by_url[url_key(str(chunk.url))].append(chunk)

    def pick(
        self,
        urls: Sequence[str],
        limit: int,
        ranked: Sequence[str],
    ) -> tuple[list[Chunk], str]:
        """Up to ``limit`` chunks of ``urls``: ranked ones first, then page leads."""
        wanted = {url_key(u) for u in urls}
        chosen: list[Chunk] = []
        for chunk_id in ranked:
            chunk = self.by_id.get(chunk_id)
            if chunk and url_key(str(chunk.url)) in wanted and chunk not in chosen:
                chosen.append(chunk)
        used_retrieval = bool(chosen)
        covered = {url_key(str(c.url)) for c in chosen}
        for url in urls:
            key = url_key(url)
            if key not in covered and self.by_url.get(key):
                chosen.append(self.by_url[key][0])
                covered.add(key)
        label = "retrieval+page_lead" if used_retrieval else "page_lead"
        return chosen[:limit], label if chosen else "none"


def diagnose(
    run: AuditRun,
    chunks: Sequence[Chunk] = (),
    *,
    retriever: Retriever | None = None,
    config: DiagnosisConfig | None = None,
    catalog: FeatureCatalog | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Diagnosis:
    config = config or DiagnosisConfig()
    catalog = catalog or default_registry().catalog
    validate_rules(config.rules, catalog)
    defs = {d.feature_id: d for d in catalog.features}
    retrieved_at = clock()
    passages = _Passages(chunks, run.audit_id)
    failing = _failing(run)
    notes: list[str] = []
    if passages.ignored:
        notes.append(f"{passages.ignored} chunk(s) from another audit were ignored.")
    if not passages.by_id:
        notes.append(
            "No passages were available; findings carry measurement evidence only."
        )
    if (
        retriever is not None
        and config.retrieval_mode not in retriever.available_modes()
    ):
        notes.append(
            f"Retrieval mode {config.retrieval_mode!r} is unavailable; page leads used."
        )
        retriever = None

    evidence = dict(run.evidence)
    sources: set[str] = set()
    attached = 0
    out: list[Finding] = []

    def attach(finding: Finding, urls: list[str], query: str | None) -> Finding:
        nonlocal attached
        if not config.max_passages_per_finding or not urls or not passages.by_id:
            return finding
        ranked: list[str] = []
        if retriever is not None and query:
            try:
                ranked = retriever.retrieve(query, config.retrieval_mode).chunk_ids
            except RuntimeError as exc:  # embedder/reranker failure: degrade, say so
                notes.append(
                    f"Retrieval failed ({type(exc).__name__}); page leads used."
                )
        picked, source = passages.pick(urls, config.max_passages_per_finding, ranked)
        if not picked:
            return finding
        sources.add(source)
        refs = [
            passage_evidence(c, retrieved_at, config.snippet_max_chars) for c in picked
        ]
        for ref in refs:
            evidence.setdefault(ref.evidence_id, ref)
        attached += len(refs)
        return _extend(
            finding,
            [r.evidence_id for r in refs],
            config.max_evidence_per_finding,
            f"Attached passages ({source}) are page text from the affected URLs, "
            "shown for context; they do not by themselves prove the defect.",
        )

    for finding in run.findings:
        own = [r for fid in finding.feature_ids for r in failing.get(fid, [])]
        defn = defs.get(finding.feature_ids[0])
        query = f"{defn.name} {defn.description}" if defn else None
        out.append(attach(finding, _urls(own), query))

    shell_pages = {
        r.subject_url
        for results in failing.values()
        for r in results
        if r.subject_url and any(_SHELL_NOTE in x for x in r.limitations)
    }
    skipped_shell: set[str] = set()
    for rule in config.rules:
        by_feature = [{u: [] for u in _urls(failing.get(f, []))} for f in rule.requires]
        matched = set.intersection(*(set(m) for m in by_feature))
        # One root cause (a client-rendered shell) already explains every co-occurring
        # failure on such a page; a cross-feature "high" finding would count it again.
        skipped_shell |= matched & shell_pages
        pages = sorted(matched - shell_pages)
        if not pages:
            continue
        ids: list[str] = []
        for feature_id in rule.requires:
            for result in failing[feature_id]:
                if result.subject_url in pages:
                    ids += [
                        e.evidence_id
                        for e in result.evidence
                        if e.evidence_id not in ids
                    ]
        names = ", ".join(rule.requires)
        partial = [
            f for f in rule.requires if defs[f].implementation_status == "partial"
        ]
        limits = [
            "Heuristic synthesis: the failures co-occur on the same page; this does "
            "not show that they interact or that fixing them changes visibility.",
            *(
                [
                    f"{', '.join(partial)}: partial implementation, covering only "
                    "part of the feature."
                ]
                if partial
                else []
            ),
        ]
        finding = Finding(
            audit_id=run.audit_id,
            finding_id=f"{_SYNTHESIS_PREFIX}{rule.rule_id}",
            title=f"{rule.title}: {len(pages)} page(s)",
            description=f"{rule.description} Example: {pages[0]}",
            category="cross_feature",
            severity=rule.severity,
            basis="heuristic",
            feature_ids=rule.requires,
            evidence_ids=tuple(ids[: config.max_evidence_per_finding]),
            measurement_method=(
                f"Deterministic rule {rule.rule_id}: failing results for {names} "
                "on the same page."
            ),
            confidence=config.synthesized_confidence,
            limitations=tuple(limits),
            verification_criteria=(
                f"Re-run {names}; all should pass on the affected pages.",
                f"Affected URLs include: {', '.join(pages[:3])}",
            ),
            remediation=rule.remediation,
            created_at=retrieved_at,
        )
        out.append(attach(finding, pages, None))

    if skipped_shell:
        notes.append(
            f"{len(skipped_shell)} page(s) look client-rendered: their co-occurring "
            "failures share that one cause, so no combined finding was raised for "
            "them; the individual results carry the limitation."
        )
    base = len(run.findings)
    diagnosis = Diagnosis(
        audit_id=run.audit_id,
        findings=tuple(out),
        evidence={k: v for k, v in evidence.items() if k in _referenced(out)},
        notes=tuple(dict.fromkeys(notes)),
        stats=DiagnosisStats(
            base_findings=base,
            synthesized_findings=len(out) - base,
            passages_attached=attached,
            passage_source="+".join(sorted(sources)) or "none",
            chunks_used=len(passages.by_id),
            chunks_ignored=passages.ignored,
        ),
    )
    problems = validate_diagnosis(diagnosis, run, chunks)
    if problems:
        raise DiagnosisError(problems[0])
    return diagnosis


def _referenced(findings: Sequence[Finding]) -> set[str]:
    return {e for f in findings for e in f.evidence_ids}


def validate_diagnosis(
    diagnosis: Diagnosis, run: AuditRun, chunks: Sequence[Chunk]
) -> list[str]:
    """Everything a reader should be able to trust about a diagnosis; [] means sound.

    Every finding must belong to the audit and be unique; original findings must be
    preserved unchanged apart from added evidence; every referenced evidence record
    must exist; measurement evidence must come from a failing result of one of the
    finding's features and equal the audit's own record; passage evidence must be
    faithful to a chunk of this audit and lie on a page the finding is about.
    """
    problems: list[str] = []
    chunk_map = {c.chunk_id: c for c in chunks}
    failing = _failing(run)
    ids = [f.finding_id for f in diagnosis.findings]
    if len(set(ids)) != len(ids):
        problems.append("duplicate finding ids")
    if diagnosis.audit_id != run.audit_id:
        problems.append("diagnosis belongs to a different audit")
    originals = {f.finding_id: f for f in run.findings}
    for original in run.findings:
        mine = next(
            (f for f in diagnosis.findings if f.finding_id == original.finding_id), None
        )
        if mine is None:
            problems.append(f"{original.finding_id}: original finding was dropped")
            continue
        kept = (
            mine.severity,
            mine.basis,
            mine.feature_ids,
            mine.title,
            mine.confidence,
        )
        if kept != (
            original.severity,
            original.basis,
            original.feature_ids,
            original.title,
            original.confidence,
        ):
            problems.append(f"{original.finding_id}: original fields were altered")
        if mine.evidence_ids[: len(original.evidence_ids)] != original.evidence_ids:
            problems.append(f"{original.finding_id}: original evidence was altered")
    problems += grounding_problems(diagnosis.evidence.values(), run.audit_id, chunk_map)
    for finding in diagnosis.findings:
        label = finding.finding_id
        if finding.audit_id != run.audit_id:
            problems.append(f"{label}: belongs to a different audit")
        if label not in originals and not label.startswith(_SYNTHESIS_PREFIX):
            problems.append(f"{label}: unknown finding")
        results = [r for fid in finding.feature_ids for r in failing.get(fid, [])]
        if any(fid not in failing for fid in finding.feature_ids) and label.startswith(
            _SYNTHESIS_PREFIX
        ):
            problems.append(f"{label}: a required feature has no failing result")
        allowed = {e.evidence_id for r in results for e in r.evidence}
        pages = {url_key(u) for u in _urls(results)}
        for evidence_id in finding.evidence_ids:
            ref = diagnosis.evidence.get(evidence_id)
            if ref is None:
                problems.append(f"{label}: evidence {evidence_id!r} is missing")
            elif ref.chunk_id is None:
                if evidence_id not in allowed or run.evidence.get(evidence_id) != ref:
                    problems.append(
                        f"{label}: {evidence_id!r} is not from its failing results"
                    )
            elif url_key(ref.source_url) not in pages:
                problems.append(
                    f"{label}: passage {evidence_id!r} is off the finding's pages"
                )
    unused = set(diagnosis.evidence) - _referenced(diagnosis.findings)
    if unused:
        problems.append(f"evidence not referenced by any finding: {sorted(unused)[0]}")
    return problems
