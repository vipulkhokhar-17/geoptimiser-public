# Evaluation

What was measured, what was not, and how far the numbers can be trusted.

## Retrieval comparison

Command (reproducible; no network):

```bash
python -m tests.retrieval.semantic.run_benchmark --out build/eval --allow-test-embedder
```

It compares four modes over the same chunks, queries and labels, using the Stage 04 metrics
(MRR, hit rate@k, Recall@k, nDCG@k) and wall-clock latency per query: **lexical** (BM25),
**dense** (exact cosine), **hybrid** (reciprocal rank fusion of lexical and dense) and
**hybrid_rerank** (hybrid followed by the term-coverage reranker, which cannot add or drop
candidates). The three data sets are constructed fixtures, kept separate and never pooled:

| Set | Purpose | Size |
|---|---|---|
| `plumbing` | checks that every code path and metric works | 7 pages / 9 chunks, 8 queries |
| `paraphrase` | queries that share **no** content word with the target page, so only a semantic model should find them | 10 pages, 9 queries |
| `lexical_control` | queries that reuse the page's own words, where BM25 should do well | 10 pages, 3 queries |

### Results actually obtained here (hashing embedder: NOT semantic)

The real embedding model could not be run in this build environment (`huggingface.co` is
blocked by its network policy, and the optional `sentence-transformers` extra is not
installed in the default environment). The "dense" column below therefore uses the
deterministic **word-overlap hashing test embedder** (`hashing-bow` v1, 256 dimensions,
`semantic=false`). These numbers validate the plumbing and BM25 only; they say **nothing**
about semantic retrieval.

plumbing

| mode | MRR | hit@1 | hit@3 | Recall@10 | nDCG@10 | p50 ms |
|---|---|---|---|---|---|---|
| lexical | 0.750 | 0.750 | 0.750 | 0.583 | 0.646 | 0.01 |
| dense (hashing) | 0.750 | 0.750 | 0.750 | 0.583 | 0.646 | 0.15 |
| hybrid | 0.750 | 0.750 | 0.750 | 0.583 | 0.646 | 0.16 |
| hybrid_rerank | 0.750 | 0.750 | 0.750 | 0.583 | 0.646 | 0.17 |

paraphrase

| mode | MRR | hit@1 | hit@3 | Recall@10 | nDCG@10 | p50 ms |
|---|---|---|---|---|---|---|
| lexical | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.01 |
| dense (hashing) | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.15 |
| hybrid | 0.056 | 0.000 | 0.111 | 0.111 | 0.070 | 0.17 |
| hybrid_rerank | 0.056 | 0.000 | 0.111 | 0.111 | 0.070 | 0.18 |

lexical_control

| mode | MRR | hit@1 | hit@3 | Recall@10 | nDCG@10 | p50 ms |
|---|---|---|---|---|---|---|
| lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.03 |
| dense (hashing) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.17 |
| hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.18 |
| hybrid_rerank | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.22 |

Reading them correctly:

* BM25 scores exactly 0 on the paraphrase set and 1.0 on the control set. That is by
  construction (the paraphrase queries share no content word with their targets; this is
  asserted by an always-run test), so it demonstrates the construction, not retrieval
  quality.
* The hashing "dense" result on the paraphrase set (1 of 9 queries) is chance-level hash
  overlap, not semantics. All four modes tie on the plumbing set.
* Latencies are single-process wall-clock times on tiny corpora and vary run to run.
* **Not obtained:** results for the real `sentence-transformers/all-MiniLM-L6-v2` model.
  When it is available the same command without `--allow-test-embedder` (after
  `pip install -e '.[semantic]'`) writes `<set>.retrieval_eval.json` files that record the
  model id, resolved revision, dimensions, normalisation and library versions, and the
  `semantic`-marked tests assert only a loose floor (hit@3 ≥ 0.7 on the paraphrase probe
  and dense nDCG above BM25). **Those assertions have never been executed.** Whether
  semantic or hybrid retrieval helps on real sites is unmeasured.

### Limits of this evaluation

* Three small, hand-constructed, English data sets; labels are `origin: fixture`, query sets
  are drafts, and `real_world_claim` is false in every report. No generalisation is claimed.
* Page-level judgments make every chunk of a labelled page relevant, which lowers Recall@k
  for long pages.
* No human-reviewed benchmark and no evaluation on real websites exists.
* Differences between methods on these sets are not tested for significance; with 3–9
  queries they could not be.
* Tokenisation has no stemming, so `encrypt` does not match `encrypted`.

## Other measurements and their status

| Item | Status |
|---|---|
| Feature results and scores | **Measured** on crawled pages, with coverage; only implemented checks count (82 of 120 catalog features have a check; the rest are reported `not_measured`) |
| Heuristic findings | Marked `basis: heuristic` with lower confidence; prompts for review, not verified defects |
| Cross-feature findings | Heuristic co-occurrence rules; no causal claim |
| Fetch timings | **Measured** where the transport exposes them, `not_measured` with a reason otherwise |
| AI-search visibility (Stages 05–06) | **No live provider exists.** Only mock/fixture observations exist and the metrics code labels them as such; nothing in the application reports real AI visibility |
| Recommendation impact | Always `uncertain` unless a justified rule says otherwise; none ships |
| Before/after comparison | Descriptive differences between two audits; not causal |
| LLM agent quality | Exercised only with scripted/rule-based fake models; the real OpenRouter model has not been run |
