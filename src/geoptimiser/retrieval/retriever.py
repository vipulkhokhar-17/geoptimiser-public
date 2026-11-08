"""Lexical, dense, hybrid and reranked retrieval over one chunk collection."""

from collections.abc import Sequence
from typing import Literal

from pydantic import Field, model_validator

from geoptimiser.retrieval.bm25 import Bm25Config, Bm25Index
from geoptimiser.retrieval.dense import DenseIndex, EmbeddingProvider
from geoptimiser.retrieval.fusion import reciprocal_rank_fusion
from geoptimiser.retrieval.rerank import Candidate, Reranker, apply_reranker
from geoptimiser.retrieval.text import tokenize
from geoptimiser.schemas import Chunk, SchemaModel

Mode = Literal["lexical", "dense", "hybrid", "hybrid_rerank"]
MODES: tuple[Mode, ...] = ("lexical", "dense", "hybrid", "hybrid_rerank")


class RetrievalConfig(SchemaModel):
    top_k: int = Field(default=10, ge=1, le=100)
    candidates: int = Field(default=50, ge=1, le=500)  # per source, before fusion
    rrf_k: int = Field(default=60, ge=1, le=1000)
    bm25: Bm25Config = Bm25Config()

    @model_validator(mode="after")
    def _candidates_cover_top_k(self):  # type: ignore[no-untyped-def]
        if self.candidates < self.top_k:
            raise ValueError("candidates must be at least top_k")
        return self


class RetrievedChunk(SchemaModel):
    chunk_id: str
    rank: int  # 1-based
    score: float
    score_kind: Literal["bm25", "cosine", "rrf", "rrf+rerank"]
    # rank of this chunk in each contributing source list (empty for single-source)
    source_ranks: dict[str, int] = Field(default_factory=dict)


class RetrievalResult(SchemaModel):
    query: str
    mode: Mode
    hits: tuple[RetrievedChunk, ...]
    note: str | None = None  # e.g. the query had no usable terms

    @property
    def chunk_ids(self) -> list[str]:
        return [h.chunk_id for h in self.hits]


class ModeUnavailable(RuntimeError):
    """The requested mode needs a component this retriever was built without."""


class Retriever:
    """Holds the indexes; every result is a ranking of real ``chunk_id`` values.

    Retrieved text is untrusted data: nothing here interprets it, and a ranking never
    contains an id that is not in the chunk collection.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        config: RetrievalConfig | None = None,
        *,
        embedder: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
        require_semantic: bool = False,
    ) -> None:
        self.config = config or RetrievalConfig()
        self.chunks = {c.chunk_id: c for c in chunks}
        if len(self.chunks) != len(chunks):
            raise ValueError("chunk_ids must be unique")
        if require_semantic and (embedder is None or not embedder.semantic):
            raise ValueError(
                "semantic retrieval was required but the embedder is "
                + ("missing" if embedder is None else f"non-semantic ({embedder.name})")
            )
        self.embedder = embedder
        self.reranker = reranker
        self.bm25 = Bm25Index(chunks, self.config.bm25)
        self.dense = DenseIndex(chunks, embedder) if embedder else None

    def available_modes(self) -> tuple[Mode, ...]:
        modes: list[Mode] = ["lexical"]
        if self.dense:
            modes += ["dense", "hybrid"]
            if self.reranker:
                modes.append("hybrid_rerank")
        return tuple(modes)

    def retrieve(
        self, query: str, mode: Mode = "lexical", k: int | None = None
    ) -> RetrievalResult:
        if mode not in self.available_modes():
            raise ModeUnavailable(f"mode {mode!r} needs a component not configured")
        k = k or self.config.top_k
        if not tokenize(query, self.config.bm25.tokenizer):
            return RetrievalResult(
                query=query, mode=mode, hits=(), note="query has no searchable terms"
            )
        pool = max(self.config.candidates, k)
        if mode == "lexical":
            return self._single(query, mode, self.bm25.search(query, k), "bm25")
        assert self.dense is not None
        if mode == "dense":
            return self._single(query, mode, self.dense.search(query, k), "cosine")
        lexical = [h.chunk_id for h in self.bm25.search(query, pool)]
        dense = [h.chunk_id for h in self.dense.search(query, pool)]
        fused = reciprocal_rank_fusion(
            {"lexical": lexical, "dense": dense}, self.config.rrf_k
        )
        if mode == "hybrid":
            top = fused[:k]
            kind = "rrf"
            order = [h.chunk_id for h in top]
        else:
            assert self.reranker is not None
            kind = "rrf+rerank"
            candidates = [
                Candidate(h.chunk_id, self.chunks[h.chunk_id].text) for h in fused
            ]
            order = apply_reranker(self.reranker, query, candidates)[:k]
        by_id = {h.chunk_id: h for h in fused}
        hits = tuple(
            RetrievedChunk(
                chunk_id=cid,
                rank=i,
                score=by_id[cid].score,
                score_kind=kind,
                source_ranks=by_id[cid].source_ranks,
            )
            for i, cid in enumerate(order, start=1)
        )
        return RetrievalResult(query=query, mode=mode, hits=hits)

    @staticmethod
    def _single(query, mode, scored, kind) -> RetrievalResult:  # type: ignore[no-untyped-def]
        hits = tuple(
            RetrievedChunk(chunk_id=s.chunk_id, rank=i, score=s.score, score_kind=kind)
            for i, s in enumerate(scored, start=1)
        )
        return RetrievalResult(query=query, mode=mode, hits=hits)
