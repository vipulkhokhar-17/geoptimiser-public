"""Stage 04: versioned query benchmark, relevance labels and ranking metrics."""

from geoptimiser.benchmark.evaluate import (
    DatasetMismatch,
    EvaluationReport,
    evaluate_rankings,
)
from geoptimiser.benchmark.loader import DatasetError, load_judgment_set, load_query_set
from geoptimiser.benchmark.models import (
    Intent,
    JudgmentSet,
    Query,
    QuerySet,
    RelevanceJudgment,
    Target,
)

__all__ = [
    "DatasetError",
    "DatasetMismatch",
    "EvaluationReport",
    "Intent",
    "JudgmentSet",
    "Query",
    "QuerySet",
    "RelevanceJudgment",
    "Target",
    "evaluate_rankings",
    "load_judgment_set",
    "load_query_set",
]
