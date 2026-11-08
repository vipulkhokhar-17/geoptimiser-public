# Architecture decisions

## ADR-0001: Start with a modular Python pipeline

**Status:** Accepted

**Decision:** Build the domain audit as independently runnable Python modules first. Add an API and frontend after the CLI stages are stable.

**Reason:** This supports learning, reproducible tests, and isolation of failures. It prevents UI or orchestration complexity from obscuring errors in the measurement pipeline.

## ADR-0002: Evidence-linked structured findings

**Status:** Accepted

**Decision:** A finding or recommendation must include stable IDs pointing to its evidence and a verification plan.

**Reason:** GEO diagnosis must be auditable. Report prose should be a rendering of structured findings, not the only record of what the system concluded.

## ADR-0003: Model complexity must earn its place

**Status:** Accepted

**Decision:** Use simple deterministic and retrieval baselines first. Add agents, rerankers, or LoRA only when a measured evaluation shows their contribution.

**Reason:** Feature count and framework count are not evidence of quality.

## ADR-0004: Strict, provenance-carrying shared schemas

**Status:** Accepted (Stage 00 review)

**Decision:** Shared Pydantic models reject unknown fields, require timezone-aware
timestamps (normalized to UTC), and carry `audit_id` plus the version of the check
or query set that produced them. Cross-field validators encode "missing is not
negative": unmeasured or failed observations cannot carry an observed value or annotations (a `FeatureResult`'s
`expected_value`, the threshold, is not a measurement and is not restricted).
URLs the platform requests are validated; URLs observed in untrusted content stay
raw strings so malformed values remain recordable observations. Findings and
recommendations must reference evidence by ID and include verification criteria;
every recommendation must also reference at least one finding. Recommendations
record only an expected impact direction, never a magnitude.

Schemas encode data validity only. They carry no operational limits (such as a
competitor count cap), which belong to configurable audit settings, and they are
not security controls: `authorization_confirmed` is a user attestation, and
domain/URL checks are format checks. DNS resolution, IP restrictions, redirect
validation and SSRF protection belong to the Stage 01 crawler.

Records are immutable after validation: the shared base model is frozen,
collection fields are tuples, and `FetchRecord.headers` is a read-only mapping.
A changed record is produced by validating a new instance
(`Model.model_validate(record.model_dump() | changes)`), never by
`model_copy(update=...)`, which skips validation even on frozen models. Raw JSON
values (`PageDocument.structured_data` contents, `FeatureResult.observed_value`
and `expected_value`) are not deep-frozen, so the records are immutable at every
level that a schema invariant depends on, not completely immutable.

**Reason:** These contracts sit between independently built stages. Failing loudly
at the boundary is cheaper than debugging silently dropped or mislabelled data
later, and it makes artifacts reproducible and auditable (ADR-0002). Validators
only run when a record is built, so a record that can be changed afterwards can
silently stop satisfying them.

