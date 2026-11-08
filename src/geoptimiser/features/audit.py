"""Run a whole audit: results, evidence, findings and scores, with provenance checked."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.engine import run_all, summarize
from geoptimiser.features.findings import (
    build_findings,
    collect_evidence,
    validate_provenance,
)
from geoptimiser.features.inputs import AuditInputs
from geoptimiser.features.registry import FeatureRegistry, default_registry
from geoptimiser.features.scoring import ScoreReport, score_audit
from geoptimiser.schemas import EvidenceRef, FeatureResult, Finding


@dataclass(frozen=True)
class AuditRun:
    audit_id: str
    config: FeatureConfig
    catalog_version: int
    results: tuple[FeatureResult, ...]
    evidence: dict[str, EvidenceRef]
    findings: tuple[Finding, ...]
    scores: ScoreReport


def run_audit(
    inputs: AuditInputs,
    config: FeatureConfig | None = None,
    registry: FeatureRegistry | None = None,
) -> AuditRun:
    """Execute every catalog feature, derive findings, score, and verify provenance."""
    registry = registry or default_registry()
    config = config or FeatureConfig()
    results = run_all(inputs, config, registry)
    findings = build_findings(results, registry.catalog, config)
    validate_provenance(results, findings, inputs)
    return AuditRun(
        audit_id=inputs.audit_id,
        config=config,
        catalog_version=registry.catalog.version,
        results=tuple(results),
        evidence=collect_evidence(results),
        findings=tuple(findings),
        scores=score_audit(results, registry.catalog, config, inputs.crawl),
    )


def _write_jsonl(path: Path, records) -> None:  # type: ignore[no-untyped-def]
    with open(path, "x", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_artifacts(run: AuditRun, out_dir: Path) -> None:
    """Write ``feature_results.jsonl``, ``evidence.jsonl``, ``findings.jsonl`` and
    ``features.json`` (summary and scores). Files are created exclusively."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "feature_results.jsonl", run.results)
    _write_jsonl(out_dir / "evidence.jsonl", run.evidence.values())
    _write_jsonl(out_dir / "findings.jsonl", run.findings)
    summary = summarize(run.results)
    document = {
        "audit_id": run.audit_id,
        "catalog_version": run.catalog_version,
        "config": run.config.model_dump(mode="json"),
        "results": summary.results,
        "results_by_status": summary.by_status,
        "findings": len(run.findings),
        "scores": run.scores.model_dump(mode="json"),
    }
    tmp = out_dir / ".features.json.tmp"
    tmp.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out_dir / "features.json")
