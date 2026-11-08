import math

import pytest

from geoptimiser.retrieval import (
    Bm25Config,
    Bm25Index,
    Candidate,
    DenseIndex,
    EmbeddingError,
    HashingEmbedder,
    RerankError,
    TermCoverageReranker,
    TokenizerConfig,
    apply_reranker,
    reciprocal_rank_fusion,
    tokenize,
)
from tests.retrieval.conftest import chunks_of

HAND = {"d1": "apple banana apple", "d2": "banana cherry", "d3": "cherry date"}


def hand_index(**kw):
    chunks = chunks_of(HAND)
    by_text = {c.text: c.chunk_id for c in chunks}
    return Bm25Index(chunks, Bm25Config(**kw)), {k: by_text[v] for k, v in HAND.items()}


def test_tokenizer():
    assert tokenize("The Quick-brown fox, 2 of 42!") == ["quick", "brown", "fox", "42"]
    keep = TokenizerConfig(remove_stopwords=False, min_token_len=1)
    assert tokenize("The 2 of", keep) == ["the", "2", "of"]
    assert tokenize("") == []


def test_bm25_hand_computed_scores():
    index, ids = hand_index()
    assert index.idf("apple") == pytest.approx(0.9808292530, abs=1e-9)
    assert index.idf("banana") == pytest.approx(0.4700036292, abs=1e-9)
    (hit,) = index.search("apple", 5)
    assert hit.chunk_id == ids["d1"]
    assert hit.score == pytest.approx(1.2483281402, abs=1e-9)
    banana = index.search("banana", 5)
    assert [h.chunk_id for h in banana] == [ids["d2"], ids["d1"]]
    assert banana[0].score == pytest.approx(0.4991762683, abs=1e-9)
    assert banana[1].score == pytest.approx(0.4208172029, abs=1e-9)


def test_bm25_parameters_change_scores_as_expected():
    no_norm, ids = hand_index(b=0.0)
    assert no_norm.search("apple", 1)[0].score == pytest.approx(1.3486402229, abs=1e-9)
    flat, _ = hand_index(k1=0.0)
    assert flat.search("apple", 1)[0].score == pytest.approx(0.9808292530, abs=1e-9)


def test_bm25_ties_break_on_chunk_id_and_repeated_query_terms_count_once():
    index, ids = hand_index()
    hits = index.search("cherry", 5)  # d2 and d3 score identically
    assert [h.chunk_id for h in hits] == sorted([ids["d2"], ids["d3"]])
    assert index.search("apple apple apple", 5)[0].score == pytest.approx(
        1.2483281402, abs=1e-9
    )


def test_bm25_edge_cases():
    index, _ = hand_index()
    assert index.search("zzz", 5) == []
    assert index.search("", 5) == []
    assert len(index.search("banana", 1)) == 1
    with pytest.raises(ValueError):
        index.search("apple", 0)
    assert Bm25Index([]).search("apple", 3) == []
    chunks = chunks_of(HAND)
    with pytest.raises(ValueError):
        Bm25Index([chunks[0], chunks[0]])
    with pytest.raises(ValueError):
        Bm25Config(b=1.5)


def test_bm25_fingerprint_depends_on_corpus_and_config():
    a, _ = hand_index()
    b, _ = hand_index()
    c, _ = hand_index(k1=1.5)
    assert a.fingerprint == b.fingerprint != c.fingerprint


# --- dense ---


def test_hashing_embedder_is_deterministic_and_not_semantic():
    e = HashingEmbedder(64)
    assert e.embed(["alpha beta"]) == e.embed(["alpha beta"])
    assert e.semantic is False and e.dimensions == 64
    assert e.embed([""]) == [[0.0] * 64]
    with pytest.raises(ValueError):
        HashingEmbedder(4)


def test_dense_exact_cosine_and_ordering():
    chunks = chunks_of(HAND)
    index = DenseIndex(chunks, HashingEmbedder(256))
    hits = index.search("apple banana apple", 3)
    top = hits[0]
    assert top.score == pytest.approx(1.0, abs=1e-9)
    assert chunks[0].chunk_id == top.chunk_id
    assert all(a.score >= b.score for a, b in zip(hits, hits[1:], strict=False))
    assert index.search("", 3) == []  # no signal is not a match


class Fixed:
    name, version, semantic, dimensions = "fixed", "9", True, 2

    def __init__(self, table, fail=False):
        self.table, self.fail = table, fail

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("secret-token-123")
        return [self.table[t] for t in texts]


