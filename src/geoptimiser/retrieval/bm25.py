"""Okapi BM25 over chunks (Stage 08, ADR-0019).

For a query term ``t`` and chunk ``d``::

    idf(t)  = ln(1 + (N - df + 0.5) / (df + 0.5))
    score   = sum over distinct query terms of
              idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avgdl))

``len`` counts tokens after the configured filtering. Only chunks containing at least
one query term are returned, ordered by score then ``chunk_id`` so ties are stable.
"""

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from typing import NamedTuple

from pydantic import Field

from geoptimiser.retrieval.text import TokenizerConfig, tokenize
from geoptimiser.schemas import Chunk, SchemaModel


class Scored(NamedTuple):
    chunk_id: str
    score: float


class Bm25Config(SchemaModel):
    k1: float = Field(default=1.2, ge=0, le=10)
    b: float = Field(default=0.75, ge=0, le=1)
    tokenizer: TokenizerConfig = TokenizerConfig()


def corpus_fingerprint(chunks: Sequence[Chunk]) -> str:
    """Identity of a chunk collection: ids and content hashes, order-independent."""
    pairs = sorted((c.chunk_id, c.text_sha256) for c in chunks)
    return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()


class Bm25Index:
    def __init__(self, chunks: Sequence[Chunk], config: Bm25Config | None = None):
        self.config = config or Bm25Config()
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("chunk_ids must be unique")
        self._ids = ids
        self._tf = [Counter(tokenize(c.text, self.config.tokenizer)) for c in chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._df: Counter[str] = Counter()
        for tf in self._tf:
            self._df.update(tf.keys())
        self._avgdl = sum(self._len) / len(ids) if ids else 0.0
        self.fingerprint = hashlib.sha256(
            json.dumps(
                ["bm25", self.config.model_dump(), corpus_fingerprint(chunks)]
            ).encode()
        ).hexdigest()

    def __len__(self) -> int:
        return len(self._ids)

    def idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1 + (len(self._ids) - df + 0.5) / (df + 0.5))

    def score(self, index: int, terms: Sequence[str]) -> float:
        tf, dl = self._tf[index], self._len[index]
        k1, b = self.config.k1, self.config.b
        norm = 1 - b + b * dl / self._avgdl if self._avgdl else 1.0
        total = 0.0
        for term in terms:
            freq = tf.get(term, 0)
            if freq:
                total += self.idf(term) * freq * (k1 + 1) / (freq + k1 * norm)
        return total

    def search(self, query: str, k: int) -> list[Scored]:
        if k < 1:
            raise ValueError("k must be at least 1")
        terms = sorted(set(tokenize(query, self.config.tokenizer)))
        hits = []
        for index, chunk_id in enumerate(self._ids):
            score = self.score(index, terms)
            if score > 0:
                hits.append(Scored(chunk_id, score))
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:k]
