"""Compare retrieval modes on one query set, one corpus and one judgment set."""

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from geoptimiser.benchmark import metrics as bm
from geoptimiser.benchmark.evaluate import EvaluationReport, evaluate_rankings
from geoptimiser.benchmark.models import JudgmentSet, QuerySet, Target
from geoptimiser.features.inputs import url_key
from geoptimiser.jsonl import write_json_atomic
from geoptimiser.retrieval.bm25 import corpus_fingerprint
from geoptimiser.retrieval.dense import EmbeddingDescriptor
from geoptimiser.retrieval.retriever import MODES, Mode, ModeUnavailable, Retriever
from geoptimiser.schemas import Chunk, Identifier, SchemaModel, VersionedRecord

COMPARISON_VERSION = 1
BASELINE: Mode = "lexical"
PAIRED_METRICS = ("ndcg@10", "recall@10")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def chunk_resolver(chunks: Sequence[Chunk]) -> Callable[[Target], Mapping[str, int]]:
    """Map a judgment target to the chunks it covers (page, or heading section)."""

    def resolve(target: Target) -> Mapping[str, int]:
        key = url_key(target.url)
        found = {}
        for chunk in chunks:
            if url_key(str(chunk.url)) != key:
                continue
            if target.heading is None or _norm(target.heading) in {
                _norm(h) for h in chunk.heading_path
            }:
                found[chunk.chunk_id] = 1
        return found

    return resolve


class Latency(SchemaModel):
    n: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


class Paired(SchemaModel):
    """Per-query comparison with the baseline over queries scored in both runs."""

    metric: str
    n: int
    wins: int
    losses: int
    ties: int
    mean_delta: float | None


class ModeResult(SchemaModel):
    mode: Mode
    status: Literal["measured", "not_measured", "error"]
    reason: str | None = None
    report: EvaluationReport | None = None
    latency: Latency | None = None
    ranking_digest: str | None = (
        None  # same rankings => same digest, whatever the speed
    )
    vs_baseline: tuple[Paired, ...] = ()


class RetrievalComparison(VersionedRecord):
    comparison_version: int = COMPARISON_VERSION
    audit_id: Identifier | None
    n_chunks: int
    n_documents: int
    chunker_versions: tuple[int, ...]
    corpus_fingerprint: str
    config: dict[str, object]
    index_fingerprints: dict[str, str]
    embedder: dict[str, object] | None
    # Full model identity (model id, revision, normalisation, similarity); additive.
    embedder_descriptor: EmbeddingDescriptor | None = None
    reranker: dict[str, str] | None
    top_k: int
    results: tuple[ModeResult, ...]
    real_world_claim: bool
    notes: tuple[str, ...]


def _latency(samples: Sequence[float]) -> Latency | None:
    if not samples:
        return None
    return Latency(
        n=len(samples),
        mean_ms=sum(samples) / len(samples),
        p50_ms=bm.percentile(samples, 50),
        p95_ms=bm.percentile(samples, 95),
        max_ms=max(samples),
    )


def _paired(base: EvaluationReport, other: EvaluationReport) -> tuple[Paired, ...]:
    out = []
    left = {q.query_id: q.scores for q in base.per_query}
    right = {q.query_id: q.scores for q in other.per_query}
    shared = sorted(set(left) & set(right))
    for metric in PAIRED_METRICS:
        if not shared or any(metric not in left[q] for q in shared):
            continue
        deltas = [right[q][metric] - left[q][metric] for q in shared]
        out.append(
            Paired(
                metric=metric,
                n=len(shared),
                wins=sum(1 for d in deltas if d > 1e-12),
                losses=sum(1 for d in deltas if d < -1e-12),
                ties=sum(1 for d in deltas if abs(d) <= 1e-12),
                mean_delta=sum(deltas) / len(deltas),
            )
        )
    return tuple(out)


