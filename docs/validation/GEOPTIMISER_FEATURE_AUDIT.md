# Geoptimiser feature audit and validation report

Date: 2026-10-27 · Base: `main` @ `220e9c7` · Branch: `claude/geoptimiser-validation-repair-ncsv4p`

This document accounts for all 120 catalog features, records which defects of the earlier
read-only audit were verified and corrected, and states plainly what remains
unvalidated. It is an engineering assessment, not a certification: a passing test suite
does not make a feature correct, and no feature has been shown to change visibility in any
answer engine. The register at the end is generated from the catalog and code
(`python -m geoptimiser.validation.matrix --write`) and checked by a test; everything
above it is hand-written.

Companion documents: [policy](VALIDATION_POLICY.md) (the rules the fixtures encode),
[methodology](VALIDATION_METHODOLOGY.md), [benchmark instructions](BENCHMARK.md),
[AI-outcome protocol](AI_OUTCOME_PROTOCOL.md), [work log](VALIDATION_WORK_LOG.md),
[matrix CSV](feature_validation_matrix.csv).

> **Historical snapshot note (2026-11-08).** This report preserves its original 2026-10-27 / 2026-11-01 audit narrative and counts. Do not treat its historical figures (81 running checks, 34 V2 features, etc.) as the current register. The current generated register is `src/geoptimiser/validation/feature_levels.json`: 41 implemented, 41 partial, 36 planned, 2 unavailable; validation levels are 35 pipeline-validated, 47 unit-tested, 38 not tested. No labelled real-page or AI-outcome validation exists. The current overview is in [README](../../README.md) and [roadmap](../ROADMAP.md).

> **Update 2026-11-01 (final master pass, `claude/geoptimiser-final-master`).** Sections 1–9
> describe the 2026-10-27 state and are kept as written. Since then: F110 (HTTPS and HSTS)
> is implemented (RFC 6797, source S14); F001 v2 treats 429, and 503 with Retry-After, as
> not measured; F070 v2 compares at most 200 distinct values (security audit run 1);
> `CATALOG_VERSION` is 3. Two fixtures were added (`k1_transport_security`,
> `e1_http_status`): 27 fixtures, 291 expectations, all met. Every feature now also has an
> implementation level, a validation level (with PIPELINE_VALIDATED: fixture expectations
> also met through the service and HTTP API) and a disposition code (ADR-0031). Sources
> S01, S03–S08 and S11–S13 were re-read at the primary source; S13 was corrected. The
> current counts are in the generated register (section 10), which supersedes the figures
> in section 1. See also [../project/FEATURE_VALIDATION_GUIDE.md](../project/FEATURE_VALIDATION_GUIDE.md).

## 1. Summary

* **Verified and corrected.** The systemic defects reported earlier were reproduced on
  the unmodified code and are fixed, each with a regression test: truncated or cut
  evidence reported as missing content (A1), unknown evidence reported as a pass or as a
  failure (A2), double-counted and non-discriminating checks (A3), category scores shown
  although withheld (A4), JSON-LD failures that blurred syntax errors with truncation (A5),
  a crawler/extractor mismatch on `<noscript>` and `<base href>` links (B2), owner-chosen
  settings graded as high-severity defects (B4), and findings that did not say what they
  could not know (B5/B6). One earlier claim did not hold: F010 and F018 are not duplicates
  (section 3).
* **Measurement benchmark.** 25 synthetic fixtures with expectations written before the
  fixes: the original code met 200 of 280 expectations (4 of 25 fixtures); the corrected
  code meets 280 of 280. Where the evidence could not support a verdict (expected
  `not_measured` or `not_applicable`) the original code reported a website failure 14
  times and a pass 4 times; the corrected code, 0 and 0. This shows the code now follows
  the written policy on constructed cases. It says nothing about accuracy on real websites.
* **No real-world benchmark exists.** No real snapshots were in the repository and the
  session could not reach websites. The shipped corpus is 14 repository pages labelled
  by an independent parser (105 labels, 0 disagreements). That is an extractor
  cross-check, not evidence of accuracy, and the 95%/80% precision targets are **not
  assessed**.
* **Dispositions (judgments, not facts).** Retain 24, Revise 15, Informational only 31,
  Investigate 50, Remove 0. Fifty are "Investigate" because their precision is unknown or
  they are unimplemented. 81 features run (40 implemented, 41 partial), 37 are planned and
  2 unavailable; 34 are exercised by a pre-declared fixture (V2), 47 by unit tests only
  (V1), none has a labelled real-page benchmark (V3).
* **Unsupported claims.** Every AI-retrieval or citation claim is unvalidated; category L
  (observed AI outcomes) is unimplemented. See the outcome protocol.
* **Biggest remaining gap.** JavaScript rendering (F108) is not implemented, so a result
  about text, title or links says what is in the HTML as fetched. Pages that look
  client-rendered are labelled; nothing says what a browser or a rendering crawler sees.

## 2. Starting state

| | Value |
|---|---|
| Branch / commit | `claude/geoptimiser-validation-repair-ncsv4p` at `220e9c7` (identical to `main` and `origin/main`; clean working tree) |
| Tests, CI default install (`.[dev]`) | 1442 passed, 13 skipped (skips: LangGraph/LangChain/FastAPI/sentence-transformers extras absent, live OpenRouter tests) |
| Tests with `agent`+`api` extras | 1485 passed, 4 skipped |
| Lint / format | `ruff check .` clean; `ruff format --check .` 206 files formatted |
| Type check | none configured in the repository |
| Catalog | 120 features: 40 implemented, 41 partial (81 run), 37 planned, 2 unavailable |
| Earlier audit artifacts | `GEOPTIMISER_FEATURE_AUDIT.md`, `feature_validation_matrix.csv` and `diagnose_empty_pages.py` are **not in the repository, in any remote branch or on disk**; the earlier findings were treated as claims and rebuilt |

Final state (clean `.[dev]` install): 1601 passed, 13 skipped (+159 tests); with extras
1644 passed, 4 skipped; lint and format clean. The skips are unchanged.

## 3. The earlier audit's claims, verified

| Claim | Verdict | Evidence |
|---|---|---|
| ~1,442 passing tests, 13 skips, 120 features, 81 working or partial | **Confirmed exactly** | baseline run; catalog |
| Truncated bodies are reported as having no title, text or valid JSON-LD | **Confirmed** | baseline on `a1_trunc_before_title`, `yt_like_truncated_large_head`: F021/F024/F011/F051 `fail` and findings raised; `a1_trunc_jsonld`: F061 `fail` and a "fix the JSON syntax" recommendation |
| Unknown evidence counts as pass or as failure | **Confirmed** | F012 `pass` for an uncrawled canonical target, `fail` for one that timed out (`a2_canonical_states`); robots body unreadable treated as allow-all (code + unit test) |
| F009 and F072 duplicate | **Confirmed**, exact at the default minimum of 1 | `test_f009_and_f072_agree_on_every_page_at_default_thresholds` |
| F052 and F059 duplicate | **Confirmed as a shared cause**: a missing `<main>` fails both (F052 fails -> F059 fails); F059 also has independent sub-tests | `a3_single_root_cause`; baseline raised both findings |
| F010 and F018 duplicate | **Not confirmed.** They read different data (link graph vs URL query string). What they share is that neither could fail under the default crawl | `overlap.py` decision |
| Overall score withheld while category scores look definitive | **Confirmed** | demo audit: category D `0.933` shown at 3 of 9 features measured, H `1.0` at 1 of 4, J `1.0` at 2 of 8 (HTML report and UI) |
| JSON-LD failures are not separated by cause | **Confirmed** | single error counter in the extractor |
| Crawler and extractor parse links differently, incl. `<noscript>` | **Confirmed**, plus a second mismatch found: `<base href>` | `b2_link_forms`, `b2_base_href` (baseline: page reachable only via `<noscript>` reported orphaned / unreachable; relative link under `<base>` crawled at the wrong URL) |
| Deliberate noindex / crawler blocks reported as high-severity defects | **Confirmed** | F004/F005/F006 had base severity `high` and `fail` |
| Specifics about YouTube | **Not verifiable** (no website access). Reproduced as a synthetic reconstruction of the mechanism; no claim about YouTube itself | section 5 |

Additional defects found: F015 passed every unredirected page (free pass); F018 could
never fail by default; F069 repeats F046/F048/F049; F017 counted refused or failing
targets (403/429/5xx) as broken links; an unreadable `robots.txt` body was allow-all;
interstitial challenge pages were scored as content; "not measured" reasons said only
"extraction was not run" for empty bodies and unsupported content types; some catalog
rationales claimed outcomes ("rarely cited", "internal authority") without support.

## 4. Defects corrected

| # | Defect | Fix | Regression tests |
|---|---|---|---|
| D1 | Truncation / extraction limits reported as confirmed missing content | `features/evidence.py` policies; extractor records `head_complete`, unterminated title; `not_measured` with the byte count | `a1_*`, `yt_like_*` fixtures; `test_evidence_policy.py` |
| D2 | Cut JSON-LD called a syntax error; wrong recommendation | per-block causes; F061 v2 | `a1_trunc_jsonld`, `a5_*`; `test_evidence_signals.py` |
| D3 | Canonical target unknown -> pass, timeout -> fail | F012 v2 | `a2_canonical_states`; `test_measurement_states.py` |
| D4 | Unreadable / cut robots.txt as allow-all | F004 v2 | `test_measurement_states.py` |
| D5 | Overlapping checks double counted | `contribution.py` (F072/F009, F059/F052, F069/F046-49) | `test_scoring_policy.py`, `test_overlap.py`, `a3_*` |
| D6 | Checks that cannot fail under the crawl | exclusion of F009/F010/F072 with reasons; F015 v2 (N/A without redirect); F018 v2 (linked URLs) | scoring and measurement tests |
| D7 | Withheld scores displayed | `reported_score`, `status`, `withheld_reason`; HTML, UI, compare read only that | `test_reportability.py`, `test_scoring_policy.py` |
| D8 | Link rules differ between crawler and extractor | shared rules in `crawler/urls.py` | `test_link_parity.py`, `b2_*` |
| D9 | Owner policy graded as defect | `intent_dependent`, `warning`, notice findings | `b4_*`, `test_measurement_states.py` |
| D10 | Interstitial pages scored | detection -> `not_measured` | `b1_interstitial` |
| D11 | Client-rendered shell wording; repeated high-severity combined findings | limitation on absence failures; combined findings skipped for such pages | `b1_js_shell`, `yt_like_js_heavy` |
| D12 | Opaque reasons for empty / non-HTML / failed extraction | explicit reasons | `b1_empty_blocked_nonhtml` |
| D13 | Refused or failing link targets counted as broken | F017 v2 | `test_measurement_states.py` |
| D14 | Unsupported causal wording in the catalog | rationales rewritten; deny-list test | `test_catalog.py` |

Report/UI additions: per-finding `kind` (defect / notice), `contributes_to_score`,
explanation column per measurement, a "Not measured" section, the exclusion reasons and
the JavaScript capability boundary in the limitations.

## 5. Before and after: the YouTube-like cases

Synthetic reconstructions of the *mechanism* described in the earlier audit (no real
site was fetched). Default crawl limit of 2,000,000 bytes.

| Case | Original code | Corrected code |
|---|---|---|
| **Large head, title beyond the cut** (`yt_like_truncated_large_head`, ~2.1 MB inline config before `<title>`) | F021 title `fail`, F024 description `fail`, F011 canonical `fail`, F051 text `fail`, F061 not applicable; findings `fnd_F021`, `fnd_F024`, `fnd_F011`, `fnd_F051` raised | F021/F024/F011/F051/F061 `not_measured` ("the stored response was truncated at 2,000,000 bytes ... content after the cut was not inspected"); F102 `fail` (truncated), F027 `pass` (the `<html lang>` was read); none of the four findings raised |
| **Script-built shell, intact head** (`yt_like_js_heavy`, ~300 KB) | F021/F024/F011 `pass`; F051, F052 `fail` with no note; combined *high* finding `syn_hard_to_extract` raised | same statuses (they describe the fetched HTML); F051/F052 carry "looks client-rendered ... does not execute JavaScript"; the finding repeats it; combined finding not raised |

