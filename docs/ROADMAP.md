# Geoptimiser roadmap and implementation status

**Status snapshot: 2026-11-08.** This is the current implementation summary, not a promise that every capability is production-ready. “Implemented” means code exists; validation level is reported separately. The generated feature register at `src/geoptimiser/validation/feature_levels.json` is the source of truth for per-feature counts.

## Implemented pipeline

| Stage | Capability | Current status and limits |
|---|---|---|
| 00 | Shared schemas, package setup and quality workflow | Complete. |
| 01 | Safe, bounded website crawler | Implemented: bounded crawl, robots handling, SSRF/DNS-rebinding controls, redirect validation, TLS verification and request/response budgets. |
| 02 | HTML extraction and normalization | Implemented: extractor v3 includes structured HTML fields and extraction/render signals. It does not execute JavaScript or render browser DOM. |
| 03 | Feature registry and deterministic audit checks | 120-feature catalog; 41 implemented, 41 partial, 36 planned, 2 unavailable. Thus 82 checks run at some level; partial checks must be read with their limitations. |
| 04 | Query taxonomy and benchmark metrics | Benchmark and ranking metrics exist. The query set is a draft, not a human-reviewed benchmark. |
| 05 | Provider contract and visibility collection | Provider interface, credential gating and mock/fixture collection exist. **No live AI-search provider adapter is currently available.** |
| 06 | Visibility annotation and metrics | Annotation and rate metrics exist, including uncertainty intervals, but current observations are mock/fixture data only. They do not represent real AI-search visibility. |
| 07 | Structure-aware chunking | Implemented with heading-aware chunks and exact source offsets. |
| 08 | Retrieval and ranking evaluation | BM25, exact dense scan, reciprocal-rank fusion and a term-coverage reranker exist. Optional Sentence Transformers embeddings are implemented, but a real-model benchmark has not been established. |
| 09 | Evidence-linked diagnosis | Implemented: findings link to measurements and located passage evidence; heuristic findings carry limitations and confidence. |
| 10 | Recommendation generation and validation | Implemented: deterministic templates, claim/evidence checks, URL screening and recommendation validation. |
| 11 | Bounded agent investigation | Implemented with LangGraph and OpenRouter integration, allowlisted tools, iteration/tool limits and deterministic final validation. Tests use fake models; a live model-quality evaluation is not established. |
| 16 | Local API, persistence and UI | Implemented as a local-first FastAPI/SQLite application with browser UI, audit history, HTML/JSON reports and before/after comparisons. It has no authentication or multi-user isolation and must remain loopback-only. |

## Validation snapshot

The current generated register reports:

| Implementation status | Features |
|---|---:|
| Implemented | 41 |
| Partial | 41 |
| Planned | 36 |
| Unavailable | 2 |
| **Total** | **120** |

| Highest validation level | Features |
|---|---:|
| Pipeline validated against pre-declared synthetic fixtures (V2) | 35 |
| Unit tested only (V1) | 47 |
| Not tested (V0) | 38 |
| Labelled real-page benchmark (V3) | 0 |
| AI-search outcome validation | 0 |

A fixture pass establishes conformance to declared expectations on constructed inputs; it does not establish accuracy on real websites or an effect on AI answer citations/visibility. See [feature validation guide](project/FEATURE_VALIDATION_GUIDE.md), [validation methodology](validation/VALIDATION_METHODOLOGY.md), and the [generated register](../src/geoptimiser/validation/feature_levels.json).

## Remaining research and product work

| Area | Current state |
|---|---|
| Labelled real-world dataset | Not established. The checked-in 14-page corpus is a repository-local cross-check, not a representative or human-labelled web corpus. |
| AI-search visibility outcomes | No live provider adapter and no outcome validation. |
| LoRA/fine-tuning | Not started; requires a justified labelled dataset and baseline first. |
| Scoring/prioritization | Measurement scoring and coverage policies exist; business impact and priority calibration are not validated. |
| Reporting | JSON and HTML reports exist. A PDF export is not established as a current capability. |
| Experiment tracking | Before/after audit comparison exists; causal impact measurement and repeated controlled experiments remain future work. |
| Public backend deployment | Not ready. Authentication, authorization, tenant isolation, quotas, ownership checks, egress controls, TLS/reverse proxy, observability, backups and retention must be implemented and tested first. |

## Definition of done for future work

- Define explicit inputs, outputs, trust boundaries and failure states.
- Add unit tests for normal, malformed, adversarial and failure cases.
- Mock external network/model calls in deterministic tests; keep live tests opt-in.
- Record validation level and limitations separately from implementation status.
- Do not claim real-world accuracy, visibility improvement or business impact without the relevant labelled evaluation.
- Update this roadmap only when code and verification evidence support the status change.
