# Geoptimiser: an evidence-grounded GEO audit tool

Technical presentation outline (Markdown; one `##` per slide). Every claim here is backed
by code and tests in the repository; items that are mocked, skipped or only proposed are
labelled as such.

---

## 1. Problem and users

* People increasingly get answers from AI search (generative engines) instead of link
  lists. Whether a site is *readable, extractable and quotable* by such systems is a
  technical question that site owners cannot easily inspect.
* **Generative Engine Optimization (GEO)** advice is often unsupported. Goal: an audit that
  separates **measured** properties from **heuristics** and **unavailable** measurements,
  and ties every finding to evidence on a source page.
* Users: small-site owners and web teams who want a checklist they can verify, and who
  accept that no tool can promise AI citations.
* Explicit non-goal: guaranteeing mentions or citations. The product never claims it.

## 2. Architecture and data flow

URL → validation → **crawl** → **extract** → **120-feature catalog (81 checks)** →
**chunk** → **retrieve** → **diagnose** → **recommend** → *(optional agent)* →
**final validation** → JSON + HTML **report** → **compare** with an earlier audit.

* Local-first: Python, SQLite for metadata, files for artifacts, a small FastAPI service,
  a static UI. Optional extras: `api`, `agent`, `semantic`; the base install needs only
  `pydantic`.
* Raw observations and derived data are separate, versioned files; every audit records the
  versions it ran with.
* Diagram and boundaries: `docs/ARCHITECTURE.md`; operations: `docs/APP.md`.

## 3. Crawler security and extraction

* A crawler that fetches user-chosen URLs is an SSRF risk. Defences: DNS resolved once and
  **pinned to public IPs only**, peer re-check after connect, manual redirect validation
  (scheme, port, credentials, scope, robots, https→http), response/audit byte and time
  budgets, verified TLS, robots.txt, no JavaScript execution.
* New in Day 6: per-fetch **timings** (DNS, connect, TLS, time to headers, response,
  total). Anything the transport cannot expose is `not_measured` with a reason, never 0.
* Extractor v2 records headings, text, links with `rel`, images, landmarks, tables, lists,
  media, structured data and viewport; truncation by size limits is recorded and disclosed.
* Evidence: about 1,450 automated tests (with the optional extras installed) include mock-server, TLS and redirect-attack cases.
  Real-internet crawling was **not** exercised in the build sandbox (no DNS).

## 4. Feature engine, scoring, provenance

* Catalog of 120 features; 81 have implemented checks (40 fully, 41 partially); the rest
  are reported `not_measured`, never as a pass.
* Result states: pass / fail / warning / not_applicable / not_measured / error. Scores
  exclude unmeasured units and always show **coverage**; a score below the coverage
  threshold is "not reportable".
* Findings come from failing results; heuristic checks are labelled and get lower
  confidence. Every finding carries evidence references; located passages carry a chunk id
  and exact character range that reproduce the source text.
* Final validation re-checks that every finding and recommendation resolves to evidence of
  the same audit; otherwise the audit is `failed`, not `completed`.

## 5. Retrieval: BM25, semantic, hybrid, reranking

* Pages are split into heading-aware **chunks with exact offsets**. Retrieval ranks chunks
  to attach relevant passages to findings.
* Implemented: Okapi **BM25** (hand-verified scores); exact **dense** cosine search behind a
  versioned embedding interface (Sentence Transformers `all-MiniLM-L6-v2`, local inference,
  revision and normalisation recorded); **reciprocal rank fusion**; a **reranker** that
  cannot add or drop candidates. No vector database: an exact scan suffices at this scale.
* Explicitly not done: the real model was **never run here** (the Hugging Face Hub is
  blocked in the build environment); the shipped test embedder is word-overlap hashing and
  is labelled non-semantic; there is no cross-encoder.

## 6. The LangGraph agent

* Optional and bounded: `inspect → decide ↔ act → finalize`, a typed state, a budget of
  model calls, bounded retries for transient errors only.
* Five or six **allowlisted tools** wrapping existing functions (list/get findings,
  retrieve passages, validate evidence, generate recommendations, validate output). No
  shell, code, file or network tools.
* Backend: OpenRouter (default `nvidia/nemotron-3-ultra-550b-a55b:free`), key from the
  environment only, no fallback model. Page text is delivered as quoted data and cannot
  change permissions or the outcome.
* The outcome comes from independent validation, not from the model's claim. Failures make
  the audit `incomplete`; the deterministic results remain.
* Status: tested with scripted and rule-based **fake** models only. The live model has not
  been run; a live smoke test exists and is skipped without a key.

## 7. Evaluation: methodology and actual results

* Three constructed data sets, kept separate: a plumbing fixture, a **paraphrase probe**
  (no shared content words) and a **lexical control**. Metrics: MRR, hit rate, Recall@k,
  nDCG@k, latency (`docs/EVALUATION.md`).
* Obtained here: BM25 = 0.000 nDCG@10 on the paraphrase probe and 1.000 on the control, by
  construction. The word-overlap "dense" test embedder reached 0.111 on the probe (chance).
  All modes tied on the plumbing set.
* **Not obtained:** any result for real semantic embeddings. We therefore make **no claim**
  that semantic or hybrid retrieval improves results, and no generalisation from 3–9
  queries.
* AI-search visibility measurement has only mock providers; no real observation exists.

## 8. Demonstration scenario

```bash
pip install -e '.[agent]'
python -m geoptimiser.demo --out demo_output
```

1. Audit a bundled mock site (demo data) → completed audit, score with coverage.
2. Follow one finding: **Title presence fails on `/about`** → evidence reference → chunk and
   character range → recommendation → verification plan (`SUMMARY.md`).
3. Show that the page's "ignore all previous instructions" text is data: findings are
   unchanged and the HTML report shows it escaped.
4. The site is "fixed"; a second audit and a **comparison** show resolved and persistent
   findings, with the statement that this is a measured difference, not proof of cause.
5. Show the UI over the stored audits and a restart (`python -m geoptimiser.app serve`).

## 9. Limitations, risks, future work

* **Not production-ready:** no authentication or user isolation, local-only, single worker,
  no resume of interrupted audits (`docs/SECURITY.md`, `docs/DEPLOYMENT_REQUIREMENTS.md`).
* Scores cover only crawled pages and implemented checks; heuristics can be wrong.
* No real AI-visibility provider; recommendation impact is always "uncertain".
* Real model runs (embeddings, OpenRouter) and real-site audits are still to do.
* **Future:** run and report the real-model benchmark; human-reviewed benchmark; live
  provider adapter; ownership verification, auth and tenancy; deployment (provider open);
  LoRA/fine-tuning only if measured against a simple baseline.