## 6. Score changes and why

Same demo site, same crawl, original vs corrected code (`python -m geoptimiser.demo`):

| | Original | Corrected |
|---|---|---|
| Overall score | 0.854, **reportable** (45 of 84 scored features measured, 53.6%) | 0.8225, **withheld** (37 of 76, 48.7%; minimum 50%) |
| Categories shown that were below coverage | D 0.933 (3/9), H 1.0 (1/4), J 1.0 (2/8) | withheld, with the reason |
| Category A / B / C | 0.950 / 0.775 / 0.693 | 0.867 / 0.743 / 0.654 |

Cause: eight features that each scored 1.0 on this site no longer contribute - F004, F005,
F006, F030 (owner-policy notices, now unscored), F009, F010, F072 (cannot fail by
construction) and F015 (no page was redirected, so not applicable). Removing eight
perfect scores lowers the mean and removes eight measured features, which takes
coverage below the unchanged 50% threshold. Nothing about the site got worse.
Scores from before and after are not comparable (catalog and scoring version 2).
Because 39 scored features are unimplemented, the overall headline is capped near 55.7%
coverage even when every implemented feature applies and is measured; expect it to be
withheld often until more features exist.

## 7. Overlaps

Programmatic signatures found 7 exact data-signature pairs (most are shared helper
calls, not duplicates) plus the catalog's declared neighbours; with the named pairs,
`overlap.py` records a decision for each of 48. Judged to double count and now handled:
F009/F072, F052/F059, F046-F048-F049/F069 (unit rules), F017/F079 (F079 is unscored).
Judged related and independent: canonical presence/validity/consistency, title and
description presence/uniqueness/quality. Documented but not adjusted for lack of
evidence: F052/F055 on pages with no landmarks (a div-soup page can lose up to two
points of the same cause), F022/F080.

## 8. What is and is not validated

| Dimension | State |
|---|---|
| Implementation verified | 81 checks run; all with tests |
| Measurement correctness evaluated | 34 features by pre-declared synthetic fixtures; the rest by unit tests |
| Diagnostic accuracy benchmarked | none on real pages. 9 presence/validity features agree with an independent parser on 14 repository pages (0 of 105 labels disagree); this is a cross-check |
| Technical rationale supported | partly; sources are search-result summaries and none was read in full |
| AI-visibility outcome demonstrated | none |
| Business outcome demonstrated | none |

## 9. Limitations and blockers

* No access to websites from the session (CONNECT tunnel refused; page fetches failed at
  name resolution). No real-world corpus, no live reproduction of any named site.
* External sources were reachable only through a search tool returning summaries. All
  source entries are marked accordingly; primary pages must be read before the rationale
  column is relied on.
* No JavaScript rendering; interstitial and client-rendered detection are heuristic.
* Type checking is not configured in the repository; none was run.
* Thresholds are policy defaults: none is empirically derived (see the threshold
  register below).
* No live AI-provider data or authorisation: category L and every outcome claim remain
  unmeasured.
* The earlier audit's own artifacts could not be recovered.

## 10. Feature register (generated)



<!-- BEGIN GENERATED: feature register (python -m geoptimiser.validation.matrix --write) -->

### Counts

* **Features accounted for:** 120 (F001-F120, each once)
* **Implementation status (catalog):** implemented: 41, partial: 41, planned: 36, unavailable: 2
* **Recommended disposition:** Informational only: 32, Investigate: 49, Retain: 24, Revise: 15
* **Validation status:** V0: 38, V1: 47, V2: 35
* **Scoring role:** not measured: 38, scored: 50, scored; results that only repeat another feature's count once: 2, unscored: 26, unscored notice: 4
* **Implementation level:** IMPLEMENTED: 41, PARTIAL: 41, PLANNED: 36, UNAVAILABLE: 2, NOT_VERIFIABLE: 0
* **Validation level (highest reached):** NOT_TESTED: 38, UNIT_TESTED: 47, FIXTURE_VALIDATED: 0, PIPELINE_VALIDATED: 35, REAL_PAGE_VALIDATED: 0, OUTCOME_VALIDATED: 0
* **Reached at least (cumulative):** UNIT_TESTED: 82, FIXTURE_VALIDATED: 35, PIPELINE_VALIDATED: 35, REAL_PAGE_VALIDATED: 0, OUTCOME_VALIDATED: 0
* **Disposition code:** RETAIN: 24, REVISE: 15, INFORMATIONAL_ONLY: 32, REMOVE: 0, INVESTIGATE: 49

Validation levels: **NOT_TESTED** no check or no test; **UNIT_TESTED** unit tests only; **FIXTURE_VALIDATED** pre-declared synthetic fixture expectations met by the crawl-extract-feature harness; **PIPELINE_VALIDATED** those expectations also met through the application service and HTTP API (tests/validation/test_app_pipeline.py); **REAL_PAGE_VALIDATED** and **OUTCOME_VALIDATED** need a labelled real-world corpus and outcome data, which do not exist, so no feature is at those levels. Validation status codes: **V0** not implemented; **V1** implemented and unit-tested only; **V2** implemented and evaluated against pre-declared synthetic fixtures. **V3** (diagnostic accuracy benchmarked on labelled real pages) has not been reached by any feature. No feature has a demonstrated AI-visibility or business outcome.

### Register

| ID | Name | Status | Implementation | Validation level | Disposition | Scoring role | Confidence | Claim strength |
|---|---|---|---|---|---|---|---|---|
| F001 | HTTP success status | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | high | specified by a standard or vendor documentation |
| F002 | Crawlable page links | implemented | IMPLEMENTED | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | scored | medium | plausible mechanism |
| F003 | Robots.txt accessibility | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | medium | specified by a standard or vendor documentation |
| F004 | Robots policy compliance | implemented | IMPLEMENTED | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | unscored notice (warning, confirm intent) | medium | specified by a standard or vendor documentation |
| F005 | Meta robots directives | implemented | IMPLEMENTED | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | unscored notice (warning, confirm intent) | high | specified by a standard or vendor documentation |
| F006 | X-Robots-Tag directives | implemented | IMPLEMENTED | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | unscored notice (warning, confirm intent) | high | specified by a standard or vendor documentation |
| F007 | Sitemap availability | partial | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | specified by a standard or vendor documentation |
| F008 | Sitemap URL coverage | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F009 | Orphan-page risk | partial | PARTIAL | PIPELINE_VALIDATED | REVISE | scored, but excluded from the aggregate when it cannot discriminate (see scoring policy) | high | plausible mechanism |
| F010 | Crawl depth | implemented | IMPLEMENTED | PIPELINE_VALIDATED | REVISE | scored, but excluded from the aggregate when it cannot discriminate (see scoring policy) | high | plausible mechanism |
| F011 | Canonical tag presence | implemented | IMPLEMENTED | PIPELINE_VALIDATED | REVISE | scored | medium | specified by a standard or vendor documentation |
| F012 | Canonical target validity | partial | PARTIAL | PIPELINE_VALIDATED | RETAIN | scored | medium | specified by a standard or vendor documentation |
| F013 | Canonical consistency | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | medium | specified by a standard or vendor documentation |
| F014 | Duplicate page content | partial | PARTIAL | PIPELINE_VALIDATED | REVISE | scored | medium | specified by a standard or vendor documentation |
| F015 | Redirect-chain length | implemented | IMPLEMENTED | PIPELINE_VALIDATED | REVISE | scored | medium | plausible mechanism |
| F016 | Redirect-loop detection | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | high | specified by a standard or vendor documentation |
| F017 | Broken internal links | partial | PARTIAL | UNIT_TESTED | RETAIN | scored | medium | specified by a standard or vendor documentation |
| F018 | URL parameter proliferation | implemented | IMPLEMENTED | UNIT_TESTED | REVISE | scored | medium | plausible mechanism |
| F019 | URL semantic readability | implemented (heuristic) | IMPLEMENTED | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F020 | HTTPS consistency | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | high | specified by a standard or vendor documentation |
| F021 | Title presence | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | high | specified by a standard or vendor documentation |
| F022 | Title uniqueness | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | medium | plausible mechanism |
| F023 | Title descriptiveness | partial (heuristic) | PARTIAL | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | scored | medium | plausible mechanism |
| F024 | Meta-description presence | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | medium | specified by a standard or vendor documentation |
| F025 | Meta-description uniqueness | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | medium | plausible mechanism |
| F026 | Description-content alignment | partial (heuristic) | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | low | plausible mechanism |
| F027 | Language declaration | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | high | specified by a standard or vendor documentation |
| F028 | Character encoding declaration | implemented | IMPLEMENTED | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | specified by a standard or vendor documentation |
| F029 | Viewport configuration | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | medium | specified by a standard or vendor documentation |
| F030 | Search snippet restrictions | partial | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored notice (warning, confirm intent) | high | specified by a standard or vendor documentation |
| F031 | Main-topic clarity | partial (heuristic) | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | low | plausible mechanism |
| F032 | Search-intent coverage | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F033 | Direct-answer availability | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F034 | Key-information prominence | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F035 | Heading hierarchy | implemented | IMPLEMENTED | PIPELINE_VALIDATED | REVISE | scored | medium | plausible mechanism |
| F036 | Section descriptiveness | partial (heuristic) | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | low | plausible mechanism |
| F037 | Topical completeness | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F038 | Entity coverage | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F039 | Terminology consistency | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F040 | Question-and-answer coverage | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | high | hypothesis about ranking |
| F041 | Source citation presence | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | high | plausible mechanism |
| F042 | Citation-target validity | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F043 | Claim-evidence proximity | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F044 | Quantitative evidence | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F045 | Methodology transparency | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F046 | Author attribution | partial | PARTIAL | UNIT_TESTED | RETAIN | scored | low | specified by a standard or vendor documentation |
| F047 | Publisher identity | partial | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | low | plausible mechanism |
| F048 | Publication-date availability | partial | PARTIAL | UNIT_TESTED | RETAIN | scored | low | specified by a standard or vendor documentation |
| F049 | Modification-date availability | partial | PARTIAL | UNIT_TESTED | RETAIN | scored | low | specified by a standard or vendor documentation |
| F050 | Freshness consistency | implemented | IMPLEMENTED | UNIT_TESTED | RETAIN | scored | high | specified by a standard or vendor documentation |
| F051 | Extractable main text | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | medium | plausible mechanism |
| F052 | Main-content signal | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | medium | plausible mechanism |
| F053 | Navigation-to-content ratio | implemented | IMPLEMENTED | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F054 | Hidden-content proportion | implemented | IMPLEMENTED | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | unscored (informational) | high | plausible mechanism |
| F055 | Semantic HTML usage | implemented | IMPLEMENTED | PIPELINE_VALIDATED | INVESTIGATE | scored | low | plausible mechanism |
| F056 | Table structure | implemented | IMPLEMENTED | UNIT_TESTED | RETAIN | scored | low | plausible mechanism |
| F057 | List structure | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F058 | Descriptive anchor text | partial (heuristic) | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | low | plausible mechanism |
| F059 | Heading and landmark accessibility | partial | PARTIAL | PIPELINE_VALIDATED | REVISE | scored; results that only repeat another feature's count once | medium | plausible mechanism |
| F060 | Text-to-markup ratio | implemented | IMPLEMENTED | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | unscored (informational) | high | plausible mechanism |
| F061 | JSON-LD validity | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | high | specified by a standard or vendor documentation |
| F062 | Structured-data type coverage | partial | PARTIAL | PIPELINE_VALIDATED | REVISE | scored | medium | plausible mechanism |
| F063 | Structured-data property completeness | partial | PARTIAL | UNIT_TESTED | REVISE | scored | medium | plausible mechanism |
| F064 | Entity identifier availability | partial | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | low | hypothesis about ranking |
| F065 | Entity relationship coverage | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F066 | Organization consistency | implemented | IMPLEMENTED | UNIT_TESTED | INVESTIGATE | scored | low | plausible mechanism |
| F067 | Product entity completeness | partial | PARTIAL | UNIT_TESTED | REVISE | scored | low | plausible mechanism |
| F068 | Offer and pricing completeness | partial | PARTIAL | UNIT_TESTED | REVISE | scored | low | plausible mechanism |
| F069 | Article metadata completeness | partial | PARTIAL | UNIT_TESTED | REVISE | scored; results that only repeat another feature's count once | low | plausible mechanism |
| F070 | Visible-content consistency | partial (heuristic) | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | medium | specified by a standard or vendor documentation |
| F071 | Internal-link density | implemented | IMPLEMENTED | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | high | plausible mechanism |
| F072 | Incoming-link count | implemented | IMPLEMENTED | PIPELINE_VALIDATED | REVISE | scored, but excluded from the aggregate when it cannot discriminate (see scoring policy) | high | plausible mechanism |
| F073 | Outgoing-link count | implemented | IMPLEMENTED | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | high | plausible mechanism |
| F074 | Hub-page identification | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F075 | Topic-cluster connectivity | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F076 | Important-page accessibility | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F077 | Contextual-link coverage | partial | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F078 | Anchor-target relevance | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | low | hypothesis about ranking |
| F079 | Broken-link concentration | partial | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F080 | Cross-page topic redundancy | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | low | hypothesis about ranking |
| F081 | Image alternative text | implemented | IMPLEMENTED | PIPELINE_VALIDATED | RETAIN | scored | high | specified by a standard or vendor documentation |
| F082 | Image filename descriptiveness | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | high | hypothesis about ranking |
| F083 | Image dimension availability | implemented | IMPLEMENTED | UNIT_TESTED | RETAIN | scored | low | plausible mechanism |
| F084 | Image loading behavior | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F085 | Image context alignment | unavailable | UNAVAILABLE | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F086 | Video transcript availability | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F087 | Video caption availability | implemented | IMPLEMENTED | UNIT_TESTED | RETAIN | scored | medium | plausible mechanism |
| F088 | Video metadata completeness | partial | PARTIAL | UNIT_TESTED | REVISE | scored | low | plausible mechanism |
| F089 | Audio transcript availability | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F090 | Multimodal content dependence | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F091 | Chunkable section structure | partial (heuristic) | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | low | hypothesis about ranking |
| F092 | Section self-containment | partial (heuristic) | PARTIAL | UNIT_TESTED | INVESTIGATE | scored | low | hypothesis about ranking |
| F093 | Definition availability | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F094 | Procedural-step clarity | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F095 | Comparison structure | partial (heuristic) | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F096 | Fact extractability | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F097 | Answer-context proximity | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F098 | Entity disambiguation | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F099 | Source-boundary clarity | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F100 | Retrieval-query coverage | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F101 | Response latency | partial | PARTIAL | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | high | plausible mechanism |
| F102 | Response-size efficiency | partial | PARTIAL | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | unscored (informational) | medium | plausible mechanism |
| F103 | Compression support | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F104 | Cache-header configuration | implemented | IMPLEMENTED | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | specified by a standard or vendor documentation |
| F105 | ETag and Last-Modified availability | implemented | IMPLEMENTED | UNIT_TESTED | INFORMATIONAL_ONLY | unscored (informational) | medium | specified by a standard or vendor documentation |
| F106 | Mobile viewport support | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F107 | Core Web Vitals | unavailable | UNAVAILABLE | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F108 | JavaScript content dependence | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F109 | Resource failure signals | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F110 | Security transport configuration | implemented | IMPLEMENTED | PIPELINE_VALIDATED | INFORMATIONAL_ONLY | unscored (informational) | high | specified by a standard or vendor documentation |
| F111 | AI-answer mention rate | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F112 | Citation frequency | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F113 | Unique cited-page coverage | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F114 | Citation prominence | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F115 | Answer factual coverage | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F116 | Citation-to-claim support | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F117 | Citation absorption | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F118 | Cross-run consistency | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F119 | Query coverage | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |
| F120 | Before/after visibility change | planned | PLANNED | NOT_TESTED | INVESTIGATE | not measured (excluded from scores) | low | none |

