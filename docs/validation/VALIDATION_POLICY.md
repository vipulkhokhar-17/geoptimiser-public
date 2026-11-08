# Measurement, scoring and reporting policy

This is the normative description of how the audit treats incomplete evidence, owner
choices, overlapping checks and scores. The synthetic fixtures in
`tests/validation/fixtures` take their expectations from this document, not from what
the implementation printed. Decisions and reasons: ADR-0027 to ADR-0030 in
`docs/DECISIONS.md`.

## 1. Result states

Every feature result has exactly one status (`FeatureStatus`, unchanged schema):

| Status | Meaning | Counts in a score |
|---|---|---|
| `pass` | The property was measured and meets the rule. | yes, 1.0 |
| `fail` | The property was measured on sufficient evidence and violates the rule. | yes, 0.0 |
| `warning` | A condition was observed that may be the site owner's deliberate choice (noindex, a blocked crawler, snippet limits). Only the *intent-dependent* features emit it, and they are unscored. | no (their features are unscored); would count 0.5 |
| `not_applicable` | The feature does not apply to this page (no images, not redirected, entry page, ...). | no (leaves numerator and denominator) |
| `not_measured` | The evidence needed is missing, incomplete, blocked or unavailable. **Not a pass and not a failure.** The explanation says which. | no; lowers coverage |
| `error` | The check itself raised an exception. | no; lowers coverage |

Unknown evidence never becomes a pass. A fetch or extraction problem is reported as
`not_measured` with its cause (HTTP status, empty body, unsupported content type,
timeout, interstitial page); it is never presented as a website defect.

## 2. Incomplete evidence

A document can be incomplete for reasons that belong to the measurement:

* the stored response was **truncated** at the crawl size limit (`source_truncated`);
* an **extraction limit** stopped one field early (`truncated_fields`);
* a JSON-LD block was skipped by a size/nesting limit or never closed because of a cut;
* the response was a **bot-challenge or consent interstitial**;
* the link list of another page, which a graph check relies on, is incomplete.

`features/evidence.py` declares, per check, what an incomplete document can still prove
(`POLICIES`). Anything it cannot prove becomes `not_measured`:

| Policy | Conclusive when the document is incomplete | Example |
|---|---|---|
| `head` | everything once `</head>` (or the body) was read; before that only a `pass` | F021 title, F024 description, F011 canonical |
| `head_violation` | a seen restriction; "none" only after the head was read | F005 meta robots, F030 snippet limits |
| `presence` | a `pass` (it was seen); a miss may lie beyond the cut | F051 text, F052 landmarks, F062 types |
| `violation` | a `fail`/`warning` (a violation was seen); a clean prefix is not a pass | F035 headings, F081 alt text, F036 |
| `first` | pass or fail once the first item exists | F084 first image |
| `complete` | nothing | F014 duplicate hash, F060 ratio, F054 hidden share |

Checks that read only headers or the fetch record (`F001`, `F006`, `F101`, ...) are
unaffected. Graph checks (`F009`, `F010`, `F072`) return `not_measured` instead of
`fail` while any other crawled page's link list is incomplete, because the missing
links may point at the page. `F061` (JSON-LD) judges each block by cause (section 3).
A registry test fails if a new content check does not declare its policy.

### Response states (what the fetch returned)

* **Truncated** - stated above; the explanation names the byte count and the limit.
* **Interstitial** - a short page whose title or opening text contains a configured
  challenge phrase (`FeatureConfig.interstitial_markers`, a heuristic list). All content
  checks are `not_measured`; the page is not the intended page.
* **Client-rendered shell** - almost no text in the initial HTML plus a concrete sign
  (an app mount point, a noscript "enable JavaScript" notice, or two or more scripts).
  Statuses do **not** change: the claim of those checks is about the HTML that was
  fetched, and that claim is true. Absence-based failures carry the limitation "the
  initial HTML looks client-rendered ... the audit does not execute JavaScript, so
  content added by scripts was not evaluated". Findings repeat it, and the combined
  cross-feature findings are not raised for such pages (one cause, already explained).
  Capability boundary: rendering (feature F108) is not implemented; adding it is the
  main follow-up.

## 3. JSON-LD (F061)

| Situation | Result |
|---|---|
| every block parsed, response complete | `pass` |
| a closed block is not valid JSON | `fail` ("could not be parsed") |
| a block never closes in a **complete** document | `fail` |
| a block never closes because the **response was truncated** | `not_measured` |
| a block was skipped (size / nesting limit) | `not_measured` ("limit") |
| no JSON-LD, complete document | `not_applicable` |
| no JSON-LD seen, document truncated | `not_measured` |
| documents extracted before causes were recorded | `fail` if complete, else `not_measured` |

