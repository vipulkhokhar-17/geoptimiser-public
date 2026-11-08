"""Configured construction of the retrieval stack, with no silent embedder swap."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from geoptimiser.retrieval.dense import (
    EmbeddingProvider,
    EmbeddingUnavailable,
    HashingEmbedder,
)
from geoptimiser.retrieval.rerank import Reranker
from geoptimiser.retrieval.retriever import RetrievalConfig, Retriever
from geoptimiser.retrieval.sbert import (
    Loader,
    SentenceTransformerConfig,
    SentenceTransformerEmbedder,
    default_loader,
)
from geoptimiser.schemas import Chunk, SchemaModel

EmbedderKind = Literal["sentence-transformers", "hashing-test"]


class EmbedderSettings(SchemaModel):
    kind: EmbedderKind = "sentence-transformers"
    sentence_transformers: SentenceTransformerConfig = SentenceTransformerConfig()
    hashing_dimensions: int = 256


class RetrievalSettings(SchemaModel):
    embedder: EmbedderSettings = EmbedderSettings()
    retrieval: RetrievalConfig = RetrievalConfig()


class SettingsError(ValueError):
    """The retrieval settings file is unreadable or invalid."""


def load_settings(path: Path) -> RetrievalSettings:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return RetrievalSettings.model_validate(data)
    except (OSError, UnicodeDecodeError) as exc:
        raise SettingsError(f"{path}: cannot read ({type(exc).__name__})") from exc
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{path}: invalid JSON at line {exc.lineno}") from exc
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise SettingsError(f"{path}: {where}: {first['msg']}") from exc


def build_embedder(
    settings: EmbedderSettings,
    *,
    allow_test_embedder: bool = False,
    loader: Loader = default_loader,
) -> EmbeddingProvider:
    """The embedder the settings ask for, or an error; never a different one.

    The word-overlap test embedder is refused unless the caller opts in explicitly,
    which only unit tests and plumbing checks should do.
    """
    if settings.kind == "hashing-test":
        if not allow_test_embedder:
            raise EmbeddingUnavailable(
                "the hashing-test embedder is a deterministic test double, not "
                "semantic retrieval; pass allow_test_embedder=True to use it"
            )
        return HashingEmbedder(settings.hashing_dimensions)
    return SentenceTransformerEmbedder(settings.sentence_transformers, loader=loader)


def build_retriever(
    chunks: Sequence[Chunk],
    settings: RetrievalSettings | None = None,
    *,
    reranker: Reranker | None = None,
    allow_test_embedder: bool = False,
    loader: Loader = default_loader,
) -> Retriever:
    """The configured semantic retrieval path: BM25 + exact dense + hybrid (+ rerank).

    Index construction embeds the corpus, so a missing model fails *here* with
    ``EmbeddingUnavailable`` rather than degrading to lexical-only results.
    """
    settings = settings or RetrievalSettings()
    embedder = build_embedder(
        settings.embedder, allow_test_embedder=allow_test_embedder, loader=loader
    )
    return Retriever(
        chunks,
        settings.retrieval,
        embedder=embedder,
        reranker=reranker,
        require_semantic=not allow_test_embedder,
    )