### Threshold register

| Setting | Default | Basis | Note |
|---|---|---|---|
| `min_crawlable_links` | `1` | configurable heuristic | A page needs at least one followable link; terminal pages are legitimate. |
| `max_click_depth` | `3` | arbitrary default | 3 clicks is a folk rule; no retrieved source supports it for AI retrieval. |
| `audit_agent_tokens` | `["GeoptimiserBot"]` | specification | The audit's own robots.txt token; matching follows RFC 9309 (S04). |
| `ai_crawler_tokens` | `["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", ...` | vendor documentation (secondary summary) | Token names must be checked against each vendor's current documentation (OpenAI: S07); others not researched. |
| `max_redirect_hops` | `1` | configurable heuristic | One hop allowed; http->https plus host normalisation is already two. |
| `max_query_parameters` | `3` | arbitrary default | 3 parameters; no source. |
| `duplicate_min_text_chars` | `100` | configurable heuristic | Below 100 characters exact duplicates are mostly shared boilerplate. |
| `max_url_segment_chars` | `60` | arbitrary default | 60 characters per segment; no source. |
| `generic_titles` | `["home", "homepage", "index", "untitled", "welcome", "new...` | configurable heuristic | Eight English placeholder words; recall unknown. |
| `description_term_coverage_min` | `0.5` | arbitrary default | 50% of description terms must appear in the text; no source. |
| `h1_overlap_min` | `0.5` | arbitrary default | 50% of H1 terms must appear in the title or opening text; no source. |
| `generic_headings` | `["heading", "untitled", "section", "more", "click here", ...` | configurable heuristic | Seven English placeholder headings; recall unknown. |
| `min_text_chars_for_citation_check` | `300` | arbitrary default | 300 characters before external links are expected; no source. |
| `article_types` | `["Article", "NewsArticle", "BlogPosting", "TechArticle", ...` | specification | schema.org Article subtypes; completeness of the list not verified. |
| `min_extractable_chars` | `100` | arbitrary default | 100 characters of text; no source. |
| `min_text_to_markup_ratio` | `0.02` | arbitrary default | 2% text share; no source. |
| `entity_properties` | `{"Article": ["headline", "author", "datePublished", "date...` | configurable heuristic | Project policy per type, not schema.org or Google requirements (S06). For VideoObject, Google requires only name, thumbnailUrl and uploadDate (S13, checked 2026-11-01); description is project policy. |
| `max_boilerplate_ratio` | `0.5` | arbitrary default | 50% navigation/boilerplate text; no source. |
| `max_hidden_ratio` | `0.3` | arbitrary default | 30% hidden text; no source. |
| `min_semantic_kinds` | `2` | arbitrary default | 2 kinds of semantic element; no source. |
| `pseudo_list_min_lines` | `3` | configurable heuristic | 3 list-like lines. |
| `generic_anchor_texts` | `["click here", "here", "link", "this link", "more", "read...` | configurable heuristic | Eleven English phrases; WCAG allows context-supplied purpose (S11 is a different criterion; 2.4.4 not retrieved). |
| `min_contextual_links` | `1` | configurable heuristic | One body link. |
| `how_to_prefixes` | `["how to", "how do", "guide to", "steps to"]` | configurable heuristic | English title prefixes. |
| `comparison_terms` | `[" vs ", " vs. ", "versus", "compar"]` | configurable heuristic | English title terms. |
| `min_incoming_links` | `1` | configurable heuristic | 1 is the definition of 'not an orphan'; >=2 is a different, weaker-linking question. |
| `topic_overlap_max` | `0.8` | arbitrary default | 0.8 Jaccard of title/H1 terms; no source. |
| `max_section_chars` | `3000` | arbitrary default | 3,000 characters per section; no source and not tied to the retrieval chunk size. |
| `dangling_openers` | `["this", "that", "these", "those", "it", "they", "such", ...` | configurable heuristic | English reference words. |
| `latency_budget_seconds` | `2.0` | arbitrary default | 2 s from the audit host; no source. |
| `max_html_bytes` | `1000000` | arbitrary default | 1 MB; Googlebot's documented limit is 15 MB uncompressed (S02), so this is stricter and arbitrary. |
| `interstitial_markers` | `["just a moment", "attention required", "access denied", ...` | configurable heuristic | Phrases used by common bot-challenge pages; English; recall unknown. |
| `interstitial_max_text_chars` | `1500` | arbitrary default | A challenge page is short; 1,500 characters. |
| `measured_confidence` | `1.0` | configurable heuristic | Ordinal marker for deterministic findings, not a probability. |
| `heuristic_confidence` | `0.5` | configurable heuristic | Ordinal marker for heuristic findings and owner-policy notices, not a probability. |
| `max_evidence_per_finding` | `20` | configurable heuristic | Presentation cap. |
| `min_reportable_coverage` | `0.5` | arbitrary default | Half of the applicable scored features must be measured before a score is shown; a project policy, not a statistical threshold. |

### Per-feature assessment

#### F001 HTTP success status

