# Project specification

## Product
Geoptimiser.me is a Generative Engine Optimization (GEO) audit, recommendation, and experimentation platform.

## Primary user journey
1. User submits a domain they own or are authorized to audit, plus business context and target audience. Authorization is a user attestation, not verified ownership or a security control.
2. The platform safely crawls permitted pages and records raw observations.
3. A versioned feature registry computes deterministic technical and content measurements.
4. A curated query benchmark is run through selected AI-search providers.
5. Visibility outcomes and cited sources are analysed against the target brand and selected competitors.
6. RAG retrieves evidence from the target site, competitor/public sources, references, and prior verified experiments.
7. Diagnostic workflow generates evidence-linked findings.
8. Recommendation workflow proposes scoped changes with rationale, expected direction of impact, effort, confidence, and verification plan. Every recommendation originates from at least one finding and cites evidence.
9. A report is rendered from validated structured artifacts.
10. After the user applies an approved change, the same benchmark is rerun and changes are analysed with uncertainty and limitations documented.

## Product principles
- Evidence before prose.
- Every recommendation traces to at least one finding, and every finding traces to evidence. An opportunity is recorded as a finding before it becomes a recommendation.
- Measured checks and model judgements must be distinguishable.
- The report is rendered from structured artifacts, not generated as one unverified giant response.
- Use simple baselines before complex models or agents.
- Evaluate every model-related component.
- Never promise specific citation/visibility increases.
- Explicitly represent missing data, errors, uncertainty, and non-applicable checks.

## Initial scope
- Start with B2B SaaS as a narrow vertical.
- Start with a capped number of pages and a manually reviewed query benchmark.
- Start with one or two API-based AI-search providers and a mock provider for tests.
- No automatic publishing to customer websites in the MVP.
- No fine-tuning until a labelled dataset and an evaluation baseline exist.
- No vector database until chunking and retrieval baselines can be measured.