**Alternatives considered:**
- *Lenient models (Pydantic's default, unknown fields ignored).* Rejected: a typo
  such as `sevrity` would be dropped silently and the record would still validate.
- *Naive or local timestamps.* Rejected: comparing a baseline audit with a
  follow-up across machines or time zones would be ambiguous.
- *Provenance only in a per-audit manifest.* Rejected as the only mechanism:
  JSONL records lose their context once copied, merged or loaded into a database.
  A manifest may still be added for schema versioning (see ADR-0006).
- *Validate every URL as `HttpUrl`.* Rejected: a malformed canonical tag or link
  is itself a GEO observation; rejecting the record would discard the evidence.
- *Optional evidence and finding links on recommendations.* Rejected: ADR-0002
  requires recommendations to be traceable.
- *A numeric expected uplift on recommendations.* Rejected: the specification
  forbids promising specific visibility or citation increases.
- *Operational limits in schemas (e.g. at most 10 competitors).* Rejected: no
  requirement justified the number, and limits depend on cost settings that
  belong to the stage that spends the budget.
- *`Literal[True]` for `authorization_confirmed`.* Rejected: it accepts `1`,
  because `1 == True` in Python.
- *Mutable models.* Rejected: any later assignment bypasses the validators.
- *Mutable models with `validate_assignment=True`.* Rejected: it validates field
  reassignment but not in-place changes such as `ids.clear()`, and it encourages
  using records as working state.
- *`frozen=True` alone.* Rejected: reassignment is blocked, but list and dict
  fields can still be changed in place (`evidence_ids.clear()`,
  `headers["set-cookie"] = ...`), breaking `min_length` and credential rules.
- *Deep immutability for every value, via a third-party frozen-dict package or a
  custom recursive freezer.* Rejected: it adds a dependency or custom framework,
  and no invariant depends on the contents of raw JSON values.

**Trade-offs accepted:**
- Any field change breaks loading of artifacts written under the old schema
  until schema versioning exists (see ADR-0006).
- Every producer must supply timezone-aware timestamps and explicit statuses.
- Collection fields are tuples in Python (JSON is unchanged: arrays and objects).
  Producers build lists and pass them in; consumers cannot append.
- `model_copy(update=...)` still bypasses validation; this is a convention
  enforced by review and documentation, not by code.
- Raw JSON values remain mutable in place.
- Frozen records containing a mapping (`FetchRecord`, and `PageDocument` with
  structured data) are not hashable, so they cannot be used as set members or
  dict keys; use their IDs instead.
- The schemas give no security guarantees: authorization is attested, and URL
  and domain checks are format checks only.

## ADR-0005: Separate fetch records from extracted documents

**Status:** Accepted (Stage 00 review)

**Decision:** Replace the single `PageRecord` with `FetchRecord` (one fetch
attempt, raw), `PageDocument` (content extracted from one successful fetch by a
versioned extractor, derived) and `ExtractionFailure`. `FetchRecord.outcome`
distinguishes a transport failure with no HTTP response (`status_code` is
`None`) from received responses (`success`, `http_error`,
`redirect_not_followed`). Response bodies are stored by reference (`StoredBody`)
rather than inlined, and parsed content never appears in a fetch record.
`check_extraction_source` enforces that only successful fetches with a stored
body are extracted.

**Reason:** CLAUDE.md requires raw observations to be stored separately from
derived data and missing measurements to be distinguishable from negative
results. A combined record could not represent a fetch with no response, mixed
crawler and parser failures, and forced a re-crawl to try a new extractor.
Stored bodies make extraction reproducible and comparable across versions.

**Alternatives considered:**
- *One `PageRecord` with a required `status_code` (the original scaffold).*
  Rejected: it cannot represent a timeout or DNS failure, and it mixes crawler
  output with parser output in one record.
- *`PageRecord` with an optional `status_code`.* Rejected: `None` would be
  ambiguous between "no response was received" and "not recorded", and parsed
  fields would still be mixed with fetch data.
- *Infer the outcome from `status_code` instead of storing `outcome`.* Rejected:
  explicit outcomes are easier to filter and read, and `redirect_not_followed`
  cannot be inferred reliably. The validators keep the two consistent.
- *Store the response body inline in the fetch record.* Rejected: JSONL files
  grow large, and customer HTML would be mixed into metadata that is logged and
  reported.
- *Discard bodies after extraction.* Rejected: every extractor change would
  require re-crawling the customer's site, and extractor versions could not be
  compared on identical input.
- *Represent extraction failures as a `PageDocument` with an error flag.*
  Rejected: every consumer would have to remember to check the flag before
  treating the record as content.
- *Nest the `FetchRecord` inside each `PageDocument`.* Rejected: it duplicates
  raw data and couples extraction artifacts to the fetch schema. The documents
  reference the fetch by ID instead.

**Trade-offs accepted:**
- Stage 01 must provide a body store, with size, retention and privacy rules
  (see ADR-0006).
- Reading "the page" needs a join between a `FetchRecord` and a `PageDocument`.
- The rule that only successful fetches with a stored body are extracted lives in
  `check_extraction_source`, which Stage 02 must call; a schema cannot enforce a
  rule that spans two records.
- `FetchRecord` cannot record why a redirect was refused or whether a body was
  truncated until those decisions are made (see ADR-0006).

## Decisions required before Stage 01 writes artifacts (resolved)

ADR-0004 and ADR-0005 left five open decisions, OD-1 to OD-5. Stage 01 settles them
in ADR-0006 to ADR-0009 below. Each is **Proposed** until the stage is reviewed.

## ADR-0006: Schema versioning and artifact layout (OD-1)

**Status:** Proposed (Stage 01, pending review)

**Decision:** Every top-level artifact record (`AuditRequest`, `FetchRecord`,
`PageDocument`, `ExtractionFailure`, `FeatureResult`, `VisibilityObservation`,
`Finding`, `Recommendation`) carries `schema_version`, currently `1`, typed as
`Literal[1]`. The model default (1) is for producers only. An artifact **reader**
(`read_fetches`) requires the field to be present and equal to the supported
version, so unversioned or newer artifacts are refused rather than read as v1.
Nested value objects carry no version. A crawl writes `fetches.jsonl` and
`skipped_urls.jsonl` incrementally (each line is flushed and `fsync`-ed before the
next request; files are created exclusively, so an existing audit is never
overwritten) and replaces `crawl_summary.json` atomically at the end. If an
exception ends the crawl, the summary is still written with
`stop_reason="aborted"` and the exception class name, and the exception is
re-raised. After a hard crash a final line may be torn; `read_fetches` ignores an
unterminated last line.

**Reason:** Models reject unknown fields and are frozen, so any field change breaks
old artifacts; a version on the record makes that failure explicit and keeps JSONL
lines self-describing when copied or merged.

**Alternatives considered:**
- *A per-audit manifest only.* Rejected as the sole mechanism: records lose their
  context once copied (see ADR-0004). `crawl_summary.json` still records the run.
- *Migrating old artifacts automatically.* Rejected for now: no old artifacts exist.
  A migration is written when version 2 is first needed.

**Trade-offs accepted:** one extra field per record; the version must be bumped by
hand on any breaking schema change. A fetch that fails while its body is being
stored has no record (the crawl aborts; earlier records are kept). `fsync` on every
line costs a few milliseconds per request.

## ADR-0007: Content-addressed local body store (OD-2, OD-3 storage side)

**Status:** Proposed (Stage 01, pending review)

**Decision:** Bodies live behind the `BodyStore` protocol. `LocalBodyStore` keeps
each body at `<root>/<sha256[:2]>/<sha256>` (mode 0600, atomic write) and
`StoredBody.ref` is `sha256:<hex>`. Identical bodies are stored once. `get` re-hashes
the file and refuses a mismatch; refs are validated against a strict pattern so a
crafted ref cannot leave the root. Only HTML is stored in Stage 01 (plus
`robots.txt`, kept for provenance). `delete(ref)` supports deletion on request and
`purge_older_than(days)` supports a retention sweep; the recommended retention is 30
days, **not enforced automatically**: nothing calls `purge_older_than`, and it is
unsafe to run while artifacts still reference bodies (deduplication means one file
can back records from several audits, and there is no reference index). Automatic
deletion needs reference tracking first; until then deletion is a manual operator
decision. A storage failure raises `StorageError` and aborts the crawl; it is never
recorded as a network error.

**Reason:** A hash is the reference, so a later layout change keeps the same ref
meaning and integrity can be verified. Bodies are customer content, so they stay out
of the JSONL records that are logged and reported (ADR-0005).

**Alternatives considered:**
- *An object store now.* Rejected: no deployment exists; the interface allows it later.
- *Refs as file paths.* Rejected: dangling when the layout changes, and path-traversal prone.
- *Storing PDFs and images.* Rejected: out of the HTML-only scope.

**Trade-offs accepted:** content addressing means deleting one body affects every
record that shares it; there is no automatic expiry, encryption at rest, or
cross-audit access control.

## ADR-0008: Size limits and truncation (OD-3, OD-4)

**Status:** Proposed (Stage 01, pending review)

**Decision:** Limits live in `CrawlConfig` (defaults: 2 MB per response, 50 MB per
audit, 500 KB for robots.txt, 25 pages). The body is read in 16 KB chunks and cut at
the limit while streaming; `Content-Length` is ignored. One extra byte is read to
detect truncation. A truncated body is stored and flagged `StoredBody.truncated`.
The remaining audit budget caps each fetch, so a response can be truncated by the
budget, and the stored total never exceeds `max_audit_bytes` (robots.txt included).
A page whose turn comes after the budget is spent is not requested; it is recorded
in `skipped_urls.jsonl` with reason `byte_budget_exhausted`, and the crawl stops
with `audit_byte_budget`. A response without a stored body always carries
`body_not_stored_reason` (`empty_response`, `unsupported_content_type`,
`unsupported_content_encoding`, `non_success_status`); `success` with no body and
no reason is invalid. A server that closes before its declared `Content-Length`
(or mid-chunk) is a `transport_error` with `error_type="incomplete_response"`, never
a complete body: only the crawler's own cut at the limit is a `truncated` body. Requests send
`Accept-Encoding: identity`, and compressed responses are not stored, which avoids
decompression bombs. Non-HTML bodies and HTTP error pages are not downloaded.

**Reason:** `body=None` previously meant a 204, an unstored body, or a too-large body.
Explicit reasons and a truncation flag remove that ambiguity (CLAUDE.md: missing is
not negative).

**Alternatives considered:**
- *Fail the fetch when over the limit.* Rejected: the page head is still useful, and
  the flag lets Stage 02 decide how much to trust a truncated page.
- *Decompress gzip.* Rejected: needs its own bounded decompressor; deferred.

**Trade-offs accepted:** a truncated HTML document may be unparseable at its end; an
HTTP error page's body is not kept (ADR-0005 allowed keeping it). A server that
*understates* `Content-Length` is read only up to that length and cannot be detected.
The record does not say whether truncation came from the per-response limit or the
remaining audit budget (the summary's `stop_reason` shows budget exhaustion).
URLs longer than 2083 characters are refused (the `HttpUrl` limit).

## ADR-0009: Redirect and network safety (OD-5)

**Status:** Proposed (Stage 01, pending review)

**Decision:**
- The fetcher uses stdlib `http.client`, so no dependency is added and redirects are
  never followed automatically.
- DNS is resolved once per hop. Every returned address must be public
  (`is_public_address`, which also blocks CGNAT, 6to4, Teredo, NAT64, documentation
  and unique-local ranges, and IPv4-mapped forms); one bad address rejects the host.
  IP literals skip DNS and are checked directly.
- The connection is made to the vetted IP, not the hostname, so a second DNS answer
  (rebinding) is never used. The connected peer is checked again. TLS verifies the
  certificate against the hostname.
- A redirect is followed only after checking: http(s) scheme, no credentials, an
  allowed port (default 80 and 443), no `https` to `http` downgrade, the target is
  inside the audited domain (or a subdomain), and its addresses are public. At most 5
  hops; loops are detected. A refusal is `outcome="redirect_not_followed"` with
  `redirect_refusal_reason`; a blocked initial target is a `transport_error` of type
  `blocked_address`, `blocked_port` or `blocked_url`.
- Only an allow-list of response headers is recorded; repeated headers are joined with
  `, `.
- A watchdog shuts the socket down at `max_fetch_seconds`, bounding slow-drip
  responses. There are no retries. Requests are paced (default one per second).
- `robots.txt` is honoured with RFC 9309 semantics: 4xx or empty means allowed; 5xx,
  unreachable or an unfollowed redirect means the origin is disallowed. Rules are
  matched by `geoptimiser.crawler.robots`, not `urllib.robotparser` (whose `*` and
  `$` support differs between Python releases): `*` wildcard, trailing `$`, longest
  pattern wins, `Allow` wins a tie, a specific user-agent group replaces `*`.
  Matching is iterative, so a hostile file cannot cause regex backtracking. URLs
  skipped for robots are recorded in `skipped_urls.jsonl`, not as failed fetches.
  Robots rules are also checked on every redirect destination before it is
  fetched; a disallowed destination is `redirect_not_followed` with reason
  `robots_disallowed`. If the audit budget is already spent, an unknown robots file
  is treated as disallowing.
- Redirects use the raw `Location` header, not the 2000-character copy kept in the
  recorded headers. Several differing `Location` headers, or one longer than 8192
  characters, are `invalid_location`. A 3xx that is not a redirect (300, 304, 305)
  is `not_a_redirect`; a redirect status without `Location` is `missing_location`.
  A page already fetched as a redirect destination is not fetched again.
- Callers may inject an `ssl_context` (for tests and private CAs). It must verify
  certificates and hostnames or the fetcher refuses it, and it cannot be combined
  with a custom connection factory. There is no option to disable verification.

**Reason:** Checking only a preliminary lookup leaves a window in which DNS can answer
differently. Pinning the validated address to the connection closes it.

**Alternatives considered:**
- *httpx or requests with event hooks.* Rejected: hostname-based connection and
  automatic redirects make pinning and per-hop checks harder to guarantee; a new
  dependency is not needed.
- *Resolve, then connect by hostname.* Rejected: reintroduces rebinding.
- *Follow cross-domain redirects.* Rejected: the audited domain is the user's
  attested target; off-site content is not theirs to audit.

**Trade-offs accepted:**
- `getaddrinfo` cannot be interrupted, so a hanging DNS server can exceed the time
  limits. The OS resolver's own timeout applies.
- No proxy support; the fetcher connects directly.
- Sitemaps are not read in Stage 01; discovery follows `<a href>` links only.
- Pages are fetched sequentially. There is no JavaScript rendering.
- The IP policy is a deny-list of non-public ranges plus Python's `is_global`; new
  special-use ranges need an update.

## ADR-0010: HTML extraction with the standard-library parser (Stage 02)

**Status:** Proposed (Stage 02, pending review)

**Decision:**
- **Parser:** `html.parser` from the standard library, driven by a small state
  machine, with no new dependency. Nothing is executed, fetched or rendered; scripts
  and styles are data. `<script type="application/ld+json">` is parsed with `json`;
  other scripts are ignored.
- **What is measured:** first `<title>`, `<meta name=description>`, `<meta name=robots>`,
  `<html lang>`, first `<link rel=canonical>` (raw), headings in order, visible text
  (block tags start a new line; `script`, `style`, `template`, `noscript`, `svg`,
  `math`, `hidden` elements and `display:none`/`visibility:hidden` inline styles are
  excluded), `<a href>` links resolved against the page URL (or `<base href>`), JSON-LD
  objects, and `@type`/`itemtype` values. Page chrome (nav, footer) is *kept* in the
  text: removing boilerplate is a content-quality judgement for a later stage.
- **Absent vs blank vs truncated:** `None` is absent, `""` is present but blank. Any
  field cut by a limit appears in `truncated_fields`; a crawl-truncated body sets
  `source_truncated`. Unparseable JSON-LD is counted in `structured_data_errors`.
- **Failures** are returned, never raised: unsupported content type, decode error
  (more than 10% undecodable characters), parse error (parser exception or time
  limit; only the exception class name is recorded, never page text), and `other`
  (body missing, unreadable, over the input limit, or failing its size/SHA-256 check).
  One bad page never stops the run. Non-pages are *skipped*, not failed: unsuccessful
  fetches, fetches without a stored body, and the crawler's `robots.txt` fetches
  (recognised by their final path).
- **Bounds:** input size, nesting depth (256), text (200k chars), headings (500),
  links (2000), JSON-LD blocks (50) and bytes (256 KB), types (100), and a 10 s
  wall-clock budget checked between 64 KB chunks and every 256 parser events.
- **Schema:** `PageDocument` gains `meta_robots`, `structured_data_errors`,
  `structured_data_types`, `encoding`, `source_truncated` and `truncated_fields`, all
  with defaults. No `PageDocument` artifact existed before Stage 02, so
  `schema_version` stays 1.
- **Artifacts:** `documents.jsonl`, `extraction_failures.jsonl`, `skipped_fetches.jsonl`
  are written line by line with `fsync` and exclusive creation (as in ADR-0006), with
  `extraction_summary.json` replaced atomically.

**Reason:** Stage 03's deterministic checks need reliable, explicit measurements of
metadata, structure and structured data. The tolerant standard parser handles broken
real-world markup without executing it, and keeps the dependency set unchanged.

**Alternatives considered:**
- *BeautifulSoup/lxml/trafilatura.* Rejected for now: new dependencies, and a
  main-content extractor makes a quality judgement before any evaluation exists
  (ADR-0003). They remain candidates if a measured baseline shows the need.
- *A full DOM tree.* Rejected: memory grows with the document; a stack of open tags
  is enough for hidden/inert regions and heading boundaries.
- *Failing on any undecodable byte.* Rejected: real pages contain stray bytes; only
  mostly-undecodable text is a failure.
- *Resolving or validating the canonical URL.* Rejected: it is an observation of
  untrusted content; Stage 03 decides what a relative or malformed canonical means.
- *Rendering JavaScript.* Rejected: out of scope and unsafe; a JavaScript-only page
  yields empty text, which is a measurement, not an error.

**Trade-offs accepted:**
- The standard parser is not a browser: unclosed or mis-nested markup is repaired
  approximately (an end tag closes intervening open tags; a heading ends at the next
  block tag), and a few edge cases differ slightly between Python releases, so
  fixtures avoid them.
- Past the nesting limit, tags are no longer tracked, so a later end tag may close an
  outer element of the same name.
- Time limits are checked only between parser events and chunks. A single pathological
  input that stalls inside the parser's own scan is not interrupted; the input size
  limit bounds it. There is no subprocess isolation.
- `@type` values come from the top level and `@graph` only, not from nested objects;
  JSON-LD `@type` and microdata `itemtype` values are mixed in one list.
- `<noscript>` text and links are ignored although a no-JavaScript client would see
  them.
- Links are not filtered for `rel=nofollow` and the text is not language-aware.

## ADR-0011: A 120-feature catalog with an honest registry (Stage 03)

**Status:** Proposed (Stage 03, pending review)

**Decision:**
- **Catalog first.** The product vocabulary is a versioned catalog of 120 features in 12
  categories (A–L) with stable IDs `F001`–`F120`. IDs are never renumbered. Each entry
  records its description, rationale, measurement definition and output type, inputs,
  evidence requirements, applicability, method, implementation status, severity policy,
  scoring policy, limitations, configuration keys, test requirements and the
  distinction from overlapping features. The source of truth is
  `src/geoptimiser/features/catalog_data.py`; `configs/feature_catalog.json` and
  `docs/FEATURE_CATALOG.md` are generated from it and a test fails if they drift. The
  placeholder YAML files in `configs/` are replaced (no YAML dependency is needed).
- **Honest status.** `implemented` and `partial` entries have a registered check and use
  only inputs that exist today; `planned` entries name the blocking data source or
  stage; `unavailable` entries need a capability not on the roadmap. Validators and the
  registry enforce this both ways (a check for a planned feature, or a runnable feature
  without a check, is an error), and `FeatureResult` refuses any status except
  `not_measured` for a planned/unavailable feature.
- **Today** (after extractor v2, ADR-0013): 40 implemented, 41 partial, 37 planned,
  2 unavailable. At first (extractor v1) it was 29/31/58/2. Working checks exist in
  categories A–K; category L (AI visibility) has none because Stages 05/06 do not exist yet.
- **Registry.** Checks are plain functions registered with `@check(id, scope, requires)`;
  the engine handles iteration, the "no extracted document" case (`not_measured`, never
  `fail`), exceptions (`error`), evidence construction and JSON-normalising of values. A
  failing outcome without a cited observation is rejected. Adding a feature means adding
  a catalog entry and a function.
- **Inputs.** Checks read `AuditInputs` built from Stage 01/02 artifacts (fetches,
  documents, failures, robots.txt bodies) and a `FeatureConfig`. Cross-page indexes
  (titles, text hashes, link graph) are computed once per run. One page is kept per
  final URL.
- **Thresholds are configuration.** Every number and word list lives in `FeatureConfig`
  and is a policy default, not a ranking factor; results carry the threshold used as
  `expected_value`. Heuristic checks are flagged in the catalog, in results and in
  findings.
- **Schema.** `FeatureResult` gains `scope`, `subject_url`, `fetch_id`, `document_id`,
  `explanation`, `is_heuristic`, `catalog_version` and `implementation_status`;
  `Finding` gains `basis="heuristic"` and `remediation`. All are additive with defaults;
  `schema_version` stays 1 because no `FeatureResult` or `Finding` artifact existed.

**Reason:** Evaluations and later stages need stable feature identifiers, and the plan
must show what is *not* yet measured instead of hiding it. Wide, honest coverage lets
Stage 03 start with what the data supports and grow without renumbering.

**Alternatives considered:**
- *Only implement the checks that work (about half of the catalog entries).* Rejected: the
  catalog is the architecture; gaps must be visible and carry their blocking dependency.
- *YAML catalog.* Rejected: needs a new dependency; a Python source with exported JSON
  is typed, testable and reviewable.
- *Extend Stage 02 now to unlock images, landmarks and viewport.* Rejected here: it is a
  separate extractor change with its own tests; the blocked features name it.
- *A new result schema.* Rejected: `FeatureResult`, `EvidenceRef` and `Finding` already
  express the concepts; only optional fields were added.

**Trade-offs accepted:** many catalog entries are definitions only. Several checks are
heuristic or partial and say so. The link graph covers crawled pages only, so
orphan-page risk (F009) is almost always satisfied by a link-driven crawl until sitemap
URLs exist. English-only word lists apply to the lexical heuristics.

## ADR-0012: Findings, evidence and scoring that do not reward missing data (Stage 03)

**Status:** Proposed (Stage 03, pending review)

**Decision:**
- **Evidence.** Every observation is a real value (or a stated absence) at a URL the audit
  fetched, with the fetch time. IDs are deterministic. `validate_provenance` rejects
  evidence citing unknown URLs, failing results without evidence, findings whose
  evidence does not come from a failing result of their own features, and findings that
  name no feature. `run_audit` calls it, so an artifact is never written with dangling
  evidence.
- **Findings.** One finding per *scored* feature with failures (duplicate control): the
  affected URLs appear as evidence (capped, with the cap stated in the limitations).
  Severity is the highest among the failing results. `basis` is `heuristic` for heuristic
  checks, whose confidence is the configurable ordinal `heuristic_confidence` (not a
  probability); partial checks carry a limitation saying so. Unscored (informational)
  features appear in results but raise no findings.
- **Scoring (version 1).** Units count pass 1, fail 0, warning 0.5. `not_applicable` units
  are removed; `not_measured` and `error` units are never scored and lower coverage.
  A feature's pass rate is its mean over measured units; a group's score (category, pillar,
  overall) is the unweighted mean of its measured scored features' pass rates. Each group
  reports `feature_coverage` (measured / applicable scored features, counting every
  unimplemented feature as applicable and unmeasured), `unit_coverage`, and `reportable`
  (coverage at least `min_reportable_coverage`, default 0.5); a score that is not
  reportable must not be shown as a headline. Technical health, content quality,
  retrieval readiness and observed AI visibility are separate groups; AI visibility has no
  score until provider data exists.
- **Unscored features** (`scored=false`) are those with no universal criterion or whose
  absence is normal (for example Q&A structure, latency, cache headers). They are reported
  but never change a score.

**Reason:** A score that ignores gaps would rise when less is measured. Excluding
unmeasured units keeps the rate honest, and coverage makes the gap visible; a coverage floor
stops a handful of passing checks from looking like a verdict.

**Alternatives considered:**
- *Treat missing as fail.* Rejected: it punishes lack of tooling and violates "missing is
  not negative".
- *Treat missing as pass or skip silently.* Rejected: it rewards missing data.
- *Weights by severity or category.* Rejected for now: there is no evidence for any
  weighting (ADR-0003). Equal weights are transparent and can be revisited with data.
- *One blended number.* Rejected: the four pillars answer different questions, so they
  are reported separately and the overall is labelled as an unweighted mean.

**Trade-offs accepted:** with the current coverage most categories are below the
reportable floor, which is the honest state. Equal feature weights let many similar
checks dominate a group. Pass rates weight a feature once however many pages it covers.

## ADR-0013: Extractor v2 — rich page structure (extension of Stage 02)

**Status:** Proposed (pending review)

**Context:** The feature catalog (ADR-0011) left 21 features `planned` because the
extractor recorded only text, headings, link URLs and structured data. Numbering note:
the roadmap's Stage 04 is the query benchmark; this work extends Stage 02 and is not
that stage.

**Decision:**
- **One parse, one document.** `html-extractor:2` extends the existing `PageDocument`
  (no parallel record) and keeps the same provenance (`fetch_id`, `url` = final URL).
  A new `detail_level` field (1 or 2) separates "not extracted" from "none on the page":
  a level-1 document may not carry rich values, and checks that need them declare
  `requires="rich_document"` so the engine returns `not_measured` for older documents.
- **What is collected** (all from static HTML, nothing executed or fetched): images with
  attributes and surrounding text (before, after, `figcaption`); anchors with text, `rel`,
  region and internal/external; landmarks (tags and ARIA roles) with region text;
  tables and lists with bounded cell/item text and exact counts; `video`/`audio` with
  caption tracks and known video-player iframes; viewport; declared charset.
- **Bounds.** Each collection has a limit in `ExtractionConfig`, enforced while parsing,
  with the cut reported in `truncated_fields`. Elements deeper than `max_nesting_depth`
  are not tracked (so a later end tag may close an outer element of the same name).
- **`links` is kept** (deduplicated URL list, used by the link graph) and `anchors`
  adds attributes. This is a small duplication accepted to leave Stage 03 untouched.
- **Internal vs external** is relative to the page's own host (www and subdomains are the
  same site). The audit's site domain can differ, so checks that need the audit's view
  reclassify from `href`.
- **Features.** 21 features move from planned to runnable (F029, F052–F059, F077, F078,
  F081–F084, F086–F089, F094, F095) and F002 and F028 become `implemented`. Only features
  whose definition is genuinely met by the data moved; keyword or title-based rules are
  `partial` and flagged heuristic (F057, F058, F078, F082, F084, F086, F089, F094, F095),
  and F059/F077/F088 stay `partial` for stated reasons.
- **Schema versioning.** The new `PageDocument` fields are additive with defaults and no
  level-2 artifact existed before, so `schema_version` stays 1.

**Alternatives considered:**
- *A separate "structure" artifact.* Rejected: a second record to join and keep in sync;
  the same fetch and parse produce both.
- *Replacing `links` with `anchors`.* Rejected: breaking for the link graph and readers.
- *BeautifulSoup or lxml.* Rejected again (ADR-0010): no new dependency; the tag-event
  state machine is enough and keeps every bound explicit.
- *Inferring "no images" from an empty list on old documents.* Rejected: it would turn a
  missing measurement into a pass.

**Trade-offs accepted:** the standard parser repairs mis-nested markup approximately, so
unclosed tables, cells and list items follow simple closing rules rather than HTML5
tree construction. Region text counts are approximate (counted per text chunk).
Landmark and region detection depends on the page using semantic elements or roles.
Embedded players hide their captions, so `video_embed` has `has_captions=None`.
Re-extraction is required to give older documents rich fields.

## ADR-0014: Completing the RAG stages 04–10 in dependency order (plan and assumptions)

**Status:** Proposed (pending review)

**Context:** Stages 04–10 of the roadmap were all "Not started": nothing existed for query
benchmarks, providers, visibility metrics, chunking, retrieval, grounded diagnosis or
recommendations. The retrieval work (Stage 08) cannot be evaluated without Stage 04
(queries and labels) and Stage 07 (chunks), and diagnosis and recommendations
(Stages 09 and 10) need both. The stages are therefore built in the order 04, 05, 06, 07,
08, 09, 10, one commit each.

**Decisions and assumptions:**
- **No new dependencies.** Everything uses the standard library and pydantic. numpy is not
  declared and CI installs only `.[dev]`; no embedding model is available.
  *(Superseded for semantic retrieval by ADR-0022: an optional `semantic` extra now
  exists. The default install and CI are unchanged.)*
- **JSON for datasets.** Query and judgment sets are JSON (stdlib), replacing the placeholder
  `configs/query_benchmark.yaml`, as the YAML catalog placeholders were replaced in Stage 03.
- **Data origin is always explicit.** Every dataset and result records whether it is a
  `fixture`, `mock`, `draft` or reviewed/`human`/`live`; results from fixtures or mocks never
  carry a real-world claim.
- **Live AI-search adapters are a documented blocker.** They need credentials, a provider
  decision and network access that cannot be tested here. Stage 05 delivers the provider
  contract, credential gating, error taxonomy and deterministic fakes; no live adapter is
  claimed.
- **No LLM generation.** Recommendations (Stage 10) are deterministic templates; nothing
  calls a model.
- **Branch.** Work continues on the designated branch restarted from the latest `main`.
- **Shared helpers.** `geoptimiser/jsonl.py` provides the durable-write conventions
  (exclusive creation, `fsync` per line, atomic JSON, torn-line tolerant reads) for the new
  stages without touching the older writers.

## ADR-0015: Versioned query benchmark, relevance labels and metrics (Stage 04)

**Status:** Proposed (Stage 04, pending review)

**Decision:**
- **Datasets.** `QuerySet` (name, version, industry, closed intent taxonomy, unique ids and
  texts, at most 1000 queries) and `JudgmentSet` (names the query-set name and version it
  was written for; graded labels 0–3; `origin` `fixture` or `human`, a human origin naming
  the judge). A reviewed query set must name a reviewer and date; a draft cannot. Evaluation
  refuses a judgment set written for another query set or version.
- **Starter set.** `configs/query_benchmark.json` is a short, generic B2B SaaS list marked
  `draft` and described as not reviewed. No human-reviewed benchmark exists; producing one is
  a manual task the roadmap requires before any real-world claim.
- **Labels point at targets** (a page, or a section by heading), not at chunk IDs, so the
  same labels survive re-chunking; the retrieval stage maps targets to chunks.
- **Metrics:** Recall@k, hit rate@k, MRR and nDCG@k (gain `2**grade - 1`, log2 discount).
  Rankings are de-duplicated. Grade 0 means judged not relevant; no judgment means unknown.
- **Undefined is not zero.** A query without labels, with only grade-0 labels, whose relevant
  targets are absent from the corpus, or without a run is excluded and listed with its
  reason. An empty ranking is a real measurement and scores 0. Labels for unknown queries or
  absent targets are reported in `issues`.
- **Result.** `EvaluationReport` records query- and judgment-set names and versions, review
  status, label origin, `ks`, per-query scores, means over evaluated queries only, exclusions
  and issues. `real_world_claim` is true only for human labels on a reviewed query set.

**Alternatives considered:** *Scoring unlabelled queries 0* (rejected: it punishes missing
labels). *Labels keyed by chunk ID* (rejected: breaks on re-chunking). *YAML* (rejected: new
dependency).

**Trade-offs accepted:** the fixture proves the arithmetic, not retrieval quality; graded
relevance needs human effort; section targets match by heading text.

## ADR-0016: Provider contract and visibility collection (Stage 05)

**Status:** Proposed (Stage 05, pending review)

**Decision:**
- **Contract.** `AnswerProvider` (Protocol) has `name`, `model`, `origin` (`live`, `mock` or
  `fixture`), `check_available()` and `answer(query, timeout_seconds)`. Errors form a small
  taxonomy: `ProviderUnavailable` (credentials/config), `ProviderTimeout`,
  `ProviderRateLimited`, `ProviderResponseError`. Adapters must not put credentials or
  response bodies in error text. `require_env(variable, env)` gates credentials, names the
  variable and never its value, and takes the environment as an argument.
- **Doubles.** `ScriptedProvider` (origin `mock`) and `FixtureProvider` (origin `fixture`,
  replaying recorded answers) are deterministic and make no network calls. No test requires
  credentials or the network.
- **Collection.** `collect_visibility` asks every provider every query `repeats` times,
  sequentially, with a call budget checked before any call, no retries, and per-call
  timeouts left to the provider. Every attempt becomes a `VisibilityObservation`:
  `success`, `error` (provider error or contained adapter bug, with a safe message) or
  `skipped` (provider unavailable, never contacted). Failed or skipped records carry no
  response and no annotation. A draft query set is refused unless explicitly allowed, and
  the manifest records the query set's review status.
- **Origin.** `VisibilityObservation` gains `origin` and `repeat_index`, both additive. An
  unrecorded origin (`None`) is never treated as live. Responses are clipped
  (`max_response_chars`, `max_citations`) and the number of clipped responses is recorded.
- **Artifacts.** `visibility.jsonl` (durable per line) and `visibility_manifest.json`.
- **Untrusted text.** Answer text is stored verbatim and treated as data; nothing in it can
  change configuration or control flow.

**Blocked / not done:** **no live AI-search adapter.** Writing one needs credentials, a
choice of one or two providers and a way to test against them, none of which exist here.
The contract is what such an adapter plugs into. Until then no observation in this
repository is a real provider measurement.

**Alternatives considered:** *Writing a generic HTTP adapter with guessed response formats*
(rejected: untestable and likely wrong). *Retries with back-off* (rejected for now: bounded,
simple behaviour first). *Treating unavailable providers as errors* (rejected: `skipped`
says nothing was attempted).


## ADR-0017 — Visibility annotation and metrics (Stage 06)

**Status:** Accepted (proposed by implementation; awaiting review)

**Decision.**
- **Annotation is deterministic and separate from collection.** `annotate` sets
  `brand_mentioned` and `competitors_mentioned` by whole-word, case-insensitive matching of
  an entity's name, aliases and domains (regex-escaped). It annotates only `success`
  observations; failed or skipped ones stay `None`, so a missing answer is never "not
  mentioned". Names that are ordinary words (e.g. "Notion") cannot be disambiguated; this
  is a documented limitation. A `BrandSpec` is supplied explicitly per audit.
- **Citations** count for an entity when the URL host equals a declared domain or is a
  subdomain of it (`acme.com.evil.net` and `notacme.com` do not match).
- **Metrics** are computed per `(provider, model, origin)` group; origins are never pooled.
  Rates (query coverage, mention rate, citation rate, repeat consistency) carry numerator,
  denominator and a Wilson 95% interval. A zero denominator gives `not_measured` with
  `rate=None`, never 0. Errors and skips are counted separately and never enter a
  denominator.
- **Real vs. not real.** Only `origin == "live"` groups are `real_measurement`. With none,
  the metrics carry an explicit note that nothing measures real AI-search visibility; since
  no live adapter exists (ADR-0016), every figure today is mock/fixture.
- **Artifact.** `visibility_metrics.json` via `write_metrics` (atomic, no overwrite),
  recording metrics/annotator versions and the query set's name, version and review status.

**Limitations.** Mention rates over small samples have wide intervals; consistency compares
only the mention outcome across repeats; no sentiment, position or share-of-voice yet.

**Alternatives considered:** *LLM-judged mentions* (rejected: not needed for name matching,
unmeasured accuracy). *Pooling providers into one rate* (rejected: hides differences and
mixes real with mock data).

## ADR-0018 — Structure-aware, offset-exact chunking (Stage 07)

**Status:** Accepted (proposed by implementation; awaiting review)

**Decision.**
- **Chunks are verbatim slices.** `Chunk.text == PageDocument.text[char_start:char_end]`
  (half-open). The model validates length and `text_sha256`; `verify_chunks` additionally
  checks the slice against the source document, identity (audit, document, fetch, URL),
  ordering, unique/stable ids, `source_truncated`, and that **every non-blank character is
  covered**. `chunk_documents` verifies before writing and raises
  `ChunkVerificationError` rather than store unfaithful evidence.
- **Structure first.** The text is split at heading lines (located in order as whole
  lines, as in the feature checks; a heading that cannot be found is ignored, never
  guessed). `heading_path` is the heading stack in force. A page without locatable
  headings is one section. The heading line stays inside its section's first chunk.
- **Bounded size and overlap.** `max_chars` (100–8000, default 1200) and `overlap_chars`
  (≤ half of `max_chars`, default 150). Long sections are cut at a newline, else a
  sentence end, else a space, and only then hard-cut; the overlap starts on a word
  boundary and never crosses a section boundary. `overlap_chars` on each chunk says
  exactly how many leading characters repeat the previous chunk, so duplication is
  declared, not silent. No content is dropped except whitespace at chunk edges.
- **Limits.** `max_chunks_per_document` (default 500) bounds output; hitting it sets
  `stopped_at_limit` and `covered_until`, and `verify_chunks` reports the gap unless the
  caller says `complete=False`.
- **Truncation.** `source_truncated` is copied from the document to each chunk. Chunking
  works on the extracted text only, so any extraction limit already applied is inherited.
- **Stable ids.** `chunk_id` hashes chunker version, document id and span; re-chunking the
  same document with the same version reproduces ids (but changing size settings changes
  spans and therefore ids).
- **No duplicate representation.** Chunks store only offsets and text for their own span;
  document fields (title, links, structured data) stay on `PageDocument`.
- **Artifact.** `chunks.jsonl` (exclusive create, fsync per line, explicit schema version).

**Limitations.** Offsets are into the *extracted* text, not the raw HTML. Heading-only
sections yield small chunks. Lines are the extractor's block approximation, so a table or
list is chunked as lines of text. Character counts, not tokens.

**Alternatives considered:** *Fixed-size windows ignoring headings* (rejected: splits topics
and loses heading context). *Token-based sizing* (rejected: needs a tokenizer dependency
and a model choice). *Storing the chunk text only* (rejected: offsets are what let a
finding point back into the source).

## ADR-0019 — Retrieval baselines and comparison (Stage 08)

**Status:** Accepted (proposed by implementation; awaiting review). Its "no real embedding
model" and dependency limitations are partly superseded by ADR-0022; the original text
below is unchanged.

**Decision.**
- **BM25** (Okapi, Lucene-style idf `ln(1 + (N-df+0.5)/(df+0.5))`), `k1=1.2`, `b=0.75`,
  configurable. Query terms count once; only chunks containing a query term are returned;
  ties break on `chunk_id`. Scores are hand-computed in the tests.
- **Dense retrieval** is an exact cosine scan behind a versioned `EmbeddingProvider`
  (`name`, `version`, `dimensions`, `semantic`). The only shipped provider,
  `HashingEmbedder`, is a deterministic **test embedder** (signed feature hashing of
  tokens); it reflects word overlap, not meaning, is flagged `semantic=False`, and every
  comparison that uses it says so. Provider failures become `EmbeddingError` without the
  provider's message; vectors of the wrong size or with non-finite values are rejected.
  A query with no signal returns no hits rather than arbitrary ones.
- **No HNSW/IVF/vector database.** An exact scan is correct and sufficient at audit scale
  (hundreds to thousands of chunks); an approximate index would add recall loss to measure
  without a demonstrated need.
- **Hybrid** is reciprocal rank fusion (`sum 1/(k+rank)`, `k=60`) of the lexical and dense
  lists with per-source ranks kept on every hit. Ties break on best source rank then
  `chunk_id`; the result does not depend on dictionary order.
- **Reranking** goes through a `Reranker` interface; `apply_reranker` rejects any output
  that adds, drops or repeats a candidate. The shipped `TermCoverageReranker` is a simple
  deterministic baseline, not a learned model.
- **Comparison** (`compare_retrieval`, `retrieval_eval.json`) runs lexical, dense, hybrid
  and hybrid+rerank over the same queries, chunk corpus and judgments, scores them with
  the Stage 04 metrics (judgment targets resolve to chunks by page URL and, optionally,
  heading), and records chunker/embedder/reranker versions, index and corpus fingerprints,
  config, per-mode latency (mean/p50/p95/max, injectable timer) and a ranking digest.
  Reproducibility is judged by the digest, not by timings. Paired wins/losses/ties
  against the lexical baseline are given for nDCG@10 and Recall@10. A mode that cannot run
  is `not_measured`; one that raises is `error`; neither is scored 0.
- **Claims.** `real_world_claim` is true only for human labels on a reviewed query set.
  The shipped fixture corpus and labels are synthetic, so the fixture results show that the
  machinery works, not that any method is better. On that fixture all four modes tie,
  which is expected because the test embedder adds no information beyond word overlap.

**Limitations.** Chunk-level relevance: a page-level label marks every chunk of that page
relevant, which lowers Recall@k for long pages. English-only tokenisation without stemming
(so "encrypt" does not match "encrypted"). No real embedding model is wired in, so whether
dense or hybrid retrieval helps on real sites is unmeasured.

**Alternatives considered:** *rank_bm25 / numpy dependencies* (rejected: the dependency set
stays at pydantic; the algorithm is small and testable). *Score-based fusion* (rejected:
BM25 and cosine scores are on incompatible scales). *Stemming* (deferred: a measurable
change that should be evaluated against labelled data first).

## ADR-0020 — Evidence-linked diagnosis (Stage 09)

**Status:** Accepted (proposed by implementation; awaiting review)

**Decision.**
- **Extend, don't replace.** `diagnose` takes the Stage 03 `AuditRun` and returns a
  `Diagnosis`. Every original finding keeps its id, title, severity, basis, features,
  confidence and its original evidence ids (in order); additions are appended. The Stage 03
  artifacts (`findings.jsonl` etc.) are untouched; `findings.json` is the extended view.
- **Additive locators on `EvidenceRef`.** New optional fields `audit_id`, `chunk_id`,
  `document_id`, `char_start`, `char_end`. All-`None` for measurement evidence (older records
  load unchanged). If any locator field is set, all must be, `snippet` must be exactly as
  long as the range, and — checked by `validate_grounding` against the stored chunks — equal
  to that slice of the chunk, in the same audit, document and page.
- **Passages are context, not proof.** For each page-scoped finding, up to
  `max_passages_per_finding` chunks from the *affected pages* are attached: retrieval-ranked
  ones first (optional, using the finding's catalog name and description as the query —
  never page text), then each affected page's first chunk. The finding gains a limitation
  saying the passages do not by themselves prove the defect. Retrieval being absent,
  unavailable (mode not configured) or failing degrades to page leads with a note; no chunks
  at all degrades to measurement evidence only.
- **Cross-feature synthesis** is data (`SynthesisRule`): a rule fires on a page only when
  *every* required feature has a failing result there. The finding (`syn_<rule_id>`,
  category `cross_feature`, basis `heuristic`, configurable confidence) cites only evidence
  already produced by those failing results and states that co-occurrence is not interaction
  or causation. Rules are validated against the catalog: unknown, unimplemented or
  non-page features are rejected. Three conservative defaults ship.
- **No model judgement.** Nothing in this stage produces `basis="model_judgement"`.
- **Self-verification.** `diagnose` runs `validate_diagnosis` and raises `DiagnosisError`
  on any problem: findings unique and in this audit, originals preserved, every evidence id
  present, measurement evidence equal to the audit's record and from a failing result of the
  finding's own features, passage evidence grounded and on a page the finding is about, no
  unreferenced evidence.
- **Untrusted text.** Page text enters only as quoted snippets. It does not influence
  severity, rule selection, queries or control flow (tested with an injection string).
- **Determinism.** Same run, chunks and clock give byte-identical output; the clock is
  injected for `retrieved_at` and `created_at`.

**Limitations.** Page-lead passages show where the page text begins, not where the defect
is. Retrieval quality for choosing passages is unevaluated on real data (ADR-0019). Site-level
findings get no passages. The synthesis rules are heuristics with no validated link to
visibility.

**Alternatives considered:** *LLM-written diagnoses* (rejected: no accepted ADR requires it
and it would add unmeasured judgement). *Replacing measurement evidence with passages*
(rejected: they answer different questions). *A parallel evidence type* (rejected: an
additive `EvidenceRef` keeps one representation).

## ADR-0021 — Template recommendations and claim validation (Stage 10)

**Status:** Accepted (proposed by implementation; awaiting review)

**Decision.**
- **No model.** `TemplateGenerator` (behind a `RecommendationGenerator` protocol)
  builds each `Recommendation` from fields the findings already carry: remediation text
  (`proposed_change`), verification criteria (`verification_plan`), measurement methods and
  limitations (`rationale`), evidence ids. Nothing is paraphrased, so nothing can be
  invented.
- **Grouping.** Findings whose remediation text is identical after whitespace and case
  normalisation become one recommendation that links all of them and the union of their
  evidence (capped). Findings without remediation are listed in `skipped_finding_ids`, not
  guessed at. The recommendation id is a hash of its finding ids, so it is stable.
- **Configurable rules** (`RecommendationConfig`): a complete severity-to-priority table
  (P0–P3) with a one-step demotion when every finding is heuristic; effort from a default,
  per-category and per-feature table, raised one step when more pages are affected than
  `large_scope_pages`; confidence is the minimum of the findings' confidence.
- **Impact direction is `uncertain` by default.** No experiment exists yet (Stage 15), so
  nothing supports a direction. A different direction needs an explicit `ImpactRule` naming
  the feature and carrying a written justification, which is quoted in the rationale.
- **Claim screening** (`claim_problems`): percentages, multipliers, "guarantee"-style
  wording, certain-outcome verbs ("will increase/improve/rank …") and ranking promises are
  detected in the final recommendation text. **URL grounding:** any URL in the text must be
  an evidence source or named by a linked finding's verification criteria. A recommendation
  that fails is *rejected and listed* with its reason (never rewritten or silently
  dropped), and the others still proceed.
- **Self-check.** `validate_recommendations` verifies that each recommendation's findings
  exist in the audit, its evidence exists and is cited by those findings, no unsupported
  claim is present, and no finding is covered twice.
- **Artifacts.** `recommendations.json`, written with `findings.json` by `write_outputs`
  (atomic, never overwrites).

**Limitations.** Pattern screening is blunt and English-only; it can reject benign text and
cannot detect every unsupported claim. A synthesized cross-feature finding and its component
findings can yield overlapping recommendations because their remediation text differs.
Priority here is a transparent rule, not the Stage 13 scoring model.

**Alternatives considered:** *LLM-written recommendations* (rejected: no accepted ADR calls
for it, and quality would be unmeasured). *Rewriting offending text automatically*
(rejected: hides a defect that a reviewer should see). *Numeric impact estimates* (rejected:
nothing grounds them).

## ADR-0022 — Local semantic embeddings via an optional extra (Stage 08 extension)

**Status:** Accepted (proposed by implementation; awaiting review). Supersedes the
"no new dependencies / no embedding model" assumption in ADR-0014 and the "dependency set
stays at pydantic" note in ADR-0019, for this one capability only.

**Context.** ADR-0019 shipped an exact dense path whose only embedder is a word-overlap
test double. Merging needs genuine semantic retrieval, but the crawler and the
deterministic feature engine must stay light.

**Decision.**
- **Optional extra.** `pip install 'geoptimiser[semantic]'` adds `sentence-transformers`
  (which brings PyTorch). The base dependency set (`pydantic`) and CI (`.[dev]`) are
  unchanged. `import geoptimiser.retrieval` never imports the heavy stack (tested); the
  model is imported and loaded lazily, once per provider.
- **Provider.** `SentenceTransformerEmbedder` implements the existing `EmbeddingProvider`
  protocol. Default model `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions),
  configurable (`model_id`, `revision`, `device`, `batch_size`, `normalize`,
  `max_seq_length`, `local_files_only`). Inference is local; documents are encoded in
  batches; `trust_remote_code` is always false. A Hub model is resolved with
  `huggingface_hub.snapshot_download` (heavy ONNX/OpenVINO variants excluded) so the exact
  **commit hash** is known and recorded; pinning a 40-character `revision` makes a
  different resolution an error. A local model directory is identified by a content hash.
- **Identity and compatibility.** Providers may expose an `EmbeddingDescriptor`: provider
  name and version, model id, revision, dimensions, `normalized`, similarity (`cosine`),
  max sequence length and library versions (recorded, not compared). The descriptor's
  compatibility key is stored on every `DenseIndex` and re-checked at every query: a
  swapped model, a different revision or normalisation setting, or a query vector of the
  wrong width raises `EmbeddingIncompatible`. Indexes can be saved and loaded; loading
  refuses another model or another chunk set. The index always L2-normalises, so
  similarity is exact cosine whatever the provider returns. `RetrievalComparison` gains an
  additive `embedder_descriptor`; the existing `embedder` dict is unchanged.
- **No silent fallback.** `build_embedder`/`build_retriever` (settings in
  `configs/retrieval.json`) return the configured provider or raise
  `EmbeddingUnavailable` (extra missing, weights unobtainable, loader failure). The
  hashing double is refused unless `allow_test_embedder=True`, and the semantic path builds
  the retriever with `require_semantic=True`. A failing retrieval during diagnosis still
  degrades to page leads **with a note** (ADR-0020); it never substitutes another embedder.
- **Tests.** Unit tests inject a fake loader/model and need neither the extra nor the
  network. Real-model tests are marked `semantic` and **skip** (they are not reported as
  passing) when the extra or the weights are missing. A paraphrase probe
  (`tests/retrieval/semantic`) pairs queries with pages that share no content word (checked
  by an always-run test), plus lexical-control queries where BM25 should do well, so
  semantic behaviour is not confused with word overlap. The earlier plumbing fixture stays
  separate. `python -m tests.retrieval.semantic.run_benchmark` reruns the comparison with
  the real model.

**Limitations and honesty.** A semantic embedder is not guaranteed to improve ranking; it
can rank a loosely related page above an exact lexical match, and the comparison reports
such cases rather than hiding them. The probe is small and constructed to favour semantic
matching; the control set is small and constructed to favour lexical matching. Neither is
a real-world benchmark and `real_world_claim` stays false. First use downloads about
90 MB of weights from the Hugging Face Hub; unpinned revisions are not reproducible over
time. Embedding is CPU-bound in-process and single-threaded per call. Query and document
text share one encoding (no asymmetric prefixes), which suits MiniLM but not every model.

**Alternatives considered:** *Embeddings via a hosted API* (rejected: sends page text off
machine, needs credentials, and the task asks for local inference). *ONNX/fastembed*
(not requested; would be a second provider to validate). *Making the extra mandatory*
(rejected: burdens users of the crawler and feature engine). *Falling back to the hashing
embedder when the model is missing* (rejected: it would present word overlap as semantics).

## ADR-0023 — A bounded LangGraph agent over the existing pipeline (Day 5, Task 1)

**Status:** Accepted (proposed by implementation; awaiting review). Adds an optional
dependency extra, like ADR-0022; the base install and default CI matrix are unchanged.

**Context.** Roadmap stage 11 calls for a bounded ReAct workflow. The deterministic audit,
retrieval, diagnosis and recommendation components exist and must stay usable alone.

**Decision.**
- **One graph, existing components.** `inspect -> decide <-> act -> finalize` (LangGraph).
  The agent only chooses among six allowlisted tools that wrap existing functions
  (`Diagnosis`, `Retriever`, `passage_evidence`, `validate_diagnosis`, `TemplateGenerator`,
  `validate_recommendations`); nothing is re-implemented. No shell, code, file or network
  tools exist. Detail and contracts are in `docs/AGENT.md`.
- **Protocol: JSON actions, not provider tool-calling.** The model returns one JSON object
  per turn, parsed and validated by us. Free OpenRouter models differ in native
  tool-calling quality, and this keeps the tool contract, validation and fake-model tests
  provider-independent. LangChain is used only as the OpenAI-compatible client.
- **Backend.** `OpenRouterModel` (`langchain-openai`, base URL
  `https://openrouter.ai/api/v1`), default `nvidia/nemotron-3-ultra-550b-a55b:free`, all in
  `configs/agent.json`. The key comes from `OPENROUTER_API_KEY` at construction, is held only
  in the private client, and is excluded from reprs, errors, logs and traces. Client-level
  retries are off; the agent owns a bounded policy (transient errors only). **No fallback**
  model or provider, ever.
- **Control in code, not prompts.** The iteration budget counts model calls; invalid
  decisions, unauthorized tools, bad arguments and repeated successful calls are rejected
  before execution; tools run under a timeout; only transient failures are retried within
  fixed bounds. Website text is delivered as wrapped data, and cannot alter permissions or
  routing because those never depend on it.
- **Honest outcomes.** `finalize` independently re-validates evidence provenance/grounding
  and the recommendations. Status is `completed`, `incomplete` or `failed` from that
  validation and the run's limits; a model that says "done" cannot produce `completed`.
- **State.** A `TypedDict` of serialisable data; live objects stay in `AgentRuntime`.
  Checkpointing is optional (any LangGraph checkpointer can be passed). No SQLite, LangSmith
  or other persistence/observability dependency is added; logs are structured JSON lines
  without content or secrets, and `agent_trace.json` records the steps.
- **Retrieval only on demand.** The prompt says not to retrieve when evidence suffices;
  `retrieve_passages` is registered only if a retriever exists, is scoped to the pages the
  finding affects, and keeps only passages that reproduce their source text.
- **Dependencies.** Extra `agent = [langgraph>=1.0,<2, langchain-openai>=1.0,<2]`
  (verified with langgraph 1.2.14, langchain-openai 1.7.1). Importing `geoptimiser.agent`
  imports neither. A separate CI job installs the extra; the default matrix does not.

**Limitations.** The agent has been exercised only with scripted fake models and one
LangChain client constructed offline; it has **not** been run against the live OpenRouter
model, so the real model's adherence to the JSON protocol is unmeasured (the system
fails closed if it does not). The free model may be rate-limited. Recommendation quality is
that of the deterministic templates; the agent only sequences them. A single model call per
step with no streaming. Tool timeouts abandon, not kill, a worker thread (tools are local
and short). No multi-agent orchestration, fine-tuning, API or UI.