* **Disposition:** Retain (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/crawl.py:23` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page request ended in a 2xx response.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** A non-2xx page cannot be read or retrieved.
* **Configuration / threshold:** base severity high — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** A 403, or a 5xx without Retry-After, during the audit may be bot blocking of the audit agent, not a property of the page (429 and 503 with Retry-After are not measured since v2).
* **Possible false negatives:** A 200 response that is really an error ('soft 404') or a challenge page passes (challenge pages are caught by F021-class checks as not measured).
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_findings_scoring.py; tests/features/test_scoring_policy.py (+1 more); fixtures: a1_trunc_before_title, b1_empty_blocked_nonhtml, b1_interstitial, b1_js_shell, b2_base_href, b2_link_forms, clean_static, e1_http_status, empty_failed_crawl, yt_like_truncated_large_head
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Done in v2 for 429 and 503 with Retry-After; consider the same for 401/403 when the response marks bot blocking. Add soft-404 detection only with evidence.

#### F002 Crawlable page links

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/crawl.py:59` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page exposes at least one followable (http/https anchor, not rel=nofollow) link.
* **Claimed outcome (crawlability or indexability; plausible mechanism, not measured):** A page with no followable links is a dead end for link-following crawlers.
* **Configuration / threshold:** min_crawlable_links=1; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Terminal pages (thank-you, receipts, single-page documents) legitimately have no links; links only inside <noscript> are not counted as anchors here.
* **Possible false negatives:** A page full of navigation links but no content links passes (see F077).
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (anchors, links): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F071: F002 is a binary dead-end test; F071 normalises internal links by text length.; F073: F002 asks whether any followable link exists; F073 reports the internal/external counts.
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_checks_structure.py; tests/features/test_integration.py; fixtures: clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Candidate for unscoring: a link-less page is not a defect in itself. Decide with labelled data.

#### F003 Robots.txt accessibility

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/crawl.py:84` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether robots.txt can be retrieved (or is cleanly absent) for each origin.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** An unreachable robots.txt is treated by crawlers as a complete disallow.
* **Configuration / threshold:** base severity high — basis: specification
* **Scoring:** scored
* **Possible false positives:** A transient 5xx during the audit; Google's own behaviour (cached copy, then no restrictions) differs from RFC 9309.
* **Possible false negatives:** A robots.txt that returns 200 but with wrong content type or HTML error body is parsed as rules.
* **Missing evidence:** reads only data that is always present for a fetched page
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/diagnosis/test_diagnose.py; tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; fixtures: clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Distinguish a persistent from a transient 5xx (re-fetch) before reporting failure.

#### F004 Robots policy compliance

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/crawl.py:134` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether robots.txt permits the audited page for the configured crawler tokens.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** A disallow rule keeps the named crawlers from fetching the page; whether that is wanted is the owner's decision.
* **Configuration / threshold:** audit_agent_tokens=["GeoptimiserBot"]; ai_crawler_tokens=["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "PerplexityBot", "Google-Exten...; base severity low — basis: n/a (no numeric threshold)
* **Scoring:** unscored notice (warning, confirm intent)
* **Possible false positives:** Blocking AI-training crawlers while allowing AI-search crawlers is a deliberate and common policy; the token list is configuration, not a registry.
* **Possible false negatives:** Rules reached only through a redirected robots.txt, or crawlers missing from the token list, are not evaluated; ChatGPT-User fetches may not follow robots.txt at all.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_findings_scoring.py; tests/features/test_integration.py (+1 more); fixtures: b4_ai_crawler_blocked
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Keep as a notice. Split tokens by purpose (training vs search vs user-triggered) per vendor documentation; verify the token list against primary vendor pages.

#### F005 Meta robots directives

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/crawl.py:177` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page's meta robots tag forbids indexing.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** A noindex directive asks search engines not to index the page.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** unscored notice (warning, confirm intent)
* **Possible false positives:** Deliberate noindex (utility pages, staging, internal search) is correct behaviour.
* **Possible false negatives:** Directives set only by JavaScript, or by X-Robots-Tag (see F006), are not seen here; a meta tag after a truncated head is unknown.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence: 'head_violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F006: F005 reads the HTML tag; F006 reads the HTTP header.; F030: F005 covers indexing; F030 covers snippet restrictions.
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_evidence_policy.py; tests/features/test_findings_scoring.py (+2 more); fixtures: a1_trunc_after_title, a1_trunc_before_title, b4_noindex_entry_page, b4_noindex_intentional, clean_static, combined_realistic_mix
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Keep as a notice (confirm intent). Consider surfacing 'noindex on a page linked from the main navigation' as a stronger signal.

#### F006 X-Robots-Tag directives

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/crawl.py:195` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the X-Robots-Tag response header forbids indexing.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** A noindex X-Robots-Tag header asks search engines not to index the response.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** unscored notice (warning, confirm intent)
* **Possible false positives:** Deliberate noindex on non-content responses; agent-scoped directives are treated as applying to everyone.
* **Possible false negatives:** Headers that differ by user agent or that the allow-listed header capture drops.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** F005 reads the HTML tag; F006 the header; both can fire for one cause.
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_findings_scoring.py; fixtures: a1_trunc_before_title, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Keep as a notice; honour agent scoping when reporting.

#### F007 Sitemap availability

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/crawl.py:216` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the site declares a sitemap in robots.txt.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** A sitemap declared in robots.txt aids discovery.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** unscored (informational)
* **Possible false positives:** None: only a positive declaration is reported.
* **Possible false negatives:** Sitemaps at default locations that robots.txt does not declare are not probed, so absence is never concluded.
* **Missing evidence:** reads only data that is always present for a fetched page
* **Overlap:** F008: F007 asks whether a sitemap is declared; F008 compares its URL list with crawled pages.
* **Discriminates / actionable:** unknown / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_integration.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Availability of the file is not verified because the crawler does not fetch sitemaps yet.
* **Follow-up:** Needs sitemap fetching (F008) to be useful; keep unscored.

#### F008 Sitemap URL coverage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Share of sitemap URLs that were crawled, and of crawled pages listed in the sitemap.
* **Claimed outcome (crawlability or indexability; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py; tests/features/test_registry.py
* **Gaps:** n/a
* **Follow-up:** Fetch and parse sitemaps (bounded); needed to make F009/F072 meaningful.

#### F009 Orphan-page risk

* **Disposition:** Revise (confidence in this assessment: high)
* **Status / location:** partial · `src/geoptimiser/features/checks/crawl.py:245` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether a crawled page has no incoming internal links from other crawled pages.
* **Claimed outcome (crawlability or indexability; plausible mechanism, not measured):** A page with no incoming internal links cannot be found by following links.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored, but excluded from the aggregate when it cannot discriminate (see scoring policy)
* **Possible false positives:** Pages linked only from uncrawled pages (outside the crawl budget) look orphaned in theory; with link-based discovery the check cannot fail at all.
* **Possible false negatives:** True orphans are never fetched by a link-following crawl, so they are never seen; this is the main limitation.
* **Missing evidence:** link-graph check: uses ctx.uncertain_link_sources
* **Overlap:** Same test as F072 at its default minimum; see overlap decisions.
* **Discriminates / actionable:** no / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_evidence_policy.py; tests/features/test_integration.py (+2 more); fixtures: b2_link_forms, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown); partial: A breadth-first crawl discovers every page through a link from another crawled page, so this check cannot fail on a crawl-discovered page; it does not contribute to the aggregate score until URLs are also discovered by another source (sitemap, F008).
* **Follow-up:** Excluded from the aggregate. Becomes meaningful only with a second discovery source (sitemap, F008) or a supplied URL list.

#### F010 Crawl depth

* **Disposition:** Revise (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/crawl.py:263` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Minimum number of link clicks from the entry page to the page.
* **Claimed outcome (crawlability or indexability; plausible mechanism, not measured):** Pages many clicks from the entry page are reached later by link-following crawlers.
* **Configuration / threshold:** max_click_depth=3; base severity low — basis: configurable heuristic
* **Scoring:** scored, but excluded from the aggregate when it cannot discriminate (see scoring policy)
* **Possible false positives:** Large sites with legitimate deep archives; limit 3 is a policy default.
* **Possible false negatives:** Pages beyond the crawl depth are never crawled, so excessive depth is invisible at the default crawl depth of 2.
* **Missing evidence:** link-graph check: uses ctx.uncertain_link_sources
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_integration.py; tests/features/test_scoring_policy.py; fixtures: b2_link_forms, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Excluded from the aggregate while crawl depth <= limit. Run a deeper crawl to make it informative; justify the limit with data.

#### F011 Canonical tag presence

* **Disposition:** Revise (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/urls.py:35` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page declares a canonical URL.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** A rel=canonical link tells search engines which URL to prefer among duplicates.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Google describes specifying a canonical as generally not critical, so a missing canonical on a unique page is not a defect.
* **Possible false negatives:** A canonical injected by JavaScript is not seen.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence: 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_engine.py; tests/features/test_findings_scoring.py; fixtures: a1_complete_missing_metadata, a1_trunc_after_title, a1_trunc_before_title, b1_interstitial, clean_static, yt_like_js_heavy, yt_like_truncated_large_head
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Severity 'medium' is higher than the documentation supports; consider 'low' and applicability to pages with duplicate variants.

#### F012 Canonical target validity

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/urls.py:65` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the canonical URL is well-formed and, when crawled, a healthy page.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** A canonical pointing at a missing, redirected or noindex URL is ignored or harmful.
* **Configuration / threshold:** base severity high — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** A target that returns 403/429/5xx to the audit agent (reported as not measured, not a failure).
* **Possible false negatives:** Targets outside the crawl are not examined (not measured); soft-404 targets pass.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence: 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_measurement_states.py; fixtures: a2_canonical_states, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown); partial: Reachability is judged only for canonical targets that were crawled; an uncrawled or unreachable target is reported as not measured, never as a pass.
* **Follow-up:** Crawl canonical targets that were not reached (a bounded extra fetch) to raise coverage.

#### F013 Canonical consistency

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/urls.py:136` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the canonical points to itself or to a self-canonical target (no chains or loops).
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** A canonical chain or loop prevents a clear preferred URL.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Cross-domain canonicals (intentional syndication) are judged only if the target was crawled.
* **Possible false negatives:** Chains through uncrawled pages are not seen.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence: 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** Related to F012 (target health) and F011 (presence); independent questions.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; fixtures: clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Same extra-fetch follow-up as F012.

#### F014 Duplicate page content

* **Disposition:** Revise (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/urls.py:174` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether another crawled page has identical normalised text.
* **Claimed outcome (content extraction or machine readability; specified by a standard or vendor documentation):** Identical text on several URLs splits signals and wastes crawl effort.
* **Configuration / threshold:** duplicate_min_text_chars=100; base severity medium — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Exact-text equality includes shared boilerplate on very short pages; threshold 100 characters is a heuristic.
* **Possible false negatives:** Near-duplicates (a changed date, reordered blocks) are not detected.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (text): 'complete' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F022: F014 compares body text; F022 compares titles.; F080: F014 finds identical text; F080 flags heavily overlapping topics.
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_evidence_policy.py; fixtures: a1_trunc_after_title, clean_static, combined_realistic_mix
* **Gaps:** no labelled real-world benchmark (precision/recall unknown); partial: Exact duplicates only; near-duplicates are not detected.
* **Follow-up:** Add near-duplicate detection (shingling) with a labelled evaluation; keep exact matching as the precise tier.

#### F015 Redirect-chain length

* **Disposition:** Revise (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/urls.py:196` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Number of redirect hops between the requested URL and the final URL.
* **Claimed outcome (crawlability or indexability; plausible mechanism, not measured):** Long redirect chains waste crawl effort and risk abandonment.
* **Configuration / threshold:** max_redirect_hops=1; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** A redirect from http to https plus www normalisation is two hops and common.
* **Possible false negatives:** Chains longer than the crawler's own redirect limit stop the fetch and are not measured.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_measurement_states.py; fixtures: b3_redirect_applicability, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Revisit the 1-hop default; applies only to redirected pages (changed).

#### F016 Redirect-loop detection

* **Disposition:** Retain (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/urls.py:213` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the redirect chain revisits a URL.
* **Claimed outcome (technical correctness; specified by a standard or vendor documentation):** A redirect loop makes a URL unreachable.
* **Configuration / threshold:** base severity high — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** None identified beyond measurement limits.
* **Possible false negatives:** Loops longer than the crawler's redirect limit are recorded as a fetch error, not as a loop.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_engine.py; tests/features/test_measurement_states.py; fixtures: b3_redirect_applicability, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Report the crawler's too-many-redirects outcome through this feature.

#### F017 Broken internal links

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/urls.py:263` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Internal links on the page whose crawled target returned an HTTP error.
* **Claimed outcome (technical correctness; specified by a standard or vendor documentation):** Links to pages that return errors waste the reader's and crawler's time.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** A target that blocks the audit agent (403) is counted as broken.
* **Possible false negatives:** Only targets inside the crawl are examined; links to uncrawled pages are unknown.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; link-graph check: judges the links of one page it read
* **Overlap:** F079: F017 is per page; F079 describes how broken links concentrate across the site.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_integration.py; tests/features/test_measurement_states.py (+1 more)
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Only crawled targets are checked; links beyond the crawl limits are unknown, not good.
* **Follow-up:** Separate 4xx from access errors (as done for F012); optionally HEAD-check unchecked internal targets.

#### F018 URL parameter proliferation

* **Disposition:** Revise (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/urls.py:288` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Number of query parameters in the page URL and in the internal URLs the page links to.
* **Claimed outcome (crawlability or indexability; plausible mechanism, not measured):** Many query parameters create duplicate URL variants.
* **Configuration / threshold:** max_query_parameters=3; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Tracking parameters on links that redirect or canonicalise correctly are harmless.
* **Possible false negatives:** Parameters in URLs not linked from crawled pages are unseen.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_measurement_states.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Revised to inspect linked URLs (the crawler does not fetch query URLs). Needs evidence for the limit of 3.

#### F019 URL semantic readability

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** implemented (heuristic) · `src/geoptimiser/features/checks/urls.py:345` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether path segments are human-readable words.
* **Claimed outcome (other: search-result presentation; plausible mechanism, not measured):** Readable URLs help people and models interpret a page.
* **Configuration / threshold:** max_url_segment_chars=60; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Product IDs and dated slugs are flagged though harmless.
* **Possible false negatives:** Semantic quality of readable-looking slugs is not judged.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Keep unscored.

#### F020 HTTPS consistency

* **Disposition:** Retain (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/urls.py:361` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page is served over HTTPS and internal links keep HTTPS.
* **Claimed outcome (technical correctness; specified by a standard or vendor documentation):** A page served over HTTP, or linking internally over HTTP, weakens transport security.
* **Configuration / threshold:** base severity high — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** http links that redirect to https immediately are flagged.
* **Possible false negatives:** Mixed-content subresources (images, scripts) are not examined.
* **Missing evidence:** truncated or limit-cut evidence (links): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F110: F020 checks URL schemes; F110 checks transport security headers.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; fixtures: clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Add subresource checks when rendering is available.

#### F021 Title presence

* **Disposition:** Retain (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/metadata.py:56` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page has a non-empty <title>.
* **Claimed outcome (other: search-result presentation; specified by a standard or vendor documentation):** The title element labels a page in search results and in citations.
* **Configuration / threshold:** base severity high — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** A title set only by JavaScript is absent from the initial HTML (reported with a client-rendered note); a cut head is not measured.
* **Possible false negatives:** A present but meaningless title passes (see F023).
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (title): 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/agent/test_tools_prompt.py; tests/app/test_compare.py; tests/diagnosis/test_diagnose.py; tests/e2e/browser_e2e.py (+12 more); fixtures: a1_complete_missing_metadata, a1_trunc_after_title, a1_trunc_before_title, a1_trunc_jsonld, b1_empty_blocked_nonhtml, b1_js_shell, b4_noindex_intentional, clean_static, combined_realistic_mix, empty_failed_crawl, yt_like_js_heavy, yt_like_truncated_large_head
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Verify against rendered titles on a labelled JS-heavy set.

#### F022 Title uniqueness

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/metadata.py:62` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page's title is shared by no other crawled page.
* **Claimed outcome (other: search-result presentation; plausible mechanism, not measured):** Distinct titles let results and citations tell pages apart.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Legitimate repeated titles on paginated or templated series.
* **Possible false negatives:** Near-identical titles differing by one word.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (title): 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F014: F022 compares titles; F014 compares body text.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_findings_scoring.py; tests/features/test_integration.py (+1 more); fixtures: a1_trunc_before_title, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Treat pagination-style repeats separately.

#### F023 Title descriptiveness

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/metadata.py:68` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the title is more than a generic placeholder.
* **Claimed outcome (other: search-result presentation; plausible mechanism, not measured):** A placeholder title tells neither users nor models what the page is.
* **Configuration / threshold:** generic_titles=["home", "homepage", "index", "untitled", "welcome", "new page", "page", "default"]; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Brand-only home page titles are common and intentional.
* **Possible false negatives:** Only eight generic words are listed; vague non-listed titles pass.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (title): 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F021: F021 asks whether a title exists; F023 asks whether it is a placeholder.
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_evidence_policy.py; tests/features/test_scoring_policy.py (+1 more); fixtures: a1_trunc_before_title, a3_independent_failures, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown); partial: Heuristic; says nothing about quality beyond placeholder detection. The list is configuration.
* **Follow-up:** Heuristic with unknown precision; evaluate on labelled titles.

#### F024 Meta-description presence

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/metadata.py:85` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page has a non-empty meta description.
* **Claimed outcome (other: search-result presentation; specified by a standard or vendor documentation):** A meta description can supply the snippet for a result.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Google may write its own snippet; many sites rely on page text, so absence is not necessarily harmful.
* **Possible false negatives:** A present but useless description passes.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence: 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/app/test_compare.py; tests/diagnosis/test_diagnose.py; tests/features/test_catalog.py; tests/features/test_checks_content.py (+4 more); fixtures: a1_complete_missing_metadata, a1_trunc_after_title, a1_trunc_before_title, a3_independent_failures, b1_interstitial, clean_static, yt_like_js_heavy, yt_like_truncated_large_head
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Keep low severity.

#### F025 Meta-description uniqueness

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/metadata.py:91` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the description is shared by no other page.
* **Claimed outcome (other: search-result presentation; plausible mechanism, not measured):** Distinct descriptions let results tell pages apart.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Templated sites with intentionally shared descriptions.
* **Possible false negatives:** Near-duplicates.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence: 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_scoring_policy.py; fixtures: a1_trunc_before_title, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** none beyond the general benchmark

#### F026 Description-content alignment

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/metadata.py:99` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the description's terms appear in the page text.
* **Claimed outcome (other: search-result presentation; plausible mechanism, not measured):** A description should reflect the page's content.
* **Configuration / threshold:** description_term_coverage_min=0.5; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Marketing descriptions that use different words for the same ideas fail the 50% term overlap.
* **Possible false negatives:** Overlap of words does not prove accuracy.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (text): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_scoring_policy.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Lexical overlap only; English stopwords; synonyms count as mismatches. Threshold is a policy default to calibrate.
* **Follow-up:** Candidate informational-only; measure precision on labelled description/page pairs.

#### F027 Language declaration

* **Disposition:** Retain (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/metadata.py:126` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether <html lang> holds a well-formed language tag.
* **Claimed outcome (technical correctness; specified by a standard or vendor documentation):** A well-formed language tag helps tools pick pronunciation, hyphenation and models.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Regional subtags with unusual but valid forms are accepted by a permissive pattern.
* **Possible false negatives:** A wrong but well-formed language passes.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence: 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_scoring_policy.py; fixtures: a1_complete_missing_metadata, a1_trunc_after_title, a1_trunc_before_title, b1_interstitial, clean_static, yt_like_truncated_large_head
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Validate against the IANA subtag registry if exactness is wanted.

#### F028 Character encoding declaration

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/metadata.py:152` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the character encoding is declared by the HTTP header or a <meta charset>.
* **Claimed outcome (technical correctness; specified by a standard or vendor documentation):** A declared character encoding avoids mis-decoding.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** unscored (informational)
* **Possible false positives:** A charset declared only after the first 1024 bytes is invalid but accepted.
* **Possible false negatives:** A wrong declared charset passes.
* **Missing evidence:** truncated or limit-cut evidence: 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_scoring_policy.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Unscored in the catalog; keep.

#### F029 Viewport configuration

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:39` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether <meta name=viewport> exists with width=device-width and without disabled zoom.
* **Claimed outcome (other: accessibility; specified by a standard or vendor documentation):** A device-width viewport with zoom allowed supports small screens and zooming.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** maximum-scale is a documented accessibility hazard only when <=1; other values pass.
* **Possible false negatives:** Layout that breaks despite a correct tag.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence: 'head' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F106: F029 checks the declared tag; F106 checks actual mobile rendering support.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; tests/features/test_integration.py; tests/features/test_scoring_policy.py (+1 more); fixtures: a1_trunc_after_title, clean_static, yt_like_js_heavy
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Overlaps in spirit with the planned F106 (rendered mobile usability).

#### F030 Search snippet restrictions

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** partial · `src/geoptimiser/features/checks/metadata.py:184` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether snippet-limiting directives are set.
* **Claimed outcome (crawlability or indexability; specified by a standard or vendor documentation):** nosnippet/max-snippet:0 limit what search systems may quote.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** unscored notice (warning, confirm intent)
* **Possible false positives:** Deliberate publisher choice.
* **Possible false negatives:** data-nosnippet attributes on elements are not seen.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence: 'head_violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F005: F005 covers indexing; F030 covers quoting.
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_findings_scoring.py; tests/features/test_scoring_policy.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: data-nosnippet attributes on elements are not extracted. Restriction may be intentional.
* **Follow-up:** Keep as a notice; extract data-nosnippet.

#### F031 Main-topic clarity

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/content.py:22` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the single H1 agrees with the title or opening text.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** The H1, title and opening text should agree on the topic.
* **Configuration / threshold:** h1_overlap_min=0.5; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Short or stylised headings with few content terms; non-English text (English stopwords).
* **Possible false negatives:** Agreeing but wrong topic.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (title, headings, text): 'complete' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F035: F035 checks heading structure; F031 checks agreement between title, H1 and opening.
* **Discriminates / actionable:** unknown / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Lexical, English-only heuristic; a deliberately different H1 is flagged.
* **Follow-up:** Measure on labelled pages; the term-overlap threshold 0.5 has no basis.

#### F032 Search-intent coverage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** How well the page covers the intents users bring to its topic.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/diagnosis/test_diagnose.py; tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs the labelled query benchmark (Stage 04) and a judged evaluation.

#### F033 Direct-answer availability

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether a concise answer appears near the top for the page's main question.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** F040: F033 asks if the main question is answered up front; F040 counts question/answer structures.
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs a labelled direct-answer set; evaluate against a simple heuristic baseline first.

#### F034 Key-information prominence

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether key facts appear early in the page.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs a labelled key-fact set.

#### F035 Heading hierarchy

* **Disposition:** Revise (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/content.py:49` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether headings form a clean outline.
* **Claimed outcome (other: accessibility; plausible mechanism, not measured):** A clean heading outline helps people and parsers navigate.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** HTML allows several H1 elements, so 'multiple H1' is a convention, not an error; templated sites use them.
* **Possible false negatives:** A well-ordered but meaningless outline passes.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (headings): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F059: F035 checks the outline; F059 covers landmarks and accessibility semantics.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_engine.py; tests/features/test_evidence_policy.py (+1 more); fixtures: clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Separate hard errors (empty headings, skipped levels) from the single-H1 convention; verify against WCAG 1.3.1 / 2.4.6 text.

#### F036 Section descriptiveness

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/content.py:78` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether headings name their section's content.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** Placeholder headings give no information to readers or models.
* **Configuration / threshold:** generic_headings=["heading", "untitled", "section", "more", "click here", "read more", "learn more"]; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Short generic headings such as 'More' used as UI labels.
* **Possible false negatives:** Vague headings not on the seven-word list.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (headings): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Placeholder detection only; descriptiveness is not judged semantically.
* **Follow-up:** Benchmark on a labelled real-page corpus (none exists yet) before treating precision/recall as known.

#### F037 Topical completeness

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether the page covers the subtopics expected for its subject.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs reference outlines; subjective.

#### F038 Entity coverage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether the entities relevant to the topic are named.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs entity recognition and an expected-entity source.

#### F039 Terminology consistency

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether the same concept is named consistently.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs term clustering and labels.

#### F040 Question-and-answer coverage

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/content.py:100` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the page structures questions with answers.
* **Claimed outcome (AI-answer retrieval or citation; hypothesis about ranking, AI retrieval or citation; unvalidated):** Question headings or FAQ markup mirror how questions are asked.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** unscored (informational)
* **Possible false positives:** Most pages are not Q&A pages; absence is normal.
* **Possible false negatives:** FAQ-like content without question marks.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (headings, structured_data): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F033: F040 counts Q&A structures; F033 judges whether the main question is answered.
* **Discriminates / actionable:** conditional / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_findings_scoring.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Does not check that an answer follows the question or that markup matches visible content.
* **Follow-up:** Already unscored; no evidence it affects retrieval.

#### F041 Source citation presence

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/trust.py:19` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the page links to external sources.
* **Claimed outcome (AI-answer retrieval or citation; plausible mechanism, not measured):** Links to external sources let readers verify claims.
* **Configuration / threshold:** min_text_chars_for_citation_check=300; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Product and brand pages rarely cite sources.
* **Possible false negatives:** A link to any external domain counts.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (text, links): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F042: F041 asks if sources are linked; F042 asks whether the linked targets are valid.
* **Discriminates / actionable:** conditional / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Navigation, social and advertising links count too.
* **Follow-up:** Already unscored.

#### F042 Citation-target validity

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether linked sources are reachable and relevant.
* **Claimed outcome (technical correctness; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs bounded external-link fetching with consent and rate limits.

#### F043 Claim-evidence proximity

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether claims sit near their supporting evidence.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs claim detection; high risk of unreliable output.

#### F044 Quantitative evidence

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether the page states measurable facts.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** F096: F044 counts numeric evidence; F096 measures how extractable facts are as passages.
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Overlaps F096; naive digit counting is wrong.

#### F045 Methodology transparency

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether the page explains how data or conclusions were produced.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Keyword matching is brittle; needs semantic detection and labels.

#### F046 Author attribution

* **Disposition:** Retain (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/trust.py:46` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether article-type structured data names an author.
* **Claimed outcome (structured-data or entity interpretation; specified by a standard or vendor documentation):** Article markup that names an author supports attribution.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Applies only where Article markup exists; sites without it are not applicable.
* **Possible false negatives:** Author names that are placeholders pass.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F069: F046 checks one signal; F069 checks overall Article property completeness.
* **Discriminates / actionable:** conditional / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; tests/features/test_engine.py; tests/features/test_integration.py (+1 more)
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Visible bylines and meta author tags are not read.
* **Follow-up:** Verify against Google's article structured-data guidance (not retrieved).

#### F047 Publisher identity

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/trust.py:64` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether structured data identifies the publisher or organisation.
* **Claimed outcome (structured-data or entity interpretation; plausible mechanism, not measured):** A named publisher in structured data supports source identification.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Any Organization with a name passes, even if it is not the page's publisher.
* **Possible false negatives:** Publisher stated in visible text only.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Visible footer or about-page identity is not assessed.
* **Follow-up:** Tighten to publisher of the page's own Article.

#### F048 Publication-date availability

* **Disposition:** Retain (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/trust.py:94` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether article-type structured data has datePublished.
* **Claimed outcome (structured-data or entity interpretation; specified by a standard or vendor documentation):** datePublished supports freshness interpretation.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Applies only to Article markup.
* **Possible false negatives:** Dates present but wrong.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; tests/validation/test_overlap.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Visible dates and meta tags are not read.
* **Follow-up:** Verify against Google article documentation.

#### F049 Modification-date availability

* **Disposition:** Retain (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/trust.py:109` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether a modification date exists.
* **Claimed outcome (structured-data or entity interpretation; specified by a standard or vendor documentation):** dateModified or Last-Modified supports freshness interpretation.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Last-Modified headers on dynamic pages equal the request time.
* **Possible false negatives:** Wrong dates.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; tests/validation/test_overlap.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Last-Modified from servers is often just the generation time.
* **Follow-up:** Do not accept a dynamic Last-Modified as a modification date.

#### F050 Freshness consistency

* **Disposition:** Retain (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/trust.py:135` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the page's dates are valid and ordered.
* **Claimed outcome (technical correctness; specified by a standard or vendor documentation):** Impossible date combinations signal broken markup.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** None identified beyond measurement limits.
* **Possible false negatives:** Only Article markup with both dates is examined.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** none beyond the general benchmark

#### F051 Extractable main text

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/content.py:127` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page yields readable text without scripts.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** Text absent from the initial HTML is invisible to crawlers that do not run scripts.
* **Configuration / threshold:** min_extractable_chars=100; base severity high — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Client-rendered applications show their content to browsers; result is flagged as client-rendered when signals exist. The 100-character floor is arbitrary.
* **Possible false negatives:** Boilerplate-only pages with 100+ characters pass.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (text): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_engine.py; tests/features/test_evidence_policy.py; fixtures: a1_trunc_after_title, a1_trunc_before_title, b1_interstitial, b1_js_shell, clean_static, combined_realistic_mix, yt_like_js_heavy, yt_like_truncated_large_head
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Add a rendered-DOM comparison (F108) to separate 'not in the HTML' from 'not on the page'; this is the main capability gap.

#### F052 Main-content signal

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:75` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether a <main>/<article> landmark (or role) identifies the main content.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** A <main>/<article> landmark lets extractors find the content.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Good extractors do not need landmarks; sites using role=main or div soup fail.
* **Possible false negatives:** A landmark wrapping the wrong content passes.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (landmarks): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F059 fails for the same missing <main>.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; tests/features/test_scoring_policy.py; tests/validation/test_overlap.py; fixtures: a1_trunc_after_title, a3_independent_failures, a3_single_root_cause, clean_static, yt_like_js_heavy
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Shares one cause with F059; counted once.

#### F053 Navigation-to-content ratio

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:91` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Share of visible text inside navigation, banner, footer or complementary regions.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** A high share of navigation text buries the content.
* **Configuration / threshold:** max_boilerplate_ratio=0.5; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Index/listing pages are mostly links by design.
* **Possible false negatives:** Needs landmarks; otherwise not measured.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (text, landmarks): 'complete' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** none beyond the general benchmark

#### F054 Hidden-content proportion

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:121` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Share of page text that is hidden from view (hidden attribute or display:none/visibility:hidden).
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** Much hidden text may be uncitable or collapsed content.
* **Configuration / threshold:** max_hidden_ratio=0.3; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Accordions, tabs and menus are legitimately hidden; whether scripts reveal text is not evaluated.
* **Possible false negatives:** Hiding by CSS class is not seen.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (text): 'complete' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; fixtures: b1_hydration_hidden
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Already unscored; needs rendering to be meaningful.

#### F055 Semantic HTML usage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:141` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** How many kinds of semantic structural elements the page uses.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** Semantic structural elements describe the page's regions.
* **Configuration / threshold:** min_semantic_kinds=2; base severity low — basis: arbitrary default
* **Scoring:** scored
* **Possible false positives:** Pages that use ARIA roles instead of tags fail.
* **Possible false negatives:** Presence of tags says nothing about correct use.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (landmarks): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; fixtures: clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** The 'at least 2 kinds' threshold has no basis; evaluate.

#### F056 Table structure

* **Disposition:** Retain (confidence in this assessment: low)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:158` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether data tables have header cells.
* **Claimed outcome (other: accessibility; plausible mechanism, not measured):** Data tables with header cells are interpretable by assistive technology and parsers.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Layout tables are skipped when marked presentational; unmarked layout tables fail.
* **Possible false negatives:** Header cells that are not real headers.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (tables): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Verify against WCAG 1.3.1 techniques.

#### F057 List structure

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:189` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether list-like content uses real list markup.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** Real list markup is more machine-readable than list-like text lines.
* **Configuration / threshold:** pseudo_list_min_lines=3; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Poetry, code and addresses look like lists.
* **Possible false negatives:** Lists in ways other than leading bullet characters.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (lists, text): 'complete' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: English-style markers only; markers in the source text of real list items are not present in extracted text.
* **Follow-up:** none beyond the general benchmark

#### F058 Descriptive anchor text

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:211` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether link text describes its target.
* **Claimed outcome (other: accessibility; plausible mechanism, not measured):** Link text such as 'click here' conveys no purpose out of context.
* **Configuration / threshold:** generic_anchor_texts=["click here", "here", "link", "this link", "more", "read more", "learn more", "details...; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** WCAG allows context-supplied link purpose; icon links with aria-label may read as empty here.
* **Possible false negatives:** Vague links outside the 11-word list.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (anchors): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F078: F058 judges anchor wording alone; F078 judges relevance to the target page.
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; tests/features/test_integration.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Placeholder detection only; descriptiveness is not judged semantically. English list.
* **Follow-up:** Benchmark on a labelled real-page corpus (none exists yet) before treating precision/recall as known.

#### F059 Heading and landmark accessibility

* **Disposition:** Revise (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/structure.py:230` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Landmark semantics that assistive technology and parsers rely on.
* **Claimed outcome (other: accessibility; plausible mechanism, not measured):** Landmarks that are present, single and labelled assist navigation.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored; results that only repeat another feature's count once
* **Possible false positives:** An <article>-only page is flagged for lacking <main>.
* **Possible false negatives:** Correct count but wrong content.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (landmarks): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F052 fails for the same missing <main>; counted once.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; tests/features/test_scoring_policy.py; fixtures: a3_independent_failures, a3_single_root_cause
* **Gaps:** no labelled real-world benchmark (precision/recall unknown); partial: Heading outline is covered by F035; ARIA beyond landmark labels is not assessed.
* **Follow-up:** A missing <main> is already counted by F052; keep F059 for multiple/unlabelled landmarks and consider dropping the missing-main sub-test.

#### F060 Text-to-markup ratio

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/content.py:148` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Share of the HTML response that is visible text.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** A very low text share may indicate a script-built page.
* **Configuration / threshold:** min_text_to_markup_ratio=0.02; base severity low — basis: arbitrary default
* **Scoring:** unscored (informational)
* **Possible false positives:** Pages with large inline data or SVG.
* **Possible false negatives:** Texty pages with huge inline scripts after the cut.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (text): 'complete' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F102: F060 relates text to markup; F102 judges total transfer size.; F108: F060 is a ratio on the raw HTML; F108 compares raw and rendered content.
* **Discriminates / actionable:** conditional / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_evidence_policy.py; tests/validation/test_overlap.py; fixtures: a1_complete_missing_metadata, a1_trunc_after_title, a1_trunc_before_title
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** The 2% threshold is arbitrary; keep unscored.

#### F061 JSON-LD validity

* **Disposition:** Retain (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structured.py:59` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether JSON-LD blocks parse.
* **Claimed outcome (structured-data or entity interpretation; specified by a standard or vendor documentation):** JSON-LD that does not parse is ignored.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Blocks skipped by extraction limits and cut by truncation are now not measured, not failures.
* **Possible false negatives:** Syntactically valid but semantically wrong markup passes.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; distinguishes truncated, skipped and invalid JSON-LD blocks by cause
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; tests/features/test_engine.py; tests/features/test_evidence_policy.py (+1 more); fixtures: a1_complete_missing_metadata, a1_trunc_after_title, a1_trunc_before_title, a1_trunc_jsonld, a5_jsonld_size_limit, a5_jsonld_states, clean_static, yt_like_truncated_large_head
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Add schema.org-aware validation only with an evaluated validator.

#### F062 Structured-data type coverage

* **Disposition:** Revise (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/structured.py:141` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page declares any schema.org type.
* **Claimed outcome (structured-data or entity interpretation; plausible mechanism, not measured):** Declared types give models and search systems an entity vocabulary.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Structured data is optional; most pages do not need it.
* **Possible false negatives:** Types irrelevant to the page pass.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; fixtures: a1_trunc_jsonld, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown); partial: Does not check that the types suit the page.
* **Follow-up:** Make applicability depend on page type; do not fail every page without markup.

#### F063 Structured-data property completeness

* **Disposition:** Revise (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/structured.py:159` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether declared entities have the configured recommended properties.
* **Claimed outcome (structured-data or entity interpretation; plausible mechanism, not measured):** Entities should carry the properties a consumer expects.
* **Configuration / threshold:** entity_properties={...}; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** The property lists are project policy, not schema.org or Google requirements.
* **Possible false negatives:** Property present but empty strings are not counted.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** F067: F063 is generic; F067 is Product-specific.; F069: F063 is generic; F069 is Article-specific.
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Property lists are project policy, not Google or schema.org requirements.
* **Follow-up:** Align property lists with vendor required/recommended sets and word as 'configured properties'.

#### F064 Entity identifier availability

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/structured.py:166` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether organisations and people carry @id or sameAs.
* **Claimed outcome (structured-data or entity interpretation; hypothesis about ranking, AI retrieval or citation; unvalidated):** @id/sameAs identifiers help entity disambiguation.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Many valid Organization blocks have neither.
* **Possible false negatives:** Identifiers pointing nowhere pass.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Does not verify that identifiers resolve or are correct.
* **Follow-up:** No evidence tying identifiers to better interpretation.

#### F065 Entity relationship coverage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether entities reference each other.
* **Claimed outcome (structured-data or entity interpretation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs a JSON-LD graph resolver.

#### F066 Organization consistency

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structured.py:187` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether Organization names agree across pages.
* **Claimed outcome (structured-data or entity interpretation; plausible mechanism, not measured):** One organisation should be described consistently across pages.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Legal vs trading names.
* **Possible false negatives:** Only pages in the crawl are compared.
* **Missing evidence:** site-level: compares only entities that were read
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; tests/features/test_engine.py; tests/features/test_integration.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** none beyond the general benchmark

#### F067 Product entity completeness

* **Disposition:** Revise (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/structured.py:223` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether Product entities have the configured properties.
* **Claimed outcome (structured-data or entity interpretation; plausible mechanism, not measured):** Product markup needs the fields product features require.
* **Configuration / threshold:** entity_properties={...}; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Project property list differs from Google's.
* **Possible false negatives:** Product data outside JSON-LD (microdata, RDFa) is not read.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; tests/features/test_findings_scoring.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Property list is project policy.
* **Follow-up:** Align with Google Product requirements.

#### F068 Offer and pricing completeness

* **Disposition:** Revise (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/structured.py:230` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether Offers state price, currency and availability.
* **Claimed outcome (structured-data or entity interpretation; plausible mechanism, not measured):** Offers need price, currency and availability.
* **Configuration / threshold:** entity_properties={...}; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Project property list differs from Google's.
* **Possible false negatives:** Offers expressed outside JSON-LD are not read; a wrong price still passes.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Does not verify prices against visible content.
* **Follow-up:** Align with Google Offer requirements.

#### F069 Article metadata completeness

* **Disposition:** Revise (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/structured.py:241` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether Article entities have the configured properties.
* **Claimed outcome (structured-data or entity interpretation; plausible mechanism, not measured):** Article markup needs headline, author and dates.
* **Configuration / threshold:** entity_properties={...}; article_types=["Article", "NewsArticle", "BlogPosting", "TechArticle", "ScholarlyArticle"]; base severity low — basis: configurable heuristic
* **Scoring:** scored; results that only repeat another feature's count once
* **Possible false positives:** Headline is not required by Google for all uses (unverified).
* **Possible false negatives:** Article data outside JSON-LD is not read.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (structured_data): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; tests/features/test_integration.py; tests/validation/test_overlap.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Property list is project policy.
* **Follow-up:** Verify required vs recommended.

#### F070 Visible-content consistency

* **Disposition:** Investigate (confidence in this assessment: medium)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structured.py:250` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether structured-data names appear in visible content.
* **Claimed outcome (structured-data or entity interpretation; specified by a standard or vendor documentation):** Markup must match what users see.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Case/format differences (title case vs upper case) after normalisation.
* **Possible false negatives:** Semantic mismatch with matching words.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (text, headings, title, structured_data): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structured.py; tests/validation/test_matrix.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Containment test only; paraphrases fail; other properties are not compared.
* **Follow-up:** Substring match is crude; evaluate on labelled pairs.

#### F071 Internal-link density

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/linking.py:20` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Internal links per 1,000 characters of text.
* **Claimed outcome (other: search-result presentation; plausible mechanism, not measured):** Link density describes the page's linking context.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** unscored (informational)
* **Possible false positives:** Not a judgement; always passes.
* **Possible false negatives:** n/a
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (text, links): 'complete' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** no / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_linking_delivery.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Descriptive statistic only.

#### F072 Incoming-link count

* **Disposition:** Revise (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/linking.py:36` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Number of other crawled pages that link to the page.
* **Claimed outcome (crawlability or indexability; plausible mechanism, not measured):** Pages with few incoming links are weakly connected.
* **Configuration / threshold:** min_incoming_links=1; base severity low — basis: configurable heuristic
* **Scoring:** scored, but excluded from the aggregate when it cannot discriminate (see scoring policy)
* **Possible false positives:** At the default minimum of 1 this repeats F009 and cannot fail on a link-discovered page.
* **Possible false negatives:** True orphans are never crawled.
* **Missing evidence:** link-graph check: uses ctx.uncertain_link_sources
* **Overlap:** Exact duplicate of F009 at min_incoming_links=1.
* **Discriminates / actionable:** no / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/features/test_evidence_policy.py; tests/features/test_scoring_policy.py (+1 more); fixtures: b2_base_href, b2_link_forms, clean_static
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Excluded from the aggregate at the default; raise the minimum to make it a 'weakly linked' check.

#### F073 Outgoing-link count

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/linking.py:58` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Internal and external outgoing link counts.
* **Claimed outcome (other: search-result presentation; plausible mechanism, not measured):** Outgoing link counts describe crawl paths.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** unscored (informational)
* **Possible false positives:** Not a judgement; always passes.
* **Possible false negatives:** n/a
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (links): 'complete' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** no / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_linking_delivery.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Descriptive statistic only.

#### F074 Hub-page identification

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Which pages act as hubs.
* **Claimed outcome (other: search-result presentation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs a defensible hub definition.

#### F075 Topic-cluster connectivity

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether related pages interlink.
* **Claimed outcome (other: search-result presentation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs topic clustering; effect on authority is unproven.

#### F076 Important-page accessibility

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether user-nominated key pages are reachable.
* **Claimed outcome (crawlability or indexability; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs an important-pages field in the audit request.

#### F077 Contextual-link coverage

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/structure.py:255` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Share of followable internal and external links that sit in body content rather than navigation.
* **Claimed outcome (content extraction or machine readability; plausible mechanism, not measured):** Links inside body content carry context that menu links lack.
* **Configuration / threshold:** min_contextual_links=1; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Utility pages are all navigation.
* **Possible false negatives:** A single content link satisfies the check.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (anchors): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; tests/features/test_integration.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: A page without landmarks classifies every link as content.
* **Follow-up:** none beyond the general benchmark

#### F078 Anchor-target relevance

* **Disposition:** Informational only (confidence in this assessment: low)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:278` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the words in an internal link relate to the page they point at.
* **Claimed outcome (AI-answer retrieval or citation; hypothesis about ranking, AI retrieval or citation; unvalidated):** Anchor text should relate to its target.
* **Configuration / threshold:** base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Brand and call-to-action anchors share no words with titles.
* **Possible false negatives:** Shared words do not prove relevance.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (anchors): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Lexical, English-only; synonyms and branded anchors are flagged.
* **Follow-up:** none beyond the general benchmark

#### F079 Broken-link concentration

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/linking.py:74` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** How broken internal links cluster across pages.
* **Claimed outcome (technical correctness; plausible mechanism, not measured):** Broken links concentrated on one page point to a single fix.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** unscored (informational)
* **Possible false positives:** Same as F017.
* **Possible false negatives:** Same as F017.
* **Missing evidence:** site-level: aggregates only links that were read
* **Overlap:** F017: F017 is per page; F079 aggregates and reports concentration.
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_crawl_urls.py; tests/validation/test_overlap.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Only crawled targets are considered.
* **Follow-up:** Redundant with F017 at feature level; keep as a site summary.

#### F080 Cross-page topic redundancy

* **Disposition:** Informational only (confidence in this assessment: low)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/linking.py:110` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether pages' titles and H1s overlap heavily.
* **Claimed outcome (AI-answer retrieval or citation; hypothesis about ranking, AI retrieval or citation; unvalidated):** Pages with overlapping topics may compete.
* **Configuration / threshold:** topic_overlap_max=0.8; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Series pages share title words.
* **Possible false negatives:** Overlap in meaning with different words.
* **Missing evidence:** site-level: compares only titles that were read
* **Overlap:** F014: F014 is identical body text; F080 is overlapping subject labels.; F022: F022 is identical titles; F080 is similar title/H1 term sets.
* **Discriminates / actionable:** unknown / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_linking_delivery.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Title/H1 only; English stopwords.
* **Follow-up:** none beyond the general benchmark

#### F081 Image alternative text

* **Disposition:** Retain (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:323` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether informative images have alt text.
* **Claimed outcome (other: accessibility; specified by a standard or vendor documentation):** Images need a text alternative (or must be marked decorative).
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Images marked decorative by CSS or by context.
* **Possible false negatives:** Alt text that is present but meaningless.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (images): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; tests/features/test_integration.py; fixtures: a3_independent_failures
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Meaningfulness of alt text is out of scope.

#### F082 Image filename descriptiveness

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:350` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether image filenames look like words rather than camera or hash names.
* **Claimed outcome (content extraction or machine readability; hypothesis about ranking, AI retrieval or citation; unvalidated):** Descriptive file names add context for images.
* **Configuration / threshold:** base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Hashed CDN names are normal.
* **Possible false negatives:** Misleading but readable file names pass.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (images): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py; tests/features/test_integration.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: English-centric pattern list; descriptiveness is not judged.
* **Follow-up:** none beyond the general benchmark

#### F083 Image dimension availability

* **Disposition:** Retain (confidence in this assessment: low)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:376` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether images declare width and height.
* **Claimed outcome (other: delivery performance; plausible mechanism, not measured):** Declared width/height reduce layout shift.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** CSS-sized images.
* **Possible false negatives:** Wrong but present dimensions pass; images added by scripts are not seen.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (images): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Verify the layout-shift mechanism against web.dev documentation.

#### F084 Image loading behavior

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:398` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the first content image is lazy-loaded.
* **Claimed outcome (other: delivery performance; plausible mechanism, not measured):** A lazy-loaded first image can delay rendering.
* **Configuration / threshold:** base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** The first image may be below the fold.
* **Possible false negatives:** Lazy loading applied by script is not seen.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (images): 'first' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Document order is a proxy for position on screen.
* **Follow-up:** none beyond the general benchmark

#### F085 Image context alignment

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** unavailable · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether images relate to the surrounding text.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs a vision model and a validated evaluation; not on the roadmap.

#### F086 Video transcript availability

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:442` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether pages with video offer a transcript.
* **Claimed outcome (other: accessibility; plausible mechanism, not measured):** Video needs a transcript.
* **Configuration / threshold:** base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Transcripts linked elsewhere; the word 'transcript' anywhere passes.
* **Possible false negatives:** Transcripts under other names.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (media, text): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: English keyword only; a transcript that is not labelled as such is missed.
* **Follow-up:** none beyond the general benchmark

#### F087 Video caption availability

* **Disposition:** Retain (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/structure.py:452` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether <video> elements have caption or subtitle tracks.
* **Claimed outcome (other: accessibility; plausible mechanism, not measured):** <video> elements should carry a captions track.
* **Configuration / threshold:** base severity low — basis: n/a (no numeric threshold)
* **Scoring:** scored
* **Possible false positives:** Captions burnt into the video.
* **Possible false negatives:** Embedded players are not measured.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (media): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Verify against WCAG 1.2.2.

#### F088 Video metadata completeness

* **Disposition:** Revise (confidence in this assessment: low)
* **Status / location:** partial · `src/geoptimiser/features/checks/structure.py:481` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether VideoObject structured data accompanies video and has the configured properties.
* **Claimed outcome (structured-data or entity interpretation; plausible mechanism, not measured):** Video pages need VideoObject markup with core properties.
* **Configuration / threshold:** entity_properties={...}; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Project property list may differ from Google's.
* **Possible false negatives:** Video data outside JSON-LD is not read; embedded players beyond the known hosts are not detected.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (media, structured_data): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** yes / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Property list is project policy. Does not match each VideoObject to a specific video.
* **Follow-up:** Align with Google's VideoObject properties after reading the primary page.

#### F089 Audio transcript availability

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:447` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether pages with audio offer a transcript.
* **Claimed outcome (other: accessibility; plausible mechanism, not measured):** Audio needs a transcript.
* **Configuration / threshold:** base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** As F086.
* **Possible false negatives:** Audio embedded through players the extractor does not recognise is not seen.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (media, text): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: English keyword only; audio in embedded players is not detected.
* **Follow-up:** none beyond the general benchmark

#### F090 Multimodal content dependence

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Share of meaning that exists only in non-text media.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs media extraction and judgement.

#### F091 Chunkable section structure

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/content.py:224` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the text divides into heading-delimited sections of manageable size.
* **Claimed outcome (AI-answer retrieval or citation; hypothesis about ranking, AI retrieval or citation; unvalidated):** Sections over ~3,000 characters are hard to retrieve as a single passage.
* **Configuration / threshold:** max_section_chars=3000; base severity low — basis: arbitrary default
* **Scoring:** scored
* **Possible false positives:** Long legal or reference sections.
* **Possible false negatives:** Short sections of poor quality.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (headings, text): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py; tests/features/test_findings_scoring.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Section size limit is a configurable policy default, not a retrieval requirement; headings must appear as their own text lines.
* **Follow-up:** The 3,000-character limit has no basis; relate it to the retrieval chunk size actually used.

#### F092 Section self-containment

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/content.py:253` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether sections open without unresolved references.
* **Claimed outcome (AI-answer retrieval or citation; hypothesis about ranking, AI retrieval or citation; unvalidated):** Sections that open with 'this/it' depend on earlier text.
* **Configuration / threshold:** dangling_openers=["this", "that", "these", "those", "it", "they", "such", "he", "she", "as mentioned"]; base severity low — basis: configurable heuristic
* **Scoring:** scored
* **Possible false positives:** Normal prose; English only.
* **Possible false negatives:** Dependence expressed otherwise.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; truncated or limit-cut evidence (headings, text): 'violation' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / no
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_content.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: English-only lexical heuristic; many valid openings begin with 'This'.
* **Follow-up:** Benchmark on a labelled real-page corpus (none exists yet) before treating precision/recall as known.

#### F093 Definition availability

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether key terms are defined.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs concept identification and labels.

#### F094 Procedural-step clarity

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:515` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether how-to pages present their steps as an ordered sequence.
* **Claimed outcome (AI-answer retrieval or citation; plausible mechanism, not measured):** How-to pages should mark steps in order.
* **Configuration / threshold:** how_to_prefixes=["how to", "how do", "guide to", "steps to"]; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** The how-to detection is by title prefix only.
* **Possible false negatives:** How-to pages with other titles are not applicable.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (lists, text, headings): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Page type comes from title prefixes (English); steps in other markup are missed.
* **Follow-up:** none beyond the general benchmark

#### F095 Comparison structure

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial (heuristic) · `src/geoptimiser/features/checks/structure.py:541` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether comparison pages use a table with several columns.
* **Claimed outcome (AI-answer retrieval or citation; plausible mechanism, not measured):** Comparison pages should present a data table.
* **Configuration / threshold:** comparison_terms=[" vs ", " vs. ", "versus", "compar"]; base severity low — basis: configurable heuristic
* **Scoring:** unscored (informational)
* **Possible false positives:** Detected from title words such as ' vs '.
* **Possible false negatives:** Comparison pages whose title lacks the listed terms are not detected.
* **Missing evidence:** no extracted document -> not_measured with the fetch/extraction reason; older extraction level -> not_measured; truncated or limit-cut evidence (tables, headings): 'presence' policy (what stays conclusive is stated in features/evidence.py); interstitial/challenge page -> not_measured
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_structure.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Page type comes from title terms (English); parallel structure in lists is not recognised.
* **Follow-up:** none beyond the general benchmark

#### F096 Fact extractability

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether facts are stated in self-contained sentences.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs fact segmentation and evaluation; overlaps F044.

#### F097 Answer-context proximity

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether answers sit next to the context they need.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs answer identification.

#### F098 Entity disambiguation

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether ambiguous entity names are disambiguated.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs entity recognition and a knowledge source.

#### F099 Source-boundary clarity

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether passages carry their source, author and date.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs the chunk model (Stage 07) and labels.

#### F100 Retrieval-query coverage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** How well the content is retrieved for benchmark queries.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs the query benchmark and retrieval evaluation; measures the retriever as much as the page.

#### F101 Response latency

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** partial · `src/geoptimiser/features/checks/delivery.py:18` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Wall-clock time of the page fetch.
* **Claimed outcome (other: delivery performance; plausible mechanism, not measured):** Slow responses cost crawl budget and user time.
* **Configuration / threshold:** latency_budget_seconds=2.0; base severity low — basis: arbitrary default
* **Scoring:** unscored (informational)
* **Possible false positives:** Measured from the audit host, including its network and pacing, not from users.
* **Possible false negatives:** A fast first fetch of a slow page.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_linking_delivery.py; tests/features/test_findings_scoring.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown); partial: Not time-to-first-byte; includes DNS, redirects and streaming.
* **Follow-up:** Keep unscored; budget 2 s is arbitrary.

#### F102 Response-size efficiency

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** partial · `src/geoptimiser/features/checks/delivery.py:36` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Size of the stored HTML response.
* **Claimed outcome (other: delivery performance; plausible mechanism, not measured):** Very large HTML is slow and may be cut by crawlers.
* **Configuration / threshold:** max_html_bytes=1000000; base severity low — basis: arbitrary default
* **Scoring:** unscored (informational)
* **Possible false positives:** A response truncated by the audit's own budget rather than its size.
* **Possible false negatives:** Large pages below the 1 MB budget but heavy in scripts.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** conditional / partly
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_linking_delivery.py; fixtures: a1_trunc_after_title, a1_trunc_before_title, yt_like_js_heavy, yt_like_truncated_large_head
* **Gaps:** no labelled real-world benchmark (precision/recall unknown); partial: HTML only; subresources are not measured.
* **Follow-up:** Googlebot's documented limit is 15 MB uncompressed; the 1 MB default is arbitrary.

#### F103 Compression support

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether the server compresses responses.
* **Claimed outcome (other: delivery performance; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Low value for GEO and the crawler requests identity encoding by design; decide whether to keep.

#### F104 Cache-header configuration

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/delivery.py:55` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether the response sets Cache-Control.
* **Claimed outcome (other: delivery performance; specified by a standard or vendor documentation):** Cache-Control lets clients and intermediaries reuse responses.
* **Configuration / threshold:** base severity informational — basis: n/a (no numeric threshold)
* **Scoring:** unscored (informational)
* **Possible false positives:** Intentional no-store.
* **Possible false negatives:** Cache policy set by a service worker or CDN rules the audit does not see.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_linking_delivery.py; tests/features/test_findings_scoring.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** none beyond the general benchmark

#### F105 ETag and Last-Modified availability

* **Disposition:** Informational only (confidence in this assessment: medium)
* **Status / location:** implemented · `src/geoptimiser/features/checks/delivery.py:75` · V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages
* **Purpose:** Whether validators exist.
* **Claimed outcome (other: delivery performance; specified by a standard or vendor documentation):** ETag/Last-Modified enable conditional requests.
* **Configuration / threshold:** base severity informational — basis: n/a (no numeric threshold)
* **Scoring:** unscored (informational)
* **Possible false positives:** A header present on a response that never revalidates still passes.
* **Possible false negatives:** Validators present but ignored by the server (no 304 behaviour) pass.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/features/test_catalog.py; tests/features/test_checks_linking_delivery.py
* **Gaps:** not exercised by a whole-pipeline fixture; no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** none beyond the general benchmark

#### F106 Mobile viewport support

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether the page renders usably on mobile.
* **Claimed outcome (other: accessibility; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs rendering; only a distinct feature if it measures rendered layout (F029 already checks the viewport tag).

#### F107 Core Web Vitals

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** unavailable · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Real-user LCP, INP and CLS.
* **Claimed outcome (other: delivery performance; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs real-user data or lab instrumentation; not on the roadmap.

#### F108 JavaScript content dependence

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** How much content exists only after JavaScript runs.
* **Claimed outcome (content extraction or machine readability; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Highest-value missing capability for this audit: compare initial HTML with rendered DOM in a safe headless environment.

#### F109 Resource failure signals

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Failures loading page subresources.
* **Claimed outcome (technical correctness; none: not implemented):** Not implemented: the claim is the catalog definition only.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Needs subresource fetching or rendering.

#### F110 Security transport configuration

* **Disposition:** Informational only (confidence in this assessment: high)
* **Status / location:** implemented · `src/geoptimiser/features/checks/delivery.py:113` · V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages
* **Purpose:** Whether the page was served over HTTPS with an HTTP Strict-Transport-Security policy.
* **Claimed outcome (technical correctness; specified by a standard or vendor documentation):** HTTPS with a valid HSTS policy keeps clients on HTTPS (RFC 6797); no link to AI-search visibility is established.
* **Configuration / threshold:** base severity informational — basis: specification (RFC 6797 6.1.1: max-age required; max-age=0 clears the policy)
* **Scoring:** unscored (informational)
* **Possible false positives:** Sites that deliberately omit HSTS (for example during an HTTPS migration) fail although nothing is broken.
* **Possible false negatives:** A valid header with a very small max-age passes; preload status, certificate quality and other security headers are not examined.
* **Missing evidence:** no HTTP response -> not_measured where headers/body are needed
* **Overlap:** none identified
* **Discriminates / actionable:** yes / yes
* **Tests:** tests/app/test_api.py; tests/features/test_catalog.py; tests/features/test_checks_linking_delivery.py; tests/features/test_registry.py (+1 more); fixtures: k1_transport_security
* **Gaps:** no labelled real-world benchmark (precision/recall unknown)
* **Follow-up:** Validate on real responses; decide whether other security headers (CSP, X-Content-Type-Options) belong in this feature or a new one.

#### F111 AI-answer mention rate

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Share of benchmark answers mentioning the brand.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/app/test_api.py; tests/features/test_catalog.py; tests/features/test_engine.py; tests/features/test_integration.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F112 Citation frequency

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** How often the site is cited in answers.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F113 Unique cited-page coverage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Distinct pages of the site that are cited.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F114 Citation prominence

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Position and prominence of citations in answers.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F115 Answer factual coverage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Share of key facts present in answers.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F116 Citation-to-claim support

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Whether cited pages support the claims they are attached to.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F117 Citation absorption

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** How much of an answer is attributable to cited sources.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F118 Cross-run consistency

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Stability of outcomes across repeated runs.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F119 Query coverage

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Share of benchmark queries answered with any visibility.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

#### F120 Before/after visibility change

* **Disposition:** Investigate (confidence in this assessment: low)
* **Status / location:** planned · `(no check)` · V0: not implemented; no check exists, always not_measured
* **Purpose:** Change in visibility metrics after an approved change.
* **Claimed outcome (AI-answer retrieval or citation; none: not implemented):** Observed outcome: requires live provider data (Stage 05/06) and a controlled comparison (docs/validation/AI_OUTCOME_PROTOCOL.md); none exists.
* **Configuration / threshold:** base severity medium — basis: n/a (no numeric threshold)
* **Scoring:** not measured (excluded from scores)
* **Possible false positives:** n/a (not implemented)
* **Possible false negatives:** n/a (not implemented)
* **Missing evidence:** Not implemented: always not_measured (never a pass or a failure).
* **Overlap:** none identified
* **Discriminates / actionable:** unknown / unknown
* **Tests:** tests/features/test_catalog.py
* **Gaps:** n/a
* **Follow-up:** Blocked on live provider adapters and data; design is in the outcome protocol.

<!-- END GENERATED -->