Recommendations are derived from `fail` findings only, so the platform never tells a
user to repair syntax because the crawler lacked a complete input.

## 4. Owner-controlled settings

`noindex` (F005, F006), blocked crawlers (F004) and snippet limits (F030) are often
deliberate. Those features are `intent_dependent` in the catalog: they emit `warning`
with the wording "confirm intent", are unscored, and raise a **notice** finding
(`kind: notice`) with low confidence. Severity is `low`, or `medium` on the entry page,
where the same directive would hide the whole site. The finding never asserts the
setting is wrong.

## 5. What contributes to a score

`score = mean over measured, scored, contributing features of the feature's unit mean`
(unchanged, ADR-0012). `contributing` adds two rules (`features/contribution.py`), each
with a stated reason that reports display:

1. **Feature exclusions** (cannot discriminate under the audit's crawl configuration):
   * F009 always, for a link-discovered crawl: every crawled page has an incoming link
     by construction;
   * F072 when `min_incoming_links <= 1`: it is the same test as F009;
   * F010 when the crawl depth is not larger than `max_click_depth`.
   Without crawl facts (hand-built inputs) nothing is excluded.
2. **Unit overlaps** (a result that only repeats another feature's result on the same
   URL counts once): F072 repeating F009 (equal status, minimum <= 1); F059's
   "no main landmark" repeating an F052 failure; F069 repeating author/dates already
   failing under F046/F048/F049. Overlapping failures stay visible: the primary
   feature's finding names both features and the evidence of both.

Redundant units and excluded features leave numerator and denominator alike, as a
`not_applicable` unit does. Features whose property is genuinely independent still
count: a page with a missing `<main>`, a generic title and a missing description is
three failures. Documented, unadjusted overlaps (e.g. F052/F055 on div-soup pages) are
listed in `src/geoptimiser/validation/overlap.py`.

## 6. Reportability

* A group (overall, pillar, category) has `score` (the computed mean), `reportable`,
  `reported_score` (= `score` if reportable else `None`), `status`
  (`reportable`, `withheld_low_coverage`, `not_measured`, `no_applicable_features`) and
  `withheld_reason` with the measured/applicable counts.
* A score is reportable when `feature_coverage >= min_reportable_coverage` (0.5,
  inclusive) and a value exists. The threshold was **not** lowered; it is a project
  policy, not a statistical threshold (see the threshold register).
* Every consumer shows `reported_score` only: the JSON report, the HTML report, the UI
  and the comparison. A withheld group shows "withheld (m/n features measured)" and the
  reason; the computed value is in the JSON for transparency only. Coverage describes
  what was measured, never how well the site performs.
* Consequence: unimplemented (planned) scored features count as applicable-but-unmeasured,
  so the overall headline is structurally capped near 0.56 and is often withheld until
  more features are implemented. Category and pillar scores with enough coverage are the
  usable summaries.

## 7. Findings and recommendations

* One finding per scored feature with failures (merged across pages), plus notice
  findings for intent-dependent features. Findings list the affected URLs, the rule and
  threshold (`expected_value`), the observed value and the explanation of every cited
  result, whether the feature counts toward the score, the limitations of the
  measurement itself, and verification criteria.
* Heuristic findings and notices carry the ordinal `heuristic_confidence`.
* Recommendations are regrouped remediation text of findings and are screened for
  unsupported claims. The report states that no change is guaranteed to affect AI
  visibility.
* Inconclusive results are not findings. The report lists them under "Not measured"
  (`measurement_gaps`) with the reason.

## 8. Compatibility and migration

* `CATALOG_VERSION` 1 -> 2 and `SCORING_VERSION` 1 -> 2: scores from before and after
  are **not comparable**; the comparison service refuses such pairs
  (`incompatible_versions`). Extraction is `html-extractor:3`; older documents load
  (new fields default) and are treated as "cause unknown" / "head state unknown", so
  their truncated pages are `not_measured` until re-extracted.
* `AuditReport.report_version` 1 -> 2: only additive fields with defaults; version-1
  reports still load and render under the same reportability rule (`shown_score`).
* Changes that can alter a score: removal of free passes (F009, F010, F072, F015 on
  unredirected pages), owner-policy checks becoming unscored, double counts removed,
  truncated/cut evidence no longer counted as failures, categories below coverage no
  longer shown. See the before/after table in `GEOPTIMISER_FEATURE_AUDIT.md`.