**Alternatives considered:** *Native tool-calling via `bind_tools`* (rejected for now, see
above). *A pure-Python loop without LangGraph* (rejected: LangGraph was requested and
provides the optional checkpointing and a visible graph). *Letting the model decide when it
is done* (rejected: validated outcomes only). *LangSmith/SQLite persistence* (rejected: not
needed yet).

## ADR-0024 — Local-first application layer (Day 6)

**Status:** Accepted (proposed by implementation; awaiting review). Adds optional extras
(`api`); the base install, crawler and audit engine remain dependency-light.

**Context.** The pipeline stages exist but are separate CLIs. Day 6 needs one usable local
flow from URL to a persisted, shareable report, without weakening the crawler's defences.

**Decisions.**
- **A service layer, not a framework.** `geoptimiser.app` has no web dependency: models,
  SQLite store, pipeline, report, comparison, job runner and `AuditService` are plain
  Python and are tested without FastAPI. Only `api.py` imports FastAPI (extra `api`:
  `fastapi`, `uvicorn`). The UI is three static files served by the API, with no build step
  or JS framework; it inserts values as text nodes.
- **Orchestration by composition.** `PipelineRun` calls the existing functions
  (`Crawler`+`SafeFetcher`, `extract_all`, `run_audit`, `chunk_documents`, `Retriever` /
  `build_retriever`, `diagnose`, `TemplateGenerator`, `run_agent`, `validate_*`). Stages
  are critical or optional; the final status is computed from stage outcomes, so a failed
  or partial run can never be `completed`.
