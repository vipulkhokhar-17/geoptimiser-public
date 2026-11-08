"""Exact dense retrieval behind a versioned embedding-provider interface.

The shipped ``HashingEmbedder`` is a **deterministic test embedder** (signed feature
hashing of tokens). It captures word overlap, not meaning, and must never be reported
as semantic retrieval. A real embedding model plugs in through ``EmbeddingProvider``.
Search is an exact cosine scan: no approximate index is justified at this scale.
"""

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ValidationError

from geoptimiser.jsonl import write_json_atomic
from geoptimiser.retrieval.bm25 import Scored, corpus_fingerprint
from geoptimiser.retrieval.text import TokenizerConfig, tokenize
from geoptimiser.schemas import Chunk, SchemaModel

_BATCH = 64


class EmbeddingError(RuntimeError):
    """The provider failed or returned vectors the index cannot trust."""


class EmbeddingUnavailable(EmbeddingError):
    """The requested embedding model cannot be used here (missing extra or weights).

    Deliberately an error, never a cue to substitute another embedder.
    """


class EmbeddingIncompatible(EmbeddingError):
    """Query and document embeddings do not come from the same model setup."""


class EmbeddingDescriptor(SchemaModel):
    """Everything that decides whether two vectors can be compared."""

    name: str
    version: str
    dimensions: int
    semantic: bool
    model_id: str | None = None
    revision: str | None = None
    # Whether the provider itself returns unit vectors. The index always
    # L2-normalises, so similarity is cosine either way.
    normalized: bool = False
    similarity: Literal["cosine"] = "cosine"
    max_seq_length: int | None = None
    libraries: dict[str, str] = {}

    def compatibility_key(self) -> tuple[object, ...]:
        """Fields that must match; library versions are recorded but not compared."""
        data = self.model_dump(exclude={"libraries"})
        return tuple(sorted(data.items()))


class EmbeddingProvider(Protocol):
    name: str
    version: str  # bump when the vectors for the same text would change
    dimensions: int
    semantic: bool  # False for test embedders that only reflect word overlap

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Signed bag-of-words feature hashing. Deterministic; NOT semantic."""

    name = "hashing-bow"
    version = "1"
    semantic = False

    def __init__(self, dimensions: int = 256) -> None:
        if not 8 <= dimensions <= 4096:
            raise ValueError("dimensions must be between 8 and 4096")
        self.dimensions = dimensions
        self._tokenizer = TokenizerConfig()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token, count in Counter(tokenize(text, self._tokenizer)).items():
            digest = hashlib.sha256(token.encode()).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[slot] += sign * (1.0 + math.log(count))
        return vector


def describe(provider: EmbeddingProvider) -> EmbeddingDescriptor:
    """The provider's descriptor; a minimal one for providers that declare none."""
    try:
        declared = getattr(provider, "descriptor", None)
        if isinstance(declared, EmbeddingDescriptor):
            return declared
        return EmbeddingDescriptor(
            name=provider.name,
            version=provider.version,
            dimensions=provider.dimensions,
            semantic=provider.semantic,
        )
    except EmbeddingError:
        raise
    except Exception as exc:  # e.g. a lazy model load failing on first access
        raise EmbeddingError(
            f"{getattr(provider, 'name', 'provider')} could not describe itself: "
            f"{type(exc).__name__}"
        ) from exc


def _unit(vector: Sequence[float], dimensions: int) -> list[float] | None:
    if len(vector) != dimensions or not all(math.isfinite(x) for x in vector):
        raise EmbeddingError("embedding has the wrong size or non-finite values")
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else None


def _embed(provider: EmbeddingProvider, texts: Sequence[str]) -> list[list[float]]:
    try:
        vectors = provider.embed(texts)
    except EmbeddingError:
        raise  # already specific (unavailable, incompatible ...) and safe to show
    except Exception as exc:  # a provider bug must not crash the caller's run
        raise EmbeddingError(f"{provider.name} failed: {type(exc).__name__}") from exc
    if len(vectors) != len(texts):
        raise EmbeddingError(f"{provider.name} returned the wrong number of vectors")
    return vectors


_INDEX_SCHEMA = 1


def _fingerprint(descriptor: EmbeddingDescriptor, corpus: str) -> str:
    parts: list[object] = [
        "dense",
        descriptor.name,
        descriptor.version,
        descriptor.dimensions,
        corpus,
    ]
    if descriptor.model_id is not None or descriptor.revision is not None:
        parts += [descriptor.model_id, descriptor.revision]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


