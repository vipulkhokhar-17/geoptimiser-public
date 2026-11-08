# Validation methodology

Goal: establish which of the 120 catalog features are measured correctly, which are
worth measuring, and what the evidence for each claim is, without letting a passing
test suite stand in for any of that.

## 1. Six separate questions

A feature is assessed on six dimensions that are never collapsed into one "validated"
flag (they are columns in `feature_validation_matrix.csv`):

| Dimension | Question | How it is established | Status today |
|---|---|---|---|
| Implementation verified | Does a check exist and do its tests pass? | catalog + registry + unit tests | 82 features have a check; 38 do not |
| Measurement correctness evaluated | Does it report the right state on constructed cases with pre-declared answers? | `tests/validation/fixtures` | 35 features exercised (V2) |
| Diagnostic accuracy benchmarked | Precision and recall against labelled real pages | `benchmarks/corpus` | **none** - no real-world corpus exists |
| Technical rationale supported | Do standards or vendor documentation support the property? | `sources.py`, `judgments.py` | partly; sources are search summaries |
| AI-visibility outcome demonstrated | Does changing it change visibility in an answer engine? | `AI_OUTCOME_PROTOCOL.md` | **none** |
| Business outcome demonstrated | Does it move a business metric? | - | **none** |

Validation status codes: **V0** not implemented, **V1** implemented and unit-tested,
**V2** also evaluated against pre-declared fixtures, **V3** (not reached) also
benchmarked on a labelled real corpus.

## 2. Evidence rules

* Fixtures, tests and passing CI are evidence of *implementation* and *measurement
  correctness on constructed inputs* only. They are never evidence that a feature
  improves visibility in ChatGPT, Google AI Overviews, Perplexity or any other engine.
* Expectations are written before the code is changed to meet them. The baseline run
  (`results/baseline_main_220e9c7.json`) records the original code against the same
  fixtures. Where a pre-declared expectation turned out to rest on a wrong premise it
  was corrected and the correction is in `VALIDATION_WORK_LOG.md`; none was edited to
  match output.
* Sources are cited only with title, publisher, URL, access date and the specific claim,
  and with how far they were verified. In this session the web could be searched but
  pages could not be fetched, so every claim is "search-result summary only". Anything
  not researched is marked unverified; no source is invented.
* Dispositions are judgments with a stated confidence, not facts:
  Retain / Revise / Informational only / Remove / Investigate. Where precision is
  unknown, a heuristic is "Investigate" (candidate informational-only, per the project's
  80% precision rule), not silently kept or deleted. No feature is recommended for
  removal on current evidence.

## 3. Checks of the checks

1. **Completeness** - `tests/validation/test_matrix.py` asserts the matrix has exactly
   the catalog's features, each once, with no empty cell, a closed disposition set,
   implementation status equal to the catalog's, no demonstrated AI/business outcome,
   all thresholds classified, and that the CSV and the register in
   `GEOPTIMISER_FEATURE_AUDIT.md` equal a fresh generation. The declared catalog state
   (version, count, categories) is a constant with an update path in the test.
2. **Evidence-policy coverage** - every content check must declare what an incomplete
   document can prove; a new check without a policy fails a test.
3. **Overlap analysis** - `validation/overlap.py` compares the data each check reads
   (static signatures) and the catalog's declared neighbours. Every candidate pair must
   carry a recorded decision (exact duplicate, shared cause, related, ...); pairs
   judged to double count need a scoring rule. Static signatures are shallow (they miss
   F009/F072 and over-match shared helpers), so semantic overlaps are added by hand.
4. **Parity** - the crawler and the extractor share link rules; a parametrised test
   feeds both the same markup (anchors, `<noscript>`, `<template>`, `<base href>`,
   malformed HTML, odd hrefs) and requires identical link sets.
5. **Scoring scenarios** - seven required cases (all pass, independent failures,
   overlapping failures, insufficient evidence, partial applicability, incomplete
   crawl, empty crawl) with hand-computed expectations in
   `tests/features/test_scoring_policy.py` and the fixtures.
6. **Discrimination** - a check that cannot fail under the audit's configuration is
   identified from facts (crawl depth, discovery method, threshold) and excluded from
   the aggregate with the reason shown; it is not deleted.

## 4. Synthetic benchmark

27 deterministic fixtures, each a mock site served from memory to the real crawler,
extractor, checks, scoring, diagnosis and recommendations (no network). A fixture
declares per feature and page the expected status, required explanation fragments,
limitations, severity; the findings that must or must not exist and their wording; score
reportability and contribution. Isolating fixtures cover one defect each; the combined
fixture mixes truncation, a client-rendered shell, a noindex page and duplicates.
Metrics: for expectations with a pass/fail answer, TP/FP/TN/FN (positive class = a
reported failure), precision = TP/(TP+FP), recall = TP/(TP+FN), Wilson 95% intervals,
and abstentions counted separately. A zero denominator is reported as undefined (null),
never as 0 or 1. These numbers measure correctness on constructed cases; they say
nothing about accuracy on real websites.

## 5. Real-world benchmark

No real-page snapshots existed in the repository, and live collection was not possible
(the session's network policy denied outbound connections to websites). The framework
(`validation/corpus.py`, `benchmarks/corpus/`) is complete and a labelled **initial
corpus** is checked in, but it consists of 14 pages already in this repository,
labelled by an independent parser (lxml) with independently written rules. It is a
cross-check of the extractor against a second implementation on objective properties.
It is not real-world, not human-labelled, and has no second reviewer. The target design
for a real corpus: 200-300 snapshots across static, server-rendered, documentation,
e-commerce and JavaScript-heavy sites; URL/source, date, page type, response
conditions, labels with labeller identity, model predictions, uncertainty; critical
labels by two independent reviewers with disagreements recorded and resolved in the
open; no credentials or personal data. Acceptance targets (project-defined, not
universal): presence and validity checks >= 95% precision and recall; heuristic checks
below 80% precision become informational-only candidates. These targets have **not**
been assessed.

## 6. Known weaknesses of this methodology

* Fixture authors and implementers are the same people; the independent parser shares
  conventions for F027/F029 (same language regex, same viewport rules).
* The static overlap analysis cannot see semantic overlap; the hand-written decisions
  can be incomplete.
* Source claims come from search summaries; primary pages must be read before the
  rationale column is trusted.
* Interstitial and client-rendered detection are heuristic phrase/signal lists with
  unknown recall.