- **Semantic retrieval and the agent are explicit options.** Requesting either and not
  getting it yields `incomplete` with a category, never a silent fallback (consistent with
  ADR-0022 and ADR-0023). Deterministic results are produced regardless.
- **SQLite for metadata, files for artifacts.** WAL, per-call connections, `BEGIN
  IMMEDIATE`, `user_version` migrations that refuse newer schemas, an artifact table with
  hashes. IDs are derived from (URL, time, per-URL sequence) inside the creating
  transaction: reproducible and collision-free. A bounded in-process worker pool replaces an
  external queue. Unfinished audits are marked `interrupted` at startup rather than resumed
  (resuming a crawl safely would need checkpointing of the crawler, which does not exist).
- **Security.** Loopback bind enforced by the CLI, `Host` allow-list, no CORS, no auth
  claimed. The API exposes no fetch, proxy or file endpoint; ids are strictly validated and
  files are reached only via the artifact table with containment checks. Target validation
  is an early filter; SSRF defence stays solely in `SafeFetcher` (unchanged), and users
  cannot alter crawl policy, only bounded `max_pages`, `max_depth`, retrieval and agent
  choice.
- **Fetch timings (additive).** `FetchRecord.timings` records DNS, connect, TLS, time to
  response headers, response time and total. The pinned connections time TCP and TLS
  themselves; any transport that cannot expose a step reports it as `not_measured` with a
  reason. TTFB is defined as "request sent until headers parsed" because `http.client` does
  not expose the first byte.
