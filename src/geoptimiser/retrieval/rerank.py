"""Reranking behind an interface that cannot add or lose candidates."""

from collections.abc import Sequence
from typing import NamedTuple, Protocol

from geoptimiser.retrieval.text import TokenizerConfig, tokenize


class Candidate(NamedTuple):
    chunk_id: str
    text: str


class RerankError(RuntimeError):
    """The reranker failed or did not return exactly the candidates it was given."""


class Reranker(Protocol):
    name: str
    version: str

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> Sequence[str]:
        """Return the candidates' chunk_ids, best first."""
        ...


class TermCoverageReranker:
    """Orders candidates by the share of distinct query terms they contain.

    A simple deterministic baseline, not a learned cross-encoder. Ties keep the
    incoming order (a stable sort).
    """

    name = "term-coverage"
    version = "1"

    def __init__(self) -> None:
        self._tokenizer = TokenizerConfig()

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[str]:
        wanted = set(tokenize(query, self._tokenizer))

        def coverage(candidate: Candidate) -> float:
            if not wanted:
                return 0.0
            have = set(tokenize(candidate.text, self._tokenizer))
            return len(wanted & have) / len(wanted)

        return [c.chunk_id for c in sorted(candidates, key=lambda c: -coverage(c))]


def apply_reranker(
    reranker: Reranker, query: str, candidates: Sequence[Candidate]
) -> list[str]:
    """Run ``reranker`` and prove its output is a permutation of the input ids."""
    try:
        order = list(reranker.rerank(query, candidates))
    except Exception as exc:
        raise RerankError(f"{reranker.name} failed: {type(exc).__name__}") from exc
    expected = [c.chunk_id for c in candidates]
    if sorted(order) != sorted(expected):
        raise RerankError(f"{reranker.name} added, dropped or repeated candidates")
    return order
