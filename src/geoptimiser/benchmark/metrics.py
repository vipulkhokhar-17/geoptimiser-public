"""Ranking metrics with explicit, documented conventions (ADR-0015).

All functions take a ranked list of item ids (best first) and a mapping of item id to
relevance grade. Conventions:

* A ranking is de-duplicated, keeping the first occurrence of each id.
* An item is *relevant* if its grade is greater than 0. ``recall@k`` divides by the
  number of relevant items the corpus holds; a query with none has no defined recall,
  MRR, hit rate or nDCG, so callers must exclude it instead of scoring it 0.
* An empty ranking is a valid measurement (nothing retrieved) and scores 0.
* ``nDCG@k`` uses gain ``2**grade - 1`` and discount ``1 / log2(rank + 1)``, normalised
  by the ideal ordering of the graded items.
"""

import math
from collections.abc import Mapping, Sequence


def _check_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"k must be a positive integer, got {k!r}")


def dedupe(ranking: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(ranking))


def _relevant(grades: Mapping[str, int]) -> set[str]:
    return {item for item, grade in grades.items() if grade > 0}


def _require_relevant(grades: Mapping[str, int]) -> set[str]:
    relevant = _relevant(grades)
    if not relevant:
        raise ValueError("no relevant items: the metric is undefined for this query")
    return relevant


def recall_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    _check_k(k)
    relevant = _require_relevant(grades)
    return len(relevant & set(dedupe(ranking)[:k])) / len(relevant)


def hit_rate_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    _check_k(k)
    relevant = _require_relevant(grades)
    return 1.0 if relevant & set(dedupe(ranking)[:k]) else 0.0


def reciprocal_rank(ranking: Sequence[str], grades: Mapping[str, int]) -> float:
    relevant = _require_relevant(grades)
    for position, item in enumerate(dedupe(ranking), start=1):
        if item in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    _check_k(k)
    _require_relevant(grades)

    def dcg(items: Sequence[int]) -> float:
        return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(items[:k]))

    gains = [grades.get(item, 0) for item in dedupe(ranking)]
    ideal = sorted((g for g in grades.values() if g > 0), reverse=True)
    return dcg(gains) / dcg(ideal)


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (``q`` in 0..100) of a non-empty sample."""
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]
