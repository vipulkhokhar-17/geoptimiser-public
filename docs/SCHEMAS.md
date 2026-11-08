# Shared schemas (Stage 00)

All cross-module data contracts live in `src/geoptimiser/schemas.py`. They are
Pydantic v2 models; later stages produce and consume them as JSON/JSONL artifacts.

## Contracts

| Model | Produced by (stage) | Purpose | Key invariants |
|---|---|---|---|
| `AuditRequest` | user input (00/16) | Explicit audit target and business context | `target_domain` required and format-checked; `authorization_confirmed` must be boolean `true` (a user attestation, see below); competitors format-checked, deduplicated, distinct from the target, and not capped by the schema |
| `FetchRecord` (+ `RedirectHop`, `StoredBody`) | crawler (01) | One fetch attempt: raw network observation | `outcome` must agree with `status_code` (see below); body stored by reference; credential headers rejected; `completed_at >= started_at` |
| `PageDocument` (+ `Heading`) | extraction (02) | Content extracted from one successful fetch | references `fetch_id` and `extraction_version`; empty `text` is valid; absent (`None`) differs from blank (`""`); limit hits are listed in `truncated_fields` |
| `ExtractionFailure` | extraction (02) | An extraction attempt that could not measure the content | closed `error_type`; non-blank `error_message` |
| `EvidenceRef` | any stage | Traceable source passage | non-blank `evidence_id`, `source_url`, `snippet`; closed `source_type` |
| `FeatureResult` | feature registry (03) | One versioned deterministic check | `feature_version >= 1`; unmeasured statuses carry no `observed_value`; `error_message` iff `status == "error"` |
| `Citation`, `VisibilityObservation` | provider adapters (05) | One provider response to one benchmark query | `query_set_version >= 1`; failed/skipped collection carries no response or annotations; `error_message` required for errors |
| `Finding` | diagnosis (09) | Evidence-linked conclusion | at least one `evidence_id` and one verification criterion; `basis` is `measured` or `model_judgement` |
| `Recommendation` | recommendations (10) | Reviewable proposed change | originates from at least one finding; at least one evidence ID and verification step; impact recorded as a direction only |

Stage 00 defines these contracts; it does not implement the stages that produce
them. Later stages may extend a model when their design needs it, recording the
reason in `docs/DECISIONS.md`.

## Conventions

- **Strict fields:** unknown fields raise a validation error (`extra="forbid"`).
- **Timestamps:** must be timezone-aware; they are normalized to UTC. Naive
  datetimes are rejected.
- **Identifiers:** 1–128 characters, starting alphanumeric, then letters, digits,
  `.`, `_`, `:` or `-` (e.g. `TECH-001`, `ev_3f2a`, `aud_<uuid hex>`).
- **Provenance:** every top-level artifact record carries `audit_id`; feature and
  query results also carry the version of the check or query set that produced them.
- **Missing is not negative:** `not_measured`, `not_applicable`, `error`, and
  failed collections are explicit states. Their validators prevent a value such
  as `False` from being recorded when nothing was actually measured.
- **Linking:** findings and recommendations refer to evidence and findings by ID.
  Checking that those IDs resolve across artifacts is left to the stages that
  assemble them (09/10).
- **Immutable records:** see below.

## Immutability

Records are treated as facts, not working state. After validation:

- **Field reassignment is rejected.** Every model is frozen, so
  `record.status_code = 404` raises a `ValidationError`.
- **Collections are tuples.** `evidence_ids.clear()` or `links.append(...)` would
  otherwise bypass `min_length` and element validation. Pass lists in; the model
  stores tuples. JSON is unchanged (arrays).
- **`FetchRecord.headers` is read-only** (a `MappingProxyType`, serialized as a
  plain JSON object), so a credential header cannot be added after validation.

What this does **not** cover:

- **Raw JSON values are not deep-frozen.** The dicts inside
  `PageDocument.structured_data`, and `FeatureResult.observed_value` /
  `expected_value` when they hold lists or dicts, can still be changed in place.
  No schema invariant depends on their contents, and deep-freezing arbitrary JSON
  would need a custom framework or a new dependency. The records are therefore
  immutable wherever an invariant depends on it, **not completely immutable**.