- **Comparison is descriptive.** Same normalized URL, both completed, earlier first, same
  catalog/scoring versions (else rejected); differing components, crawl limits, page sets or
  options are surfaced as caveats and mark the result `reduced`. "Recommendation status"
  states only whether the related features still fail in the later audit.
- **Reports** are built from produced artifacts only (JSON and escaped, script-free HTML)
  and carry the disclaimer that no outcome in AI search is promised.

**Limitations.** No authentication, authorization, multi-user isolation, TLS termination or
deployment story; one machine; no resume; scores reflect only crawled pages and implemented
features; the comparison cannot establish cause; wall-clock timings include local
scheduling; the build sandbox has no DNS, so real-network behaviour is covered by the
crawler's existing mock-server/TLS tests and the new mock-site pipeline tests, not by an
audit of a live site.

**Alternatives considered:** *Flask/other framework* (FastAPI gives validated models and
OpenAPI with little code). *PostgreSQL or a queue* (excluded by scope). *A SPA build chain*
(unneeded weight). *Letting the API accept crawl parameters like robots or IP policy*
(rejected: it would let a client weaken the SSRF defences). *Storing artifacts in SQLite*
(rejected: large and already file-based).

## ADR-0025 — Day 7 validation: fixes, evaluation honesty and the demo

