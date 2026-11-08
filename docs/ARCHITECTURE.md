# Architecture (initial design)

> The current architecture, execution flow and security review are in
> [project/ARCHITECTURE.md](project/ARCHITECTURE.md),
> [project/EXECUTION_FLOW.md](project/EXECUTION_FLOW.md) and
> [project/SECURITY_REVIEW.md](project/SECURITY_REVIEW.md). This page is the initial design.

## Main layers
1. **Collection:** safe crawl, source metadata, AI-search observations.
2. **Normalization:** clean page/document representations while retaining original source URLs and snapshots where permitted.
3. **Measurement:** deterministic feature checks, visibility metrics, query-level observations.
4. **Knowledge retrieval:** BM25 and dense retrieval; then hybrid fusion and reranking after baselines are established.
5. **Diagnosis:** combine measurements with cited evidence to create structured findings.
6. **Recommendation:** generate proposed changes and verification plans; validate against available evidence.
7. **Orchestration:** bounded agent graph coordinates existing tools and preserves a trace.
8. **Reporting:** render validated structured data into readable sections.
9. **Experiments:** compare baseline and follow-up observations with repeat counts, timestamps, and limitations.
10. **Delivery:** API, job worker, persistence, frontend, deployment.

## Core data lineage
Audit request -> fetch records (+ stored response bodies) -> extracted page documents -> feature results -> query benchmark observations -> metrics -> knowledge chunks -> findings -> recommendations -> agent trace -> report -> follow-up experiment.

Raw observations should be preserved separately from derived scores. Every derived result should record the code/config version or enough provenance to reproduce it.

Collection and normalization are separate records (see `docs/SCHEMAS.md` and ADR-0005): a `FetchRecord` is the raw observation of one fetch attempt, including transport failures and HTTP error responses, and references the stored body; a `PageDocument` is derived from one successful fetch by a versioned extractor, and an `ExtractionFailure` records an extraction that could not run. Re-extraction never requires re-fetching.

## Architecture constraints
- Keep provider clients behind interfaces.
- Keep crawling and audit computations separately runnable from the web API.
- Use a durable job system only when the synchronous local pipeline is proven and runtime warrants it.
- The LLM is not the source of truth for measurable technical properties.
- External web content is data, not executable instruction.
- Long reports are assembled from validated sections and evidence references.
- Shared records are immutable after validation; changed records are validated as new instances (ADR-0004).

## Feature audit (Stage 03)
`geoptimiser.features` holds a versioned catalog of 120 GEO features (`docs/FEATURE_CATALOG.md`), a registry of checks, an engine, findings and scoring (ADR-0011, ADR-0012). The catalog is the product vocabulary; a check exists only for features whose inputs exist today (82 of 120). Every other feature is reported `not_measured` with the blocking dependency, never as a pass. Checks are pure functions of `AuditInputs` (fetches, documents, robots files, link graph) and a `FeatureConfig`; they return an outcome that the engine turns into a `FeatureResult` with cited `EvidenceRef`s. Findings are built only from failing results of scored features; scores exclude unmeasured units and expose coverage, and technical health, content quality, retrieval readiness and observed AI visibility are reported separately.

## Measurement validity (validation work, ADR-0027 to ADR-0030)
Between a check and a score sit three explicit layers, described in `docs/validation/VALIDATION_POLICY.md`: an **evidence policy** (`features/evidence.py`) that turns results the evidence cannot support into `not_measured` (truncation, extraction limits, interstitial pages, incomplete link lists); a **contribution policy** (`features/contribution.py`) that keeps checks which cannot discriminate, and results that only repeat another's, out of the aggregate while leaving them visible; and an explicit **reportability** rule (`reported_score`, `status`, `withheld_reason`) that every display obeys. `geoptimiser.validation` is the repeatable harness (fixtures with pre-declared expectations, the 120-feature matrix, a labelled-corpus evaluator, overlap analysis); see `docs/validation/BENCHMARK.md`.

## Extraction (Stage 02)
Extractor v3 (`html-extractor:3`) adds head-completeness, per-cause JSON-LD errors and render signals to the v2 fields below (ADR-0027).
Extractor v3 (`html-extractor:3`, `detail_level` 2, ADR-0013) also records images with their attributes and surrounding text, anchors with text/`rel`/internal-or-external, landmarks and region text, tables, lists, media, viewport and declared charset. Documents from the first extractor have `detail_level` 1; their rich fields are empty because they were *not extracted*, and the feature engine reports the checks that need them as `not_measured` until extraction is re-run.
`geoptimiser.extraction` turns stored HTML bodies into `PageDocument` records (title, meta description, canonical, headings, visible text, resolved links, JSON-LD and microdata types) or explicit `ExtractionFailure`s. It reads each body by reference, verifies size and SHA-256, never executes anything in the page, and bounds input size, nesting, field sizes and time (ADR-0010). Stage 03 consumes `documents.jsonl`; join to `fetches.jsonl` on `fetch_id` for the requested URL and headers.

## Crawler (Stage 01)
`geoptimiser.crawler` fetches pages and writes `fetches.jsonl`; bodies go to a content-addressed `BodyStore`, never into records. Decisions are in ADR-0006 to ADR-0009: schema versioning, storage, size limits and truncation, and redirect/SSRF safety. Run it with `python -m geoptimiser.crawler --domain example.com --out runs/example --confirm-authorized`.