- **`model_copy(update=...)` skips validation, even on frozen models.**
  `fetch.model_copy(update={"status_code": 404})` on a `transport_error` record
  returns an invalid record without raising. Do not use it on shared records.
  To derive a changed record, validate a new instance:

  ```python
  updated = FetchRecord.model_validate(record.model_dump() | {"status_code": 404})
  ```

  This raises if the change breaks an invariant. `tests/test_immutability.py`
  pins both behaviours.
- **Hashing:** records that contain a mapping (`FetchRecord`, and `PageDocument`
  with structured data) are not hashable. Refer to records by their IDs.

## Fetching vs extraction

A fetch and an extraction are different events with different failure modes, so
they are recorded separately:

```
AuditRequest -> FetchRecord --(body stored by reference)--> PageDocument
                    |                                   \-> ExtractionFailure
                    \-> (no extraction for failed or non-2xx fetches)
```

`FetchRecord` is a **raw observation**: what the network returned for one
attempt. It never contains parsed content. `PageDocument` is **derived data**:
what a specific extractor version produced from a stored body. Because the body
is kept by reference, a newer extractor can re-derive documents without
re-fetching the site, and two extractor versions can be compared on identical
input.

### `FetchRecord.outcome`

| `outcome` | HTTP response received? | `status_code` | `final_url` | headers / body | `error_type` + `error_message` |
|---|---|---|---|---|---|
| `transport_error` | no (DNS, connection, timeout, TLS, redirect limit) | must be `None` | must be `None` | must be empty | required |
| `redirect_not_followed` | yes, a 3xx the crawler did not follow | 300–399 | required (the URL that returned the 3xx) | allowed; `redirect_refusal_reason` required | must be `None` |
| `http_error` | yes, an error response | 400–599 | required | allowed (the Stage 01 crawler does not store error pages) | must be `None` |
| `success` | yes | 200–299 | required | `body` or `body_not_stored_reason` required (exactly one) | must be `None` |

"No HTTP response" and "an HTTP error response" are therefore never confused: a
404 is something the server *said*; a timeout means the server said nothing.

Other invariants:
- `redirects` lists the 3xx hops that were followed, in order; the first hop must
  start at `requested_url`. Without redirects, `final_url` must equal
  `requested_url`. A transport error may keep hops (e.g. `too_many_redirects`).
- Header names are lowercased; `authorization`, `cookie`, `proxy-authorization`
  and `set-cookie` are rejected so credentials never reach artifacts. The crawler
  must drop them before building the record.
- `StoredBody` holds a store reference, a lowercase SHA-256 hex digest and the
  size in bytes, and `truncated` (the body was cut at a size limit). Storage,
  limits and truncation are decided in ADR-0007 and ADR-0008.
- `body_not_stored_reason` explains a response without a stored body:
  `empty_response`, `unsupported_content_type`, `unsupported_content_encoding` or
  `non_success_status`. It is never set together with
  `body`, and a `transport_error` never has one.
- `redirect_refusal_reason` (`https_downgrade`, `blocked_address`, `cross_domain`,
  `robots_disallowed`, `not_a_redirect`, `missing_location` and so on) is required for `redirect_not_followed` and forbidden otherwise.
- `error_type` also includes `blocked_address`, `blocked_port` and `blocked_url`
  (the crawler refused the target before connecting) and `incomplete_response`
  (the server closed before its declared length).
- Top-level records carry `schema_version` (ADR-0006). Artifact readers must see
  it explicitly in the JSON.
- `SkippedUrl.reason` (`skipped_urls.jsonl`) is `robots_disallowed` or
  `byte_budget_exhausted`: URLs that were not requested, which is not a failed
  fetch.

### Extraction