def test_dense_hand_computed_cosine():
    chunks = chunks_of({"d1": "east", "d2": "north", "d3": "diag"})
    provider = Fixed(
        {"east": [1.0, 0.0], "north": [0.0, 1.0], "diag": [1.0, 1.0], "q": [2.0, 0.0]}
    )
    hits = DenseIndex(chunks, provider).search("q", 3)
    ids = {c.text: c.chunk_id for c in chunks}
    assert [h.chunk_id for h in hits] == [
        ids["east"],
        ids["diag"],
    ]  # north is 0, excluded
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == pytest.approx(1 / math.sqrt(2))


def test_dense_provider_failures_are_contained_and_do_not_leak():
    chunks = chunks_of({"d1": "east"})
    with pytest.raises(EmbeddingError) as err:
        DenseIndex(chunks, Fixed({}, fail=True))
    assert "secret-token" not in str(err.value) and "RuntimeError" in str(err.value)


def test_dense_rejects_bad_vectors():
    chunks = chunks_of({"d1": "east"})
    for bad in ([1.0], [1.0, float("nan")], [1.0, float("inf")]):
        with pytest.raises(EmbeddingError):
            DenseIndex(chunks, Fixed({"east": bad}))


def test_dense_fingerprint_tracks_provider_version():
    chunks = chunks_of({"d1": "east"})
    a = DenseIndex(chunks, Fixed({"east": [1.0, 0.0]}))
    p = Fixed({"east": [1.0, 0.0]})
    p.version = "10"
    assert a.fingerprint != DenseIndex(chunks, p).fingerprint


# --- fusion ---


def test_rrf_hand_computed():
    fused = reciprocal_rank_fusion({"a": ["x", "y", "z"], "b": ["y", "x"]}, k=60)
    by = {h.chunk_id: h for h in fused}
    assert by["x"].score == pytest.approx(1 / 61 + 1 / 62)
    assert by["y"].score == pytest.approx(1 / 62 + 1 / 61)
    assert by["z"].score == pytest.approx(1 / 63)
    # x and y tie; the tie breaks on best source rank (both 1), then chunk_id
    assert [h.chunk_id for h in fused] == ["x", "y", "z"]
    assert by["x"].source_ranks == {"a": 1, "b": 2}
    assert by["z"].source_ranks == {"a": 3}


def test_rrf_is_order_independent_and_dedupes():
    one = reciprocal_rank_fusion({"b": ["y", "x"], "a": ["x", "y", "x"]})
    two = reciprocal_rank_fusion({"a": ["x", "y"], "b": ["y", "x"]})
    assert one == two
    assert reciprocal_rank_fusion({}) == []
    assert reciprocal_rank_fusion({"a": []}) == []
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({"a": ["x"]}, k=0)


def test_rrf_single_source_preserves_order():
    assert [h.chunk_id for h in reciprocal_rank_fusion({"a": ["c", "a", "b"]})] == [
        "c",
        "a",
        "b",
    ]


# --- rerank ---


class Greedy:
    name, version = "greedy", "1"

    def __init__(self, mode):
        self.mode = mode

    def rerank(self, query, candidates):
        ids = [c.chunk_id for c in candidates]
        if self.mode == "drop":
            return ids[:-1]
        if self.mode == "add":
            return [*ids, "invented"]
        if self.mode == "dup":
            return [ids[0], *ids]
        if self.mode == "boom":
            raise ValueError("x")
        return ids[::-1]


CANDS = [Candidate("a", "alpha"), Candidate("b", "beta gamma"), Candidate("c", "gamma")]


def test_reranker_reorders_without_changing_the_set():
    assert apply_reranker(Greedy("reverse"), "q", CANDS) == ["c", "b", "a"]
    order = apply_reranker(TermCoverageReranker(), "gamma beta", CANDS)
    assert order == ["b", "c", "a"]


def test_reranker_that_adds_drops_or_fails_is_rejected():
    for mode in ("drop", "add", "dup", "boom"):
        with pytest.raises(RerankError):
            apply_reranker(Greedy(mode), "q", CANDS)


def test_term_coverage_keeps_incoming_order_on_ties_and_empty_query():
    assert apply_reranker(TermCoverageReranker(), "", CANDS) == ["a", "b", "c"]
    assert apply_reranker(TermCoverageReranker(), "zzz", CANDS) == ["a", "b", "c"]