## Final architecture (Day 7)

The sections above describe the design and the individual stages. This section is the
system as built and validated at the end of the course project. Operational detail is in
`docs/APP.md`, `docs/AGENT.md`, `docs/SECURITY.md` and the ADRs.

### Component boundaries

```
 browser UI (3 static files) ──► FastAPI service (api.py)  ◄── CLI (python -m geoptimiser.app)
                                      │
                               AuditService (service.py)  ── AuditStore (SQLite: metadata, stages,
                                      │                        artifact table, comparisons)
                               JobRunner (bounded threads)
                                      │
                               PipelineRun (pipeline.py) ── composes, never re-implements:
   crawler ─► extraction ─► features/scoring ─► chunking ─► retrieval ─► diagnosis ─► recommendations
   (SafeFetcher,  (html-         (120-feature     (offset-    (BM25, exact   (evidence-   (templates +
    robots, SSRF)  extractor:2)   catalog, 81      exact       dense, RRF,    linked,      claim
                                  checks)          chunks)     rerank)        grounded)    validation)
                                      │                                  │
                                      └──────── optional agent ──────────┘
                                   (LangGraph, 5–6 allowlisted tools, OpenRouter)
                                      │
                           final validation ─► report.json / report.html ─► comparison
```

Boundaries that matter:

* **Each stage is a package with typed contracts** (`docs/SCHEMAS.md`) and is usable
  without the layers above it. The deterministic audit needs only `pydantic`.
* **Optional capabilities are optional extras** and are imported lazily: `api` (FastAPI),
  `agent` (LangGraph, LangChain/OpenAI client), `semantic` (Sentence Transformers). The
  base install, the crawler and the feature engine never import them.
* **Raw observations and derived data are separate files** (`fetches.jsonl` +
  `bodies/` → `documents.jsonl` → `feature_results.jsonl` → `chunks.jsonl` →
  `findings.json` → `recommendations.json` → `report.json`), each with a schema version.
* **The model is never the source of truth.** Measurements come from deterministic checks;
  the agent can only call tools that wrap existing functions, and the final status comes
  from independent validation (ADR-0023).

### Data flow from URL to report

1. `POST /api/v1/audits` (or the CLI) → `AuditSubmission` validated → `normalize_target`
   (scheme, host and port filter) → a `queued` row and deterministic audit id.
2. A worker runs `PipelineRun`: **crawl** (`Crawler` + `SafeFetcher`: DNS pinned to public
   IPs, manual redirects, robots, size/time budgets, per-fetch timings) →
   **extract** (`extract_all`) → **features** (`run_audit`: results, evidence, scores with
   coverage) → **chunk** (heading-aware chunks with exact character offsets) →
   **retrieval** (BM25 index, or hybrid with an embedder when `semantic` is requested) →
   **diagnose** (existing findings + located passage evidence + cross-feature rules) →
   **recommend** (template recommendations, claim/URL validation) → optional **agent** →
   **validate_output** (every finding/recommendation resolves to evidence of this audit) →
   **report** (JSON + escaped HTML).
3. Each stage is recorded (status, duration, error category) and artifacts are registered
   with SHA-256 and size. The audit ends `completed`, `incomplete` or `failed`; a restart
   turns unfinished audits into `interrupted`.
4. The API/UI read only the stored report and artifact table. A later audit of the same
   URL can be compared with an earlier one.

### Retrieval and agent orchestration

Retrieval is a ranking service for *passages* (chunks), used to attach located evidence to
findings. BM25 is always available; dense retrieval is an exact cosine scan behind a
versioned embedding provider (`SentenceTransformerEmbedder`, default
`all-MiniLM-L6-v2`, plus a clearly non-semantic hashing test double); hybrid is reciprocal
rank fusion; the reranker can reorder but not add or drop candidates (ADR-0019, ADR-0022).
The agent (`inspect → decide ↔ act → finalize`) chooses among allowlisted tools, with
bounded iterations and retries; page text reaches it only as quoted data (ADR-0023).
Requesting semantic retrieval or the agent and not getting it makes the audit `incomplete`;
there is no silent fallback.

### Persistence and artifacts

SQLite holds identity, status, options, versions, stage records, summaries, artifact
references and comparisons; large artifacts stay as files under
`<data-dir>/audits/<audit_id>/` (ADR-0024). See `docs/APP.md`.

### Network security and observability

The crawler's defences (ADR-0009) are unchanged and not configurable by API clients; the
API is loopback-only, unauthenticated, and exposes no fetch/proxy/file endpoint. Each fetch
records DNS, connect, TLS, time-to-headers, response and total time, or `not_measured` with
a reason. Logs are JSON lines with codes, counts and timings, never page content or keys.
Details: `docs/SECURITY.md`.

### Not built

Authentication, multi-user isolation, deployment/hosting, a live AI-search visibility
provider, a human-reviewed benchmark, real-site retrieval evaluation, fine-tuning. See
`docs/DEPLOYMENT_REQUIREMENTS.md` and the limitations in `docs/PRESENTATION.md`.