- `PageDocument` represents **successful** extraction only (ADR-0010 describes the
  extractor). `None` means a field is absent from the page; `""` means present but
  blank (`<title></title>`). `url` is the fetch's `final_url`; `fetch_id` joins to the
  `FetchRecord` for the requested URL, headers and body reference. `links` are
  absolute http(s) URLs (fragments removed, deduplicated; `mailto:`, `javascript:` and
  fragment-only links are dropped); `canonical_url` stays raw. `structured_data` holds
  the parsed JSON-LD objects, `structured_data_errors` counts blocks that were present
  but unparseable (so "no JSON-LD" and "broken JSON-LD" differ), and
  `structured_data_types` lists JSON-LD `@type` values (top level and `@graph`) and
  microdata `itemtype` values in document order. `truncated_fields` names fields cut
  by an extraction limit and `source_truncated` says the stored body was cut by the
  crawler: both mean "more existed", never "absent". `encoding` is the charset used.
  Extractor v3 (validation work, ADR-0027) adds, all with defaults so older documents
  still load: `structured_data_error_causes` (per cause: `syntax_error`, `unterminated`,
  `size_limit`, `nesting_limit`; empty = cause unknown, not "syntax error"), `head_complete`
  (`True`/`False`/`None` unknown: whether the end of `<head>` was read), `render_signals`
  (script count, mount points, noscript notice: facts about the initial HTML, never what
  a browser shows) and the new truncated field `title` (an unterminated `<title>`). Link
  rules are shared with the crawler (`crawler/urls.py`): `<noscript>` anchors count,
  `<template>`/`<svg>`/`<math>` anchors do not, `<base href>` applies.
- An empty `text`
  is a valid measurement (e.g. a JavaScript-only page with no server-rendered
  text), which is a negative result, not a missing one.
- `ExtractionFailure` records that extraction could not measure the content
  (`unsupported_content_type`, `decode_error`, `parse_error`, `other`).
- `check_extraction_source(fetch, result)` enforces the cross-record rule that a
  single model cannot see: the result must reference the fetch (`audit_id`,
  `fetch_id`), the fetch must be a `success` with a stored body, and a document's
  `url` must equal the fetch's `final_url`. HTTP error pages, unfollowed
  redirects and transport failures are never extracted.

## Traceability rule: every recommendation originates from a finding

The data lineage is measurements/observations -> findings -> recommendations.
A `Recommendation` must list at least one `finding_id` **and** at least one
`evidence_id`, plus a verification plan; none of these may be empty. A change
that addresses no diagnosed issue is not a recommendation. If an opportunity
exists (for example, competitors are cited for a benchmark query and the target
is not), it is first recorded as an evidence-linked `Finding`, and the
recommendation then refers to that finding. Checking that the referenced IDs
exist in the audit's artifacts is done by the stages that assemble them (09/10).

## Authorization semantics

`authorization_confirmed` records the user's **attestation** that they own or
are authorized to audit `target_domain`. It must be the JSON boolean `true`
(`1`, `"true"` and `"yes"` are rejected) so the attestation is always explicit.

It is **not** verified domain ownership and **not** a security control: the
schema cannot know whether the statement is true. Any ownership verification
(for example DNS TXT or file-based proofs) is out of scope for Stage 00 and
would be designed in a later stage.

## Operational limits

Schemas describe what valid data looks like; they do not encode cost or capacity
limits. There is no schema-level cap on `competitor_domains`. A limit on how many
competitors an audit processes belongs to configurable audit settings, introduced
by the first stage that spends crawl or query budget per competitor (01/05).
Stage 00 has no such consumer, so it defines no limit.

## Security boundary: what the schemas do not do

Schema validation is a data-format check, not a network security control.

- `normalize_domain` lowercases, strips whitespace and a trailing dot, and rejects
  URLs, ports, credentials, IP literals, single-label hosts (`localhost`), invalid
  labels and non-ASCII input (use punycode, e.g. `xn--mnchen-3ya.de`). It performs
  **no DNS resolution**, so names such as `app.localhost` or
  `metadata.google.internal`, which may resolve to loopback or private addresses,
  are accepted.
- `FetchRecord` and `PageDocument` URLs accept any http(s) URL, including
  `localhost`, private ranges and link-local metadata addresses. The records
  describe what was fetched; they do not decide what may be fetched.
- `RedirectHop.location` and the `location` header are raw, untrusted values.
  The schema does not validate where a redirect points.

DNS resolution, IP range restrictions, redirect validation, response size
limits, robots handling, rate limiting and other SSRF protections are the
responsibility of the Stage 01 crawler. Tests in `tests/test_schemas.py` and
`tests/test_fetch_extraction.py` pin this boundary so the schemas cannot be mistaken for those protections.

## Inspecting the contracts