**Status:** Accepted (proposed by implementation; awaiting review).

**Context.** After Day 6 the integrated application needed end-to-end validation, a
reproducible demonstration and honest documentation, without new product features.

**Decisions.**
- **Validate through the real interfaces with a deterministic local mock site.** New tests
  (`tests/app/test_e2e_validation.py`, `test_security.py`, additions to `test_api.py`)
  cover provenance end to end, status transitions, failure categories (DNS, TLS, timeout,
  connection, redirect loops and attacks, empty/malformed/oversized sites, byte budgets),
  persistence and report failures, interrupted runs, evidence corruption, cross-audit
  chunks, agent scenarios through the pipeline and secret handling.
- **Fixes, each reproduced by a test that failed beforehand:**
  1. `run_pipeline` now guards against unexpected errors (for example a database failure
     between stages) and records the audit as `failed`/`internal_error` instead of leaving
     it `running`.
  2. The report is rendered fully before anything is written, and a failure removes any
     partial `report.json`/`report.html`, so a failed audit can never ship a report that
     says `completed`.
  3. `AuditStore` closes its handle and reports a corrupt or non-SQLite file as a
     `StoreError` without the path.
  4. Truncated bodies and documents are counted and disclosed in the report's crawl summary
     and limitations (previously silent).
  5. The HTML report shows the brand name (needed to label demo data).
