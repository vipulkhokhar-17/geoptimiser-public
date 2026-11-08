"""Evaluate rankings against a judgment set and report what was (not) measured."""

from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from geoptimiser.benchmark import metrics
from geoptimiser.benchmark.models import JudgmentSet, QuerySet, Target
from geoptimiser.schemas import Identifier, SchemaModel, VersionedRecord

EVALUATION_VERSION = 1
# target -> {item id: 1}; empty means the target is not in the corpus.
TargetResolver = Callable[[Target], Mapping[str, int]]
ExclusionReason = Literal[
    "no_judgments",  # the query has no labels at all (unknown, not "irrelevant")
    "no_relevant_labels",  # every label is grade 0: recall and nDCG are undefined
    "unresolvable_targets",  # relevant labels point at targets absent from the corpus
    "no_ranking",  # the system produced no run for this query (missing, not empty)
]


class DatasetMismatch(ValueError):
    """The judgment set was written for a different query set (name or version)."""


class Exclusion(SchemaModel):
    query_id: Identifier
    reason: ExclusionReason


class QueryScores(SchemaModel):
    query_id: Identifier
    retrieved: int
    scores: dict[str, float]


class EvaluationReport(VersionedRecord):
    """Machine-readable result of one evaluation run.

    ``means`` average only the evaluated queries; it is ``None`` when none were.
    ``real_world_claim`` is false whenever the labels are fixture data.
    """

    evaluation_version: int = EVALUATION_VERSION
    query_set_name: Identifier
    query_set_version: int
    query_set_review_status: Literal["draft", "reviewed"]
    judgment_set_name: Identifier
    judgment_set_version: int
    judgment_origin: Literal["fixture", "human"]
    real_world_claim: bool
    ks: tuple[int, ...]
    n_queries: int
    n_evaluated: int
    per_query: tuple[QueryScores, ...]
    means: dict[str, float] | None
    excluded: tuple[Exclusion, ...]
    issues: tuple[str, ...]


def _identity(target: Target) -> Mapping[str, int]:
    return {target.url: 1}


def evaluate_rankings(
    queries: QuerySet,
    judgments: JudgmentSet,
    rankings: Mapping[str, Sequence[str]],
    *,
    ks: Sequence[int] = (1, 3, 5, 10),
    resolve: TargetResolver = _identity,
) -> EvaluationReport:
    """Score ``rankings`` (query id -> ranked item ids) with Recall@k, hit rate@k,
    nDCG@k and MRR.

    Rules: refuses a judgment set written for another query set; a query without
    usable labels, or without a run, is excluded and listed, never scored 0; labels for
    unknown queries or absent targets are reported in ``issues``.
    """
    if (judgments.query_set_name, judgments.query_set_version) != (
        queries.name,
        queries.version,
    ):
        raise DatasetMismatch(
            f"judgments are for {judgments.query_set_name} "
            f"v{judgments.query_set_version}, "
            f"not {queries.name} v{queries.version}"
        )
    for k in ks:
        metrics._check_k(k)
    known = {q.query_id for q in queries.queries}
    issues: list[str] = []
    for judgment in judgments.judgments:
        if judgment.query_id not in known:
            issues.append(f"judgment for unknown query {judgment.query_id!r}")
    for query_id in rankings:
        if query_id not in known:
            issues.append(f"ranking for unknown query {query_id!r}")

    per_query: list[QueryScores] = []
    excluded: list[Exclusion] = []
    for query in queries.queries:
        labels = judgments.for_query(query.query_id)
        if not labels:
            excluded.append(Exclusion(query_id=query.query_id, reason="no_judgments"))
            continue
        if not any(j.grade > 0 for j in labels):
            excluded.append(
                Exclusion(query_id=query.query_id, reason="no_relevant_labels")
            )
            continue
        grades: dict[str, int] = {}
        for judgment in labels:
            items = resolve(judgment.target)
            if not items:
                where = judgment.target.url
                if judgment.target.heading:
                    where += f" / {judgment.target.heading}"
                issues.append(
                    f"query {query.query_id!r}: target {where!r} is not in the corpus"
                )
                continue
            for item in items:
                grades[item] = max(grades.get(item, 0), judgment.grade)
        if not any(g > 0 for g in grades.values()):
            excluded.append(
                Exclusion(query_id=query.query_id, reason="unresolvable_targets")
            )
            continue
        if query.query_id not in rankings:
            excluded.append(Exclusion(query_id=query.query_id, reason="no_ranking"))
            continue
        ranking = metrics.dedupe(rankings[query.query_id])
        scores = {"mrr": metrics.reciprocal_rank(ranking, grades)}
        for k in ks:
            scores[f"recall@{k}"] = metrics.recall_at_k(ranking, grades, k)
            scores[f"hit_rate@{k}"] = metrics.hit_rate_at_k(ranking, grades, k)
            scores[f"ndcg@{k}"] = metrics.ndcg_at_k(ranking, grades, k)
        per_query.append(
            QueryScores(query_id=query.query_id, retrieved=len(ranking), scores=scores)
        )

    means = (
        {
            name: sum(q.scores[name] for q in per_query) / len(per_query)
            for name in per_query[0].scores
        }
        if per_query
        else None
    )
    return EvaluationReport(
        query_set_name=queries.name,
        query_set_version=queries.version,
        query_set_review_status=queries.review_status,
        judgment_set_name=judgments.name,
        judgment_set_version=judgments.version,
        judgment_origin=judgments.origin,
        real_world_claim=judgments.origin == "human"
        and queries.review_status == "reviewed",
        ks=tuple(ks),
        n_queries=len(queries.queries),
        n_evaluated=len(per_query),
        per_query=tuple(per_query),
        means=means,
        excluded=tuple(excluded),
        issues=tuple(issues),
    )