```bash
python -c "import json; from geoptimiser.schemas import Finding; print(json.dumps(Finding.model_json_schema(), indent=2))"
python -m pytest tests/ -v
```

## Feature results and findings (Stage 03)

`FeatureResult` (one per feature per unit) gained optional fields, all with defaults, so
older records remain valid:

| Field | Meaning |
|---|---|
| `scope` | `page`, `site` or `audit` (the unit that was measured; features without a check are `audit`) |
| `subject_url`, `fetch_id`, `document_id` | Which page was judged (required for `page` scope) |
| `explanation` | One sentence saying why the status was given |
| `is_heuristic` | The criterion is a heuristic rather than an exact rule |
| `catalog_version`, `implementation_status` | Which catalog entry and implementation produced it |

States: `pass` (measured, criterion met), `fail` (measured, criterion violated; always
carries evidence), `not_applicable` (does not apply to this page/site), `not_measured`
(data or integration unavailable, including every `planned`/`unavailable` feature) and
`error` (the check raised). `warning` is emitted only by the intent-dependent features
(F004, F005, F006, F030): an observed condition that may be the owner's choice, reported as
"confirm intent" and not scored (ADR-0028). `not_measured` also covers incomplete
evidence: a truncated or limit-cut document, an interstitial page, an unreachable
canonical target (ADR-0027, `docs/validation/VALIDATION_POLICY.md`). A
`FeatureResult` with `implementation_status` `planned`/`unavailable` can only be
`not_measured`; observed values exist only for measured states and are JSON-native.

`Finding.basis` now also allows `heuristic`, and `Finding.remediation` carries guidance
text (reviewable proposals remain Stage 10 `Recommendation`s). Evidence IDs are
deterministic (`ev_<feature>_<hash of feature, URL and snippet>`); a finding may cite only
evidence produced by a failing result of its own features, and every evidence URL must be
a page or file the audit actually read (`validate_provenance`).

## Rich page structure (extractor v2, ADR-0013)

`PageDocument.detail_level` says which extractor produced a document: **1** carries the
Stage 02 fields only; **2** adds the fields below. A level-1 document cannot carry rich
values (the schema rejects them), because for it they are *unmeasured*, not absent;
the feature engine reports the checks that need them as `not_measured`.

| Field | Content |
|---|---|
| `viewport`, `charset_declared` | `<meta name=viewport>` content; `<meta charset>` or `http-equiv` charset |
| `images` (`ImageRef`) | `src` (absolute; `data:` for inline), `alt` (`None` absent, `""` empty), `width`, `height`, `loading`, `decorative`, `caption`, `context_before`/`context_after`, `in_navigation` |
| `anchors` (`Anchor`) | `href` (absolute, no fragment), `text` (or image alt), `rel` tokens, `internal` (same host family as the page), `region` (`content` or `navigation`), `has_image` |
| `landmarks` (`Landmark`) | `kind` (main, navigation, banner, contentinfo, complementary, region, article, search), `source` (`tag` or `role`), `labelled`, `label`, `text_chars` |
| `semantic_counts`, `boilerplate_chars`, `main_chars`, `hidden_chars` | semantic element counts; approximate visible characters inside navigation/banner/footer/aside, inside main/article, and hidden from view |
| `tables` (`TableRef`) | `caption`, `header_cells`, bounded `rows`, exact `row_count`/`column_count`, `has_header_cells`, `presentational` |
| `lists` (`ListBlock`) | `kind` (ul/ol/dl), bounded `items`, exact `item_count`, `depth`, `in_navigation` |
| `media` (`MediaRef`) | `kind` (video, audio, video_embed), `src`, `has_captions` (`True`/`False` for video, `None` for audio and embeds) |

`links` stays the deduplicated URL list; `anchors` adds the attributes. Hidden, inert
(`noscript`, `template`) and foreign (`svg`, `math`) elements are not collected.
Every collection is bounded by `ExtractionConfig`; a cut adds its name (`images`,
`anchors`, `landmarks`, `tables`, `lists`, `media`) to `truncated_fields`, and the
exact counts (`row_count`, `item_count`) are kept even when stored rows or items are cut.

## Query benchmark (Stage 04)