def compare_retrieval(
    queries: QuerySet,
    judgments: JudgmentSet,
    retriever: Retriever,
    *,
    modes: Sequence[Mode] = MODES,
    ks: Sequence[int] = (1, 3, 5, 10),
    audit_id: str | None = None,
    timer: Callable[[], float] = time.perf_counter,
) -> RetrievalComparison:
    """Run every requested mode over every query and score it with the benchmark.

    A mode the retriever cannot run is ``not_measured`` and a mode that raises is
    ``error``; neither is scored as zero. Latency is wall-clock and machine dependent,
    so reproducibility is judged by ``ranking_digest``, not by timings.
    """
    chunks = list(retriever.chunks.values())
    resolver = chunk_resolver(chunks)
    k = max(max(ks), retriever.config.top_k)
    results: list[ModeResult] = []
    for mode in modes:
        if mode not in retriever.available_modes():
            results.append(
                ModeResult(
                    mode=mode,
                    status="not_measured",
                    reason="required embedder or reranker not configured",
                )
            )
            continue
        rankings: dict[str, list[str]] = {}
        samples: list[float] = []
        try:
            for query in queries.queries:
                started = timer()
                rankings[query.query_id] = retriever.retrieve(
                    query.text, mode, k
                ).chunk_ids
                samples.append((timer() - started) * 1000)
        except (ModeUnavailable, RuntimeError) as exc:
            results.append(
                ModeResult(
                    mode=mode, status="error", reason=f"{type(exc).__name__}: {exc}"
                )
            )
            continue
        report = evaluate_rankings(
            queries, judgments, rankings, ks=ks, resolve=resolver
        )
        digest = hashlib.sha256(
            json.dumps(rankings, sort_keys=True).encode()
        ).hexdigest()
        results.append(
            ModeResult(
                mode=mode,
                status="measured" if report.n_evaluated else "not_measured",
                reason=None if report.n_evaluated else "no query could be evaluated",
                report=report,
                latency=_latency(samples),
                ranking_digest=digest,
            )
        )
    base = next((r.report for r in results if r.mode == BASELINE and r.report), None)
    if base is not None:
        results = [
            r.model_copy(update={"vs_baseline": _paired(base, r.report)})
            if r.report and r.mode != BASELINE
            else r
            for r in results
        ]
    real = judgments.origin == "human" and queries.review_status == "reviewed"
    notes = []
    if not real:
        notes.append(
            "Labels are fixture data or the query set is an unreviewed draft: these "
            "numbers describe the test setup, not real-world retrieval quality."
        )
    if retriever.embedder is not None and not retriever.embedder.semantic:
        notes.append(
            f"Embedder {retriever.embedder.name!r} is a deterministic test embedder "
            "(word-overlap hashing); dense and hybrid results are not semantic "
            "evidence."
        )
    if BASELINE not in modes:
        notes.append("No lexical baseline was run, so no paired comparison is given.")
    emb = retriever.embedder
    rer = retriever.reranker
    fingerprints = {"lexical": retriever.bm25.fingerprint}
    if retriever.dense:
        fingerprints["dense"] = retriever.dense.fingerprint
    return RetrievalComparison(
        audit_id=audit_id,
        n_chunks=len(chunks),
        n_documents=len({c.document_id for c in chunks}),
        chunker_versions=tuple(sorted({c.chunker_version for c in chunks})),
        corpus_fingerprint=corpus_fingerprint(chunks),
        config=retriever.config.model_dump(),
        index_fingerprints=fingerprints,
        embedder=(
            {
                "name": emb.name,
                "version": emb.version,
                "dimensions": emb.dimensions,
                "semantic": emb.semantic,
            }
            if emb
            else None
        ),
        embedder_descriptor=(
            retriever.dense.descriptor if retriever.dense is not None else None
        ),
        reranker=({"name": rer.name, "version": rer.version} if rer else None),
        top_k=retriever.config.top_k,
        results=tuple(results),
        real_world_claim=real,
        notes=tuple(notes),
    )


def write_comparison(path: Path, comparison: RetrievalComparison) -> None:
    """Write ``retrieval_eval.json`` atomically; refuses to overwrite."""
    write_json_atomic(path, comparison.model_dump(mode="json"))


__all__ = ["chunk_resolver", "compare_retrieval", "write_comparison"]
