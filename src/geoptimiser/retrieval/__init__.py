"""Stage 08: lexical, dense, hybrid and reranked retrieval over chunks."""

from geoptimiser.retrieval.bm25 import Bm25Config, Bm25Index, corpus_fingerprint
from geoptimiser.retrieval.dense import (
    DenseIndex,
    EmbeddingDescriptor,
    EmbeddingError,
    EmbeddingIncompatible,
    EmbeddingProvider,
    EmbeddingUnavailable,
    HashingEmbedder,
    describe,
)
from geoptimiser.retrieval.evaluate import (
    RetrievalComparison,
    chunk_resolver,
    compare_retrieval,
    write_comparison,
)
from geoptimiser.retrieval.fusion import FusedHit, reciprocal_rank_fusion
from geoptimiser.retrieval.rerank import (
    Candidate,
    Reranker,
    RerankError,
    TermCoverageReranker,
    apply_reranker,
)
from geoptimiser.retrieval.retriever import (
    MODES,
    ModeUnavailable,
    RetrievalConfig,
    RetrievalResult,
    RetrievedChunk,
    Retriever,
)
from geoptimiser.retrieval.sbert import (
    DEFAULT_MODEL,
    SentenceTransformerConfig,
    SentenceTransformerEmbedder,
)
from geoptimiser.retrieval.settings import (
    EmbedderSettings,
    RetrievalSettings,
    SettingsError,
    build_embedder,
    build_retriever,
    load_settings,
)
from geoptimiser.retrieval.text import TokenizerConfig, tokenize

__all__ = [
    "DEFAULT_MODEL",
    "EmbedderSettings",
    "EmbeddingDescriptor",
    "EmbeddingIncompatible",
    "EmbeddingUnavailable",
    "RetrievalSettings",
    "SentenceTransformerConfig",
    "SentenceTransformerEmbedder",
    "SettingsError",
    "build_embedder",
    "build_retriever",
    "describe",
    "load_settings",
    "MODES",
    "Bm25Config",
    "Bm25Index",
    "Candidate",
    "DenseIndex",
    "EmbeddingError",
    "EmbeddingProvider",
    "FusedHit",
    "HashingEmbedder",
    "ModeUnavailable",
    "RerankError",
    "Reranker",
    "RetrievalComparison",
    "RetrievalConfig",
    "RetrievalResult",
    "RetrievedChunk",
    "Retriever",
    "TermCoverageReranker",
    "TokenizerConfig",
    "apply_reranker",
    "chunk_resolver",
    "compare_retrieval",
    "corpus_fingerprint",
    "reciprocal_rank_fusion",
    "tokenize",
    "write_comparison",
]
