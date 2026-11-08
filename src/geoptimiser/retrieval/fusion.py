"""Reciprocal rank fusion with deterministic ties and per-source provenance."""

from collections.abc import Mapping, Sequence

from pydantic import Field

from geoptimiser.schemas import SchemaModel


class FusedHit(SchemaModel):
    chunk_id: str
    score: float
    source_ranks: dict[str, int] = Field(default_factory=dict)  # 1-based


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]], k: int = 60
) -> list[FusedHit]:
    """Fuse ranked id lists: ``score(d) = sum over sources of 1 / (k + rank)``.

    A repeated id within one list counts once, at its first rank. Ties break on the
    best source rank, then ``chunk_id``, so the output never depends on dict or set
    order. Sources are accumulated in sorted name order for reproducible floats.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for source in sorted(rankings):
        seen: set[str] = set()
        position = 0
        for chunk_id in rankings[source]:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            position += 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position)
            ranks.setdefault(chunk_id, {})[source] = position
    fused = [
        FusedHit(chunk_id=c, score=s, source_ranks=ranks[c]) for c, s in scores.items()
    ]
    fused.sort(key=lambda h: (-h.score, min(h.source_ranks.values()), h.chunk_id))
    return fused