Contracts live in `geoptimiser.benchmark.models` (not the shared `schemas.py`): `Query`,
`QuerySet`, `Target`, `RelevanceJudgment`, `JudgmentSet`, and the result `EvaluationReport`
(`geoptimiser.benchmark.evaluate`). See ADR-0015 for the conventions on undefined metrics,
exclusions and data origin.


## Chunk (Stage 07)

`Chunk` (`chunks.jsonl`, schema version 1): `audit_id`, `chunk_id` (stable hash of chunker
version, document id and span), `document_id`, `fetch_id`, `url`, `chunker_version`,
`ordinal`, `heading_path`, `text`, `char_start`/`char_end` (half-open indices into
`PageDocument.text`; `text` equals that slice), `text_sha256`, `overlap_chars` (leading
characters repeating the previous chunk of the same section) and `source_truncated`.
`verify_chunks` proves a chunk list reproduces its document. See ADR-0018.

## Retrieval comparison (Stage 08)

`RetrievalComparison` (`retrieval_eval.json`, schema version 1) records, for one chunk
corpus and one query/judgment set, a `ModeResult` per mode (`lexical`, `dense`, `hybrid`,
`hybrid_rerank`): `status` (`measured` / `not_measured` / `error`), the Stage 04
`EvaluationReport`, latency summary, `ranking_digest` and paired comparison with the
lexical baseline. Top-level fields name the chunker versions, corpus and index
fingerprints, retrieval config, embedder and reranker (including `semantic`), and
`real_world_claim`. See ADR-0019.

## Evidence locators and diagnosis (Stage 09)

`EvidenceRef` gains optional `audit_id`, `chunk_id`, `document_id`, `char_start`,
`char_end` (all or none). When set, `snippet` equals `[char_start, char_end)` of the
document's extracted text. `Diagnosis` (`findings.json`, schema version 1) holds the
extended findings, the evidence they cite, notes and statistics. See ADR-0020.

## Recommendation set (Stage 10)

`RecommendationSet` (`recommendations.json`, schema version 1): `audit_id`, generator name
and version, `recommendations` (the Stage 00 `Recommendation` model), `rejected` (finding
ids and the reason a recommendation was held back), `skipped_finding_ids` and `notes`.
See ADR-0021.

`RetrievalComparison.embedder_descriptor` (additive, ADR-0022) holds the full embedding
model identity: `name`, `version`, `dimensions`, `semantic`, `model_id`, `revision`,
`normalized`, `similarity`, `max_seq_length` and `libraries`. A saved dense index
(`DenseIndex.save`) stores the same descriptor with its vectors and refuses to load for a
different model or chunk set.

## Agent result (Day 5, `agent_trace.json`)

`AgentResult` (schema version 1): `audit_id`, `goal`, `status` (`completed` / `incomplete` /
`failed`), `reason`, `provider`, `model_id`, `iterations_used` / `max_iterations`, `steps`
(`ActionRecord`: step, tool, bounded args, status `ok|error|rejected|invalid|timeout`, error
code, attempts, duration, the model's stated thought), `errors`, `findings_total`,
`evidence_valid`, `output_valid` (`null` when no recommendations exist), `recommendations`
(the Stage 10 `RecommendationSet`), `supplementary_evidence` (grounded `EvidenceRef`s found
by retrieval), `model_summary` (model-written and unvalidated) and timestamps. See ADR-0023.

## Fetch timings (Day 6, additive)

`FetchRecord.timings` (`FetchTimings`, optional): `dns_ms`, `connect_ms`, `tls_ms`,
`ttfb_ms`, `response_ms` (final exchange) and `total_ms` (whole fetch, all hops), in
milliseconds. A step that was not measured is `null` with a reason in `unmeasured`; it is
never 0. Redirect count, response size and the categorized transport failure were already
on the record (`redirects`, `body.size_bytes`, `error_type`). Older records load with
`timings = null`. See ADR-0024.

## Application records (Day 6)

`AuditReport` (`report.json`, schema version 1), `Comparison` (`comparisons/<id>.json`) and
the SQLite tables (`audits`, `stages`, `artifacts`, `comparisons`, `PRAGMA user_version` =
1) are described in `docs/APP.md`. Large artifacts stay as files; the database holds
identity, status, options, stage records, summaries and artifact references.