class DenseIndex:
    """Exact cosine search over unit-normalised chunk vectors.

    The index remembers the descriptor of the model that embedded its documents and
    refuses to be queried by anything that no longer matches it.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        provider: EmbeddingProvider,
        *,
        _vectors: list[list[float] | None] | None = None,
    ) -> None:
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("chunk_ids must be unique")
        self.provider = provider
        self._ids = ids
        self._corpus = corpus_fingerprint(chunks)
        # Documents are embedded in batches; the model is loaded once by the provider.
        # The descriptor is read after the first embedding so a lazily loaded model
        # reports its real dimensions and revision.
        if _vectors is not None:
            self._vectors = _vectors
            self.descriptor = describe(provider)
        else:
            self._vectors = []
            for start in range(0, len(chunks), _BATCH):
                batch = [c.text for c in chunks[start : start + _BATCH]]
                for vector in _embed(provider, batch):
                    self._vectors.append(self._unit(vector, provider))
            self.descriptor = describe(provider)
        self.fingerprint = _fingerprint(self.descriptor, self._corpus)

    @staticmethod
    def _unit(vector: Sequence[float], provider: EmbeddingProvider):
        return _unit(vector, describe(provider).dimensions)

    def __len__(self) -> int:
        return len(self._ids)

    def _check_compatible(self) -> None:
        current = describe(self.provider)
        if current.compatibility_key() != self.descriptor.compatibility_key():
            raise EmbeddingIncompatible(
                "the embedding model changed since this index was built "
                f"(built with {self.descriptor.model_id or self.descriptor.name} "
                f"{self.descriptor.version!r}, now "
                f"{current.model_id or current.name} {current.version!r})"
            )

    def search(self, query: str, k: int, *, min_score: float = 0.0) -> list[Scored]:
        """Top ``k`` chunks by cosine similarity strictly above ``min_score``."""
        if k < 1:
            raise ValueError("k must be at least 1")
        self._check_compatible()
        (raw,) = _embed(self.provider, [query])
        if len(raw) != self.descriptor.dimensions:
            raise EmbeddingIncompatible(
                f"query embedding has {len(raw)} dimensions, index has "
                f"{self.descriptor.dimensions}"
            )
        q = _unit(raw, self.descriptor.dimensions)
        if q is None:  # no signal in the query is not "similar to nothing"
            return []
        hits = []
        for chunk_id, vector in zip(self._ids, self._vectors, strict=True):
            if vector is None:
                continue
            score = sum(a * b for a, b in zip(q, vector, strict=True))
            if score > min_score:
                hits.append(Scored(chunk_id, score))
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:k]

    # --- persistence: re-embedding a corpus is the slow part -----------------------

    def save(self, path: Path) -> None:
        """Write the vectors and the descriptor that produced them (no overwrite)."""
        write_json_atomic(
            path,
            {
                "schema_version": _INDEX_SCHEMA,
                "descriptor": self.descriptor.model_dump(),
                "corpus_fingerprint": self._corpus,
                "chunk_ids": self._ids,
                "vectors": self._vectors,
            },
        )

    @classmethod
    def load(
        cls, path: Path, chunks: Sequence[Chunk], provider: EmbeddingProvider
    ) -> "DenseIndex":
        """Load saved vectors for ``chunks``, but only for the same model and corpus.

        Raises ``EmbeddingIncompatible`` if ``provider`` is not the model that made
        the vectors, and ``EmbeddingError`` if the file is unreadable, of another
        schema version, or describes a different corpus.
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            saved = EmbeddingDescriptor.model_validate(data["descriptor"])
            version = data["schema_version"]
            ids, vectors = data["chunk_ids"], data["vectors"]
            corpus = data["corpus_fingerprint"]
        except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
            raise EmbeddingError(
                f"{path}: unreadable index ({type(exc).__name__})"
            ) from exc
        if version != _INDEX_SCHEMA:
            raise EmbeddingError(
                f"{path}: unsupported index schema version {version!r}"
            )
        current = describe(provider)
        if current.compatibility_key() != saved.compatibility_key():
            raise EmbeddingIncompatible(
                f"{path} was built with {saved.model_id or saved.name} "
                f"{saved.version!r}, not {current.model_id or current.name} "
                f"{current.version!r}"
            )
        if corpus != corpus_fingerprint(chunks) or ids != [c.chunk_id for c in chunks]:
            raise EmbeddingError(f"{path}: index was built for a different chunk set")
        if len(vectors) != len(ids) or any(
            v is not None and len(v) != saved.dimensions for v in vectors
        ):
            raise EmbeddingError(f"{path}: vectors do not match the descriptor")
        return cls(chunks, provider, _vectors=vectors)
