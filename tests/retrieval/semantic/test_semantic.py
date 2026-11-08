"""Paraphrase probe: does retrieval work when query and answer share no words?

This is a small, constructed probe, not a benchmark of real sites. The first group of
tests needs no model and checks the probe itself. The ``semantic`` test uses the real
Sentence Transformers model and is skipped (not passed) when the extra or the model
is unavailable. Run it with:

    pip install -e '.[semantic]'
    python -m pytest tests/retrieval/semantic -m semantic -W error -rs
"""

import pytest

from geoptimiser.retrieval import (
    EmbeddingUnavailable,
    Retriever,
    SentenceTransformerEmbedder,
    TermCoverageReranker,
    compare_retrieval,
    tokenize,
)
from geoptimiser.retrieval.evaluate import chunk_resolver


def target_chunks(judgments, chunks):
    resolve = chunk_resolver(chunks)
    return {j.query_id: set(resolve(j.target)) for j in judgments.judgments}


# --- the probe itself (no model needed) ------------------------------------------------


def test_paraphrase_queries_share_no_content_word_with_their_targets(
    paraphrase, probe_chunks
):
    queries, judgments = paraphrase
    targets = target_chunks(judgments, probe_chunks)
    by_id = {c.chunk_id: c for c in probe_chunks}
    for query in queries.queries:
        query_terms = set(tokenize(query.text))
        for chunk_id in targets[query.query_id]:
            overlap = query_terms & set(tokenize(by_id[chunk_id].text))
            assert not overlap, (query.query_id, overlap)


def test_every_probe_query_has_exactly_one_target(paraphrase, probe_chunks):
    queries, judgments = paraphrase
    targets = target_chunks(judgments, probe_chunks)
    assert {q.query_id for q in queries.queries} == set(targets)
    assert all(len(t) == 1 for t in targets.values())


def test_bm25_cannot_rank_a_paraphrase_target_first(paraphrase, probe_chunks):
    queries, judgments = paraphrase
    targets = target_chunks(judgments, probe_chunks)
    retriever = Retriever(probe_chunks)
    for query in queries.queries:
        ranked = retriever.retrieve(query.text, "lexical", 10).chunk_ids
        assert not set(ranked) & targets[query.query_id]  # no shared word, no hit


def test_lexical_control_queries_are_found_by_bm25(control, probe_chunks):
    queries, judgments = control
    targets = target_chunks(judgments, probe_chunks)
    retriever = Retriever(probe_chunks)
    for query in queries.queries:
        top = retriever.retrieve(query.text, "lexical", 1).chunk_ids
        assert set(top) == targets[query.query_id]


# --- the real model (skipped unless available) -----------------------------------------


@pytest.fixture(scope="module")
def real_embedder():
    pytest.importorskip("sentence_transformers")
    embedder = SentenceTransformerEmbedder()
    try:
        embedder.embed(["warm-up"])  # loads once; downloads the weights if needed
    except EmbeddingUnavailable as exc:
        pytest.skip(f"model unavailable: {exc}")
    return embedder


@pytest.mark.semantic
def test_real_model_identity_is_recorded(real_embedder):
    d = real_embedder.descriptor
    assert d.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert d.semantic is True and d.dimensions == 384
    assert d.revision and d.similarity == "cosine"


@pytest.mark.semantic
def test_real_model_retrieves_paraphrases_that_bm25_cannot(
    real_embedder, paraphrase, probe_chunks
):
    queries, judgments = paraphrase
    retriever = Retriever(
        probe_chunks,
        embedder=real_embedder,
        reranker=TermCoverageReranker(),
        require_semantic=True,
    )
    cmp = compare_retrieval(queries, judgments, retriever)
    by = {r.mode: r.report.means for r in cmp.results if r.report and r.report.means}
    # A deliberately loose floor: with 9 queries and 10 pages a working embedder puts
    # the right page in the top 3 for most paraphrases. It is not a quality claim.
    assert by["dense"]["hit_rate@3"] >= 0.7, by["dense"]
    assert by["dense"]["ndcg@10"] > by["lexical"]["ndcg@10"]
    assert cmp.embedder_descriptor is not None and cmp.embedder_descriptor.semantic
    assert cmp.real_world_claim is False