- **Evaluation stays honest.** The benchmark runner gained `--allow-test-embedder` so the
  deterministic parts can be reproduced offline; its output is labelled non-semantic. No
  data set was enlarged to improve displayed scores, no metric definition changed, and the
  real-model results are reported as not obtained. Fixtures, probes and controls stay
  separate.
- **A bundled demo (`python -m geoptimiser.demo`).** A mock site served from memory on
  loopback, the real `SafeFetcher` with DNS and the TCP connection redirected (as in the
  tests), a rule-based fake model, two audits and a comparison. Results are labelled demo
  data (brand `… (DEMO DATA)`, summary header). It needs no key, no network and no
  download; the agent step runs only when the `agent` extra is installed.
- **Documentation does not claim more than exists:** no authentication, isolation or
  deployment readiness; hosting is deliberately undecided
  (`docs/DEPLOYMENT_REQUIREMENTS.md`).

**Not done / known gaps.** Real-model embedding and OpenRouter runs; real-network audit;
multi-process safety; auth; resuming interrupted audits.

**Alternatives considered:** *Enlarging the synthetic sets* (rejected: it would inflate
scores without adding evidence). *Hiding the missing real-model results* (rejected).
*A hosted demo* (out of scope; hosting undecided).

## ADR-0026 — Static frontend on GitHub Pages, backend local

**Status:** Accepted (proposed by implementation; awaiting review). Nothing is deployed yet.

**Decision.**
- The existing UI is exported as static files rather than rebuilt: `static_export` copies
  `app.js` and `style.css` unchanged, rewrites `/ui/...` to relative paths, and writes
  `config.js`, `CNAME`, `.nojekyll` and a CSP meta tag. One source, two delivery paths
  (backend-served and Pages).
- The API base is runtime configuration in `config.js` (`""` = same origin, so local use is
  unchanged). The base is validated as a bare origin (https; http only for localhost) before
  it reaches the CSP or `config.js`; the CSP `connect-src` allows `'self'` and that origin
  only. Requests omit credentials.
- Cross-origin access is an explicit backend opt-in: `AppConfig.cors_origins` /
  `serve --cors-origin`, exact validated origins, `GET`/`POST`, no credentials, absent by
  default. The `Host` allow-list is unchanged and extended only by `--allowed-host`.
- Deployment is a least-privilege GitHub Actions workflow (read-only contents; `pages` and
  `id-token` write only on the deploy job), triggered by pushes to `main` touching the UI
  and by manual dispatch. It needs no secrets; the API URL is a public repository variable
  with a default.
- Hosting stays split: Pages for static files only; backend, data and models stay on the
  operator's machine. The tunnel is a later, separate step.

**Consequences.** An unauthenticated API reachable through a tunnel is public; this is
documented with mitigations (demo-only tunnel, throw-away data, Cloudflare Access) in
`docs/DEPLOY_FRONTEND.md`. A meta CSP cannot express `frame-ancestors`. Safari may block an
HTTPS page calling an `http://localhost` backend.

**Alternatives considered:** *A separate frontend project/build chain* (rejected: no build
step is needed). *Serving the UI from the tunnel only* (rejected by the requirement to host
on Pages). *Wildcard CORS* (rejected). *Cookies/session auth* (not implemented; out of
scope).

## ADR-0027 — Incomplete evidence is `not_measured`, per check (validation, A1/A2/A5/B1)

**Status:** Accepted (proposed by implementation; awaiting review).

