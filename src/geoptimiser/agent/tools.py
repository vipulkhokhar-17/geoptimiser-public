"""The agent's allowlisted tools: thin, validated wrappers over existing components.

Every tool wraps functionality that already exists (diagnosis, retrieval, grounding,
recommendations); none runs code, touches the shell or reaches the network. Anything
quoted from a website is returned under an ``untrusted_text`` key and is data only.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import Field, ValidationError

from geoptimiser.diagnosis import (
    Diagnosis,
    diagnose,
    passage_evidence,
    validate_diagnosis,
)
from geoptimiser.diagnosis.grounding import grounding_problems
from geoptimiser.features.audit import AuditRun
from geoptimiser.features.inputs import url_key
from geoptimiser.features.registry import default_registry
from geoptimiser.recommendations import (
    RecommendationSet,
    TemplateGenerator,
    validate_recommendations,
)
from geoptimiser.retrieval import EmbeddingIncompatible, EmbeddingUnavailable, Retriever
from geoptimiser.schemas import (
    Chunk,
    EvidenceRef,
    Finding,
    Identifier,
    SchemaModel,
    Severity,
)

_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "informational": 4,
}
MAX_SUPPLEMENTARY_PER_FINDING = 10


class ToolError(RuntimeError):
    """A tool could not do what was asked. ``transient`` allows a bounded retry."""

    def __init__(self, code: str, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient


@dataclass
class AgentContext:
    """Everything the tools may touch for one audit (never put in graph state)."""

    run: AuditRun
    diagnosis: Diagnosis
    chunks: Sequence[Chunk]
    retriever: Retriever | None = None
    generator: TemplateGenerator = field(default_factory=TemplateGenerator)
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    recommendations: RecommendationSet | None = None
    supplementary: dict[str, list[EvidenceRef]] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        run: AuditRun,
        chunks: Sequence[Chunk] = (),
        *,
        retriever: Retriever | None = None,
        diagnosis: Diagnosis | None = None,
        generator: TemplateGenerator | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> "AgentContext":
        """Wrap an existing audit run; runs the Stage 09 diagnosis if none is given."""
        diagnosis = diagnosis or diagnose(run, chunks, retriever=retriever, clock=clock)
        return cls(
            run=run,
            diagnosis=diagnosis,
            chunks=chunks,
            retriever=retriever,
            generator=generator or TemplateGenerator(),
            clock=clock,
        )

    @property
    def audit_id(self) -> str:
        return self.run.audit_id

    def finding(self, finding_id: str) -> Finding:
        for finding in self.diagnosis.findings:
            if finding.finding_id == finding_id:
                return finding
        raise ToolError("not_found", f"no finding {finding_id!r} in this audit")

    def problems(self) -> list[str]:
        extra = [e for refs in self.supplementary.values() for e in refs]
        chunk_map = {c.chunk_id: c for c in self.chunks}
        return [
            *validate_diagnosis(self.diagnosis, self.run, self.chunks),
            *grounding_problems(extra, self.audit_id, chunk_map),
        ]


# --- inputs ---------------------------------------------------------------------------


class ListFindingsInput(SchemaModel):
    severity: Severity | None = None
    limit: int = Field(default=20, ge=1, le=50)


class GetFindingInput(SchemaModel):
    finding_id: Identifier


class RetrievePassagesInput(SchemaModel):
    finding_id: Identifier
    query: str | None = Field(default=None, min_length=3, max_length=200)
    top_k: int = Field(default=3, ge=1, le=5)


class ValidateEvidenceInput(SchemaModel):
    finding_id: Identifier | None = None


class GenerateRecommendationsInput(SchemaModel):
    # None means every finding; an empty list would silently replace earlier
    # recommendations with an empty set, so it is refused (security audit run 1).
    finding_ids: tuple[Identifier, ...] | None = Field(
        default=None, min_length=1, max_length=50
    )


class ValidateOutputInput(SchemaModel):
    pass


# --- handlers -------------------------------------------------------------------------


def _located(ref: EvidenceRef) -> dict[str, Any] | None:
    if ref.chunk_id is None:
        return None
    return {
        "chunk_id": ref.chunk_id,
        "char_start": ref.char_start,
        "char_end": ref.char_end,
    }


def list_findings(ctx: AgentContext, args: ListFindingsInput) -> dict[str, Any]:
    findings = [
        f
        for f in ctx.diagnosis.findings
        if args.severity is None or f.severity == args.severity
    ]
    findings.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.finding_id))
    evidence = ctx.diagnosis.evidence
    items = [
        {
            "finding_id": f.finding_id,
            "title": f.title,
            "severity": f.severity,
            "basis": f.basis,
            "feature_ids": list(f.feature_ids),
            "evidence_count": len(f.evidence_ids),
            "passage_count": sum(
                1 for e in f.evidence_ids if e in evidence and evidence[e].chunk_id
            ),
            "has_remediation": bool(f.remediation),
        }
        for f in findings[: args.limit]
    ]
    return {"total": len(findings), "returned": len(items), "findings": items}


def get_finding(ctx: AgentContext, args: GetFindingInput) -> dict[str, Any]:
    f = ctx.finding(args.finding_id)
    refs = [
        ctx.diagnosis.evidence[e] for e in f.evidence_ids if e in ctx.diagnosis.evidence
    ]
    return {
        "finding_id": f.finding_id,
        "title": f.title,
        "severity": f.severity,
        "basis": f.basis,
        "confidence": f.confidence,
        "feature_ids": list(f.feature_ids),
        "measurement_method": f.measurement_method,
        "limitations": list(f.limitations[:5]),
        "remediation": f.remediation,
        "verification_criteria": list(f.verification_criteria[:3]),
        "evidence_total": len(refs),
        "evidence": [
            {
                "evidence_id": r.evidence_id,
                "kind": "passage" if r.chunk_id else "measurement",
                "source_url": r.source_url,
                "locator": _located(r),
                "untrusted_text": r.snippet[:200],
            }
            for r in refs[:10]
        ],
        "supplementary_evidence": [
            r.evidence_id for r in ctx.supplementary.get(f.finding_id, [])
        ],
    }


def _affected_urls(ctx: AgentContext, finding: Finding) -> set[str]:
    return {
        url_key(r.subject_url)
        for r in ctx.run.results
        if r.status in ("fail", "warning")
        and r.feature_id in finding.feature_ids
        and r.subject_url
    }


def _default_query(finding: Finding) -> str:
    catalog = default_registry().catalog
    defs = {d.feature_id: d for d in catalog.features}
    defn = defs.get(finding.feature_ids[0])
    return f"{defn.name} {defn.description}" if defn else finding.title


def retrieve_passages(ctx: AgentContext, args: RetrievePassagesInput) -> dict[str, Any]:
    if ctx.retriever is None:
        raise ToolError(
            "retrieval_unavailable", "no retriever is configured for this audit"
        )
    finding = ctx.finding(args.finding_id)
    pages = _affected_urls(ctx, finding)
    if not pages:
        raise ToolError("no_scope", "this finding is not tied to specific pages")
    modes = ctx.retriever.available_modes()
    mode = "hybrid" if "hybrid" in modes else "lexical"
    query = args.query or _default_query(finding)
    try:
        ranked = ctx.retriever.retrieve(
            query, mode, ctx.retriever.config.top_k
        ).chunk_ids
    except (EmbeddingUnavailable, EmbeddingIncompatible) as exc:
        raise ToolError("retrieval_unavailable", type(exc).__name__) from None
    except RuntimeError as exc:  # encoding or rerank failure: worth one more try
        raise ToolError(
            "retrieval_failed", type(exc).__name__, transient=True
        ) from None
    by_id = {c.chunk_id: c for c in ctx.chunks if c.audit_id == ctx.audit_id}
    chunk_map = dict(by_id)
    stored = ctx.supplementary.setdefault(finding.finding_id, [])
    known = {r.evidence_id for r in stored}
    passages = []
    for chunk_id in ranked:
        chunk = by_id.get(chunk_id)
        if chunk is None or url_key(str(chunk.url)) not in pages:
            continue
        ref = passage_evidence(chunk, ctx.clock(), 300)
        if grounding_problems([ref], ctx.audit_id, chunk_map):
            continue  # never keep evidence that does not reproduce its source
        if ref.evidence_id not in known and len(stored) < MAX_SUPPLEMENTARY_PER_FINDING:
            stored.append(ref)
            known.add(ref.evidence_id)
        passages.append(
            {
                "rank": len(passages) + 1,
                "evidence_id": ref.evidence_id,
                "chunk_id": chunk.chunk_id,
                "source_url": ref.source_url,
                "heading_path": list(chunk.heading_path),
                "char_start": ref.char_start,
                "char_end": ref.char_end,
                "already_cited": ref.evidence_id in finding.evidence_ids,
                "untrusted_text": ref.snippet,
            }
        )
        if len(passages) >= args.top_k:
            break
    return {
        "mode": mode,
        "query": "custom" if args.query else "default",
        "returned": len(passages),
        "passages": passages,
    }


def validate_evidence(ctx: AgentContext, args: ValidateEvidenceInput) -> dict[str, Any]:
    if args.finding_id is not None:
        ctx.finding(args.finding_id)
    problems = ctx.problems()
    if args.finding_id is not None:
        problems = [p for p in problems if args.finding_id in p or p.startswith("ev_")]
    return {
        "valid": not problems,
        "problem_count": len(problems),
        "problems": problems[:10],
        "scope": args.finding_id or "all findings",
    }


def generate_recommendations(
    ctx: AgentContext, args: GenerateRecommendationsInput
) -> dict[str, Any]:
    problems = ctx.problems()
    if problems:
        raise ToolError(
            "evidence_invalid",
            f"refusing to recommend from unvalidated evidence: {problems[0]}",
        )
    findings = ctx.diagnosis.findings
    if args.finding_ids is not None:
        wanted = set(args.finding_ids)
        missing = wanted - {f.finding_id for f in findings}
        if missing:
            raise ToolError("not_found", f"unknown finding {sorted(missing)[0]!r}")
        findings = tuple(f for f in findings if f.finding_id in wanted)
    subset = ctx.diagnosis.model_copy(update={"findings": tuple(findings)})
    result = ctx.generator.generate(subset, ctx.clock)
    ctx.recommendations = result
    return {
        "count": len(result.recommendations),
        "rejected": [
            {"finding_ids": list(r.finding_ids), "reason": r.reason}
            for r in result.rejected
        ],
        "skipped_without_remediation": len(result.skipped_finding_ids),
        "recommendations": [
            {
                "recommendation_id": r.recommendation_id,
                "title": r.title,
                "priority": r.priority,
                "effort": r.estimated_effort,
                "impact": r.expected_impact_direction,
                "finding_ids": list(r.finding_ids),
            }
            for r in result.recommendations
        ],
    }


def validate_output(ctx: AgentContext, args: ValidateOutputInput) -> dict[str, Any]:
    if ctx.recommendations is None:
        raise ToolError(
            "no_recommendations", "generate_recommendations has not run yet"
        )
    problems = [
        *ctx.problems(),
        *validate_recommendations(ctx.recommendations, ctx.diagnosis),
    ]
    return {
        "valid": not problems,
        "problem_count": len(problems),
        "problems": problems[:10],
        "recommendations": len(ctx.recommendations.recommendations),
    }


# --- registry -------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[SchemaModel]
    handler: Callable[[AgentContext, Any], dict[str, Any]]


class ToolRegistry:
    """The complete set of things the agent may do. Nothing else can be called."""

    def __init__(self, specs: Sequence[ToolSpec]) -> None:
        names = [s.name for s in specs]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique")
        if "finish" in names:
            raise ValueError("'finish' is reserved for the agent protocol")
        self._specs = {s.name: s for s in specs}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "args": s.input_model.model_json_schema().get("properties", {}),
            }
            for s in self._specs.values()
        ]

    def validate(self, name: str, args: Mapping[str, Any]) -> SchemaModel:
        """Validated input for ``name``; unknown tools and bad arguments are errors."""
        spec = self._specs.get(name)
        if spec is None:
            raise ToolError("unauthorized_tool", f"{name!r} is not an allowed tool")
        try:
            return spec.input_model.model_validate(dict(args))
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "arguments"
            raise ToolError(
                "invalid_arguments", f"{where}: {first['msg']}"[:200]
            ) from None

    def run(self, name: str, parsed: SchemaModel, ctx: AgentContext) -> dict[str, Any]:
        result = self._specs[name].handler(ctx, parsed)
        json.dumps(result)  # tools must return plain JSON-serialisable data
        return result


def default_registry_tools(*, with_retrieval: bool) -> ToolRegistry:
    """The shipped allowlist; ``retrieve_passages`` only when a retriever exists."""
    specs = [
        ToolSpec(
            "list_findings",
            "List the audit's findings (id, title, severity, evidence counts).",
            ListFindingsInput,
            list_findings,
        ),
        ToolSpec(
            "get_finding",
            "Show one finding with its evidence references.",
            GetFindingInput,
            get_finding,
        ),
        ToolSpec(
            "validate_evidence",
            "Check evidence grounding and provenance for all findings, or one.",
            ValidateEvidenceInput,
            validate_evidence,
        ),
        ToolSpec(
            "generate_recommendations",
            "Generate recommendations from validated findings (all, or a subset).",
            GenerateRecommendationsInput,
            generate_recommendations,
        ),
        ToolSpec(
            "validate_output",
            "Validate the generated recommendations against the findings and evidence.",
            ValidateOutputInput,
            validate_output,
        ),
    ]
    if with_retrieval:
        specs.insert(
            2,
            ToolSpec(
                "retrieve_passages",
                "Retrieve passages relevant to a finding from the pages it affects.",
                RetrievePassagesInput,
                retrieve_passages,
            ),
        )
    return ToolRegistry(specs)