**Context.** The validation audit reproduced that a response cut at the 2 MB crawl limit
produced confirmed-looking failures for a missing title, description, canonical and text,
a "fix the JSON syntax" recommendation for a JSON-LD block that was merely cut, a pass for
a canonical whose target was never crawled and a failure for one that timed out. An
unreadable stored robots.txt was treated as allow-all.

**Decision.**
- Each content check declares in `features/evidence.py` what an incomplete document can
  still prove (`head`, `head_violation`, `presence`, `violation`, `first`, `complete`).
  The engine downgrades anything the evidence cannot support to `not_measured` with an
  explanation naming the cause; conclusive results are kept. A registry test fails if a
  new content check declares no policy.
- The extractor records `head_complete`, per-block JSON-LD error causes
  (`syntax_error`, `unterminated`, `size_limit`, `nesting_limit`), an unterminated title
  and render signals (script/mount-point/noscript facts). `html-extractor:3`; old
  documents still load and mean "unknown".
- F061 judges JSON-LD by cause. F012 distinguishes not crawled / fetch error /
  access-or-server status (`not_measured`) from a 404/410-class error (`fail`). F004 treats
  an unreadable or cut robots.txt as not measured. Graph checks (F009/F010/F072) do not
  conclude while another page's link list is incomplete.
- Interstitial pages (configurable phrase list) make all content checks `not_measured`.
  A client-rendered shell does **not** change a status (the claim is about the fetched
  HTML) but adds an explicit limitation and suppresses combined cross-feature findings
  for that page. JavaScript rendering is not added (F108 stays planned).

**Consequences.** Fewer false defects on large or script-built pages; lower unit
coverage on truncated crawls, which is the truth. The policy lists are heuristics with
unknown recall.

## ADR-0028 — Owner-controlled settings are notices, not defects (validation, B4)

**Status:** Accepted (proposed by implementation; awaiting review).

**Decision.** F004 (blocked crawlers), F005/F006 (noindex) and F030 (snippet limits) are
`intent_dependent` catalog features: they emit `warning` ("confirm intent"), are unscored,
and raise a *notice* finding at low confidence. Severity is `low`, `medium` on the entry
page. Their previous base severity was `high` and a failure.

**Consequences.** A deliberate noindex or GPTBot block no longer lowers a score or reads
as a high-severity defect; an accidental site-wide noindex is still surfaced (entry page
=> medium, listed in findings) but no longer moves the aggregate. If evidence later shows
accidental directives are common, scoring them again is a catalog change.

## ADR-0029 — What contributes to a score, and when a score may be shown (validation, A3/A4)

**Status:** Accepted (proposed by implementation; awaiting review).

**Decision.**
- `features/contribution.py`: features that cannot discriminate under the crawl
  configuration (F009 always for a link-discovered crawl, F072 at minimum <= 1, F010 when
  crawl depth <= limit) are excluded from the aggregate with a stated reason; results that
  only repeat another feature's result on the same URL (F072/F009, F059/F052's missing
  main, F069/F046-F048-F049) count once. Everything stays visible; findings fold the
  repeated failure into the primary finding.
- F015 is `not_applicable` for unredirected pages (as F016); F018 inspects linked URLs
  because the crawler never fetches query URLs.
- `GroupScore` gains `reported_score`, `status` and `withheld_reason`; the HTML report,
  UI and comparison show `reported_score` only. The 0.5 coverage threshold is unchanged.
- `CATALOG_VERSION` 2, `SCORING_VERSION` 2, `REPORT_VERSION` 2: scores from before and
  after are not comparable (the comparison service already refuses differing versions).

**Consequences.** Typical scores fall slightly because free passes disappear; the overall
headline is capped near 0.56 coverage while 39 scored features are unimplemented, so it is
often withheld. Alternatives rejected: lowering the threshold to keep more scores
reportable (arbitrary), or deleting the redundant features (loses diagnostics).

## ADR-0030 — A repeatable validation harness; an honest corpus (validation, section 7)

**Status:** Accepted (proposed by implementation; awaiting review).

**Decision.** `geoptimiser.validation` runs declared fixtures (mock site -> real crawler
... -> recommendations) and compares them with pre-written expectations; `matrix` derives
the 120-feature register from the catalog and code plus hand-written judgments with a
completeness test; `corpus` evaluates features against labelled snapshots with
precision/recall (undefined, not zero, on empty denominators) and Wilson intervals. The
shipped corpus is repository-local and oracle-labelled and says so; no real-world result
is claimed because none could be collected.

**Consequences.** Regressions in measurement semantics fail CI. Metrics describe
constructed cases only. The external-source column is unverified until primary pages are
read.

## ADR-0031 — Three explicit classifications per feature; an application-pipeline level

**Status:** Accepted (proposed by implementation, 2026-11-01; awaiting review).

**Decision.** Every feature carries three independent labels, generated by
`python -m geoptimiser.validation.matrix --write` and shipped as
`src/geoptimiser/validation/feature_levels.json`:
- implementation level: IMPLEMENTED, PARTIAL, PLANNED, UNAVAILABLE, NOT_VERIFIABLE;
- validation level (highest reached): NOT_TESTED, UNIT_TESTED, FIXTURE_VALIDATED,
  PIPELINE_VALIDATED, REAL_PAGE_VALIDATED, OUTCOME_VALIDATED;
- disposition: RETAIN, REVISE, INFORMATIONAL_ONLY, REMOVE, INVESTIGATE.

PIPELINE_VALIDATED means the fixture expectations also hold when the fixture is run through
`AuditService` and the HTTP API (`tests/validation/test_app_pipeline.py`), not only through
the crawl-extract-feature harness. The API's `GET /api/v1/catalog` returns these labels so
the UI never computes or invents them.

**Consequences.** Every fixture-validated feature is also pipeline-validated today (35).
REAL_PAGE_VALIDATED and OUTCOME_VALIDATED stay at 0 until a labelled real-world corpus and
outcome data exist; nothing in the code can promote a feature there. Alternative rejected:
one combined status (it hid "implemented but unvalidated").

## ADR-0032 — Catalog version 3: F110 implemented, F001 v2, F070 v2

**Status:** Accepted (proposed by implementation, 2026-11-01; awaiting review).

**Decision.**
- **F110 (HTTPS and HSTS)** is implemented from the recorded fetch: plain http fails; https
  without a usable `Strict-Transport-Security` header fails; `max-age=0`, a missing or
  invalid value, or a duplicated directive fails. It is informational and unscored. Basis:
  RFC 6797 (source S14, read at the primary source).
- **F001 v2:** HTTP 429, and 503 with `Retry-After`, are `not_measured`: the server told
  the crawler to slow down, which says nothing about the page.
- **F070 v2:** compares distinct structured-data values, at most 200; with more and none
  absent it is `not_measured`, never `pass` (security finding, see ADR-0034).
- `CATALOG_VERSION` 3. The comparison service refuses to compare audits across catalog
  versions, so a 429 page measured before and after cannot look like an improvement.

**Consequences.** Fixtures `k1_transport_security` and `e1_http_status` pin the behaviour.
Alternatives rejected: scoring F110 (no evidence that HSTS affects answer engines); treating
every 5xx as not measured (a persistent 500 is a real defect).

## ADR-0033 — Redesigned local UI (vanilla JavaScript)

**Status:** Accepted (proposed by implementation, 2026-11-01; awaiting review).

**Decision.** The bundled UI was rewritten without a framework or build step: hash routes
(new audit, audits, audit tabs for overview, features, findings, recommendations, crawl,
retrieval, report and compare, the feature catalog, compare); a light neutral canvas with
a deep teal accent; a 120-cell measurement ledger as the overview's main element; DOM built
only from text nodes (no `innerHTML`); a render-generation counter that drops stale
responses; polling that backs off from 1.5 s to 8 s; `credentials: "omit"`. Fonts (Hanken
Grotesk, JetBrains Mono; SIL OFL) are self-hosted, so the strict CSP (`default-src 'self'`)
is unchanged. Two read-only endpoints feed it: `GET /api/v1/audits/{id}/features` and
`GET /api/v1/catalog`.

**Consequences.** Scores appear only as the backend's `reported_score`; a withheld score
shows its reason. A browser test (`tests/e2e/browser_e2e.py`) checks that the UI and the
API agree. Alternatives rejected: React or another framework (adds a toolchain and a supply
chain for a local tool), CDN fonts (would weaken the CSP and leak requests).

## ADR-0034 — Security audit run 1 remediation

**Status:** Accepted (proposed by implementation, 2026-11-01; awaiting review).

**Decision.** Fix the four confirmed low-severity findings and three of the four leads
from the Cloudflare `security-audit` run on `fce9c1d`, each with a regression test:
one URL parser decides crawl scope (refuse `\` and `%` in the authority, IDNA ASCII hosts,
first-hop scope check in the fetcher); an invalid discovered URL is skipped, not fatal;
F070 is bounded; the claim screen only reads Geoptimiser's own text; robots parsing is
linear; a rejected submission leaves no row; agent audits are limited per hour
(`max_agent_audits_per_hour`, default 20, `0` disables them). Also done: full-match id
checks, IPv6 `Host` parsing, atomic comparison writes, a `<meta>` CSP in the HTML report,
escaping `<` in agent tool results, `min_length=1` for `finding_ids`, linear
`split_sections`.

**Consequences.** Details and the remaining risks (no authentication, unpinned semantic
model, unpinned Actions, no stage deadline, no disk quota) are in
`docs/project/SECURITY_REVIEW.md`. Alternative rejected: adding authentication now (a
product decision outside this assignment's scope; the API stays loopback-only by default).
