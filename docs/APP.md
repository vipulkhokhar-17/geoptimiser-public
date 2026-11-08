# Local application (Day 6)

A local-first service that runs the whole existing pipeline for one URL and keeps the
result. It adds orchestration, persistence, an API, a small UI, reports and comparison; it
re-implements none of the crawler, extractor, feature engine, retrieval, diagnosis,
recommendations or agent. Decisions are in ADR-0024.

## Pipeline and status

`validate -> crawl -> extract -> features -> chunk -> retrieval -> diagnose -> recommend ->
[agent] -> validate_output -> report`. Every stage is timed, logged, stored and (when it
produces files) registered. Artifacts live in `<data-dir>/audits/<audit_id>/`:
`fetches.jsonl`, `bodies/`, `extraction/`, `features/`, `chunks.jsonl`, `findings.json`,
`recommendations.json`, `agent_trace.json`, `report.json`, `report.html`.

| Status | Meaning |
|---|---|
| `queued` / `running` | In the local queue / executing (the current stage is exposed) |
| `completed` | Every requested stage succeeded and the outputs passed final validation |
| `incomplete` | Deterministic results exist, but an optional stage failed or was unavailable (semantic retrieval, agent, chunking) or the crawl stopped early (time/byte budget) |
| `failed` | A critical stage failed (crawl, extraction, features, diagnosis, recommendations, final validation, report) |
| `interrupted` | The service stopped while the audit was queued or running; marked on the next start |

Partial artifacts are kept for failed and interrupted audits, and a report describing
exactly what was produced is written whenever possible. Findings and recommendations are
served only when final validation passed (every finding and recommendation still resolves
to existing evidence). The deterministic audit never depends on the model: with
`use_agent=false` (the default) no key, LangGraph or network model is touched; if the agent
is requested and fails, is incomplete or is unavailable, the audit is `incomplete`, the
agent block says so, and the deterministic results are still reported.

Error categories: `invalid_target`, `blocked_target`, `dns`, `connection`, `tls`, `timeout`,
`http_error`, `no_content`, `crawl_error`, `extraction_error`, `feature_error`,
`retrieval_unavailable`, `diagnosis_error`, `validation_failed`, `agent_unavailable`,
`agent_failed`, `agent_incomplete`, `interrupted`, `internal_error`. Messages are fixed,
safe sentences; exception text is never exposed.

## Persistence

SQLite (`<data-dir>/geoptimiser.db`, WAL, foreign keys, `PRAGMA user_version` migrations; a
newer schema is refused). Tables: `audits` (id, target, normalized URL, status, stage,
timestamps, options, pipeline versions, summary, artifact directory), `stages`,
`artifacts` (name, relative path, SHA-256, size) and `comparisons`. Writes are short
`BEGIN IMMEDIATE` transactions on a connection per call. Audit ids are
`aud_<20 hex>` derived from (normalized URL, creation time, per-URL sequence), so they are
reproducible given the same inputs and unique per submission. A restart keeps everything;
audits left queued/running become `interrupted` (they are not resumed).

## API (`/api/v1`)

| Method and path | Result |
|---|---|
| `GET /health`, `GET /ready` | liveness; readiness (database, data directory, workers) |
| `POST /audits` | `202` with the audit; body `{url, brand_name?, authorization_confirmed, options{max_pages, max_depth, retrieval: off|lexical|semantic, use_agent}}` |
| `GET /audits`, `GET /audits/{id}` | list; status, stage records, summary, versions |
| `GET /audits/{id}/findings` | findings with evidence, affected URLs, measured values (`409` if unavailable) |
| `GET /audits/{id}/recommendations` | validated recommendations (`409` if unavailable) |
| `GET /audits/{id}/report`, `/report.html` | full report; `?download=true` for an attachment |
| `GET /audits/{id}/features` | every feature's stored results for this audit (at most 100 per feature, 5 evidence items, 500-character snippets) with its score entry (`409` if the audit produced none) |
| `GET /catalog` | the 120 catalog definitions, threshold defaults and each feature's implementation level, validation level and disposition |
| `POST /comparisons`, `GET /comparisons/{id}` | before/after comparison |

Errors are always `{"error": {"code", "message", "request_id"}}` (`400` bad id, `404`
unknown, `409` unavailable/incompatible, `413` large body, `422` invalid, `429` agent audit
rate limit, `503` queue full).
Validation errors list field names and reasons but never echo submitted values.

## Security model

* **Local-first, no authentication.** The CLI is hard-bound to IPv4 loopback
  `127.0.0.1`; it exposes no host override or remote-bind option. The `Host` header must
  be local (guards DNS rebinding), and configured CORS origins are also restricted to
  loopback. There is no multi-user isolation: anyone who can reach the port can read every
  audit. Do not expose it.
* **Agent spend is capped server-side.** At most `max_agent_audits_per_hour` agent audits
  (default 20; `serve --max-agent-audits-per-hour`, `0` forbids them) are accepted per
  hour; more get `429 agent_rate_limited`. A submission refused because the queue is full
  leaves no stored audit.
* **No fetch proxy, no file access, no code execution.** The API accepts a URL and bounded
  options, not request details. Reading is by audit id through the artifact table, with a
  path-containment check. Crawling happens only in the pipeline, through `SafeFetcher`:
  public-IP-only DNS pinning with a re-check of the connected peer, manual redirects,
  scheme/port/credential rules, response and audit budgets, robots.txt and verified TLS.
  Users cannot change any of these; limits come from server config and are capped.
* Submission requires an explicit authorization attestation (a record of intent, not a
  verified ownership check). Local-looking hosts, IP literals, credentials and non-default
  ports are rejected up front; the crawler enforces the real policy at fetch time.
* **Secrets.** `OPENROUTER_API_KEY` is read only from the environment, only when the agent
  is requested, and never stored, logged or put in a report. Logs are JSON lines with
  codes, counts and timings, not page content.
* **UI.** Fixed static files (HTML, CSS, JavaScript, two self-hosted OFL fonts and their
  licence), a strict CSP (`script-src 'self'`), values inserted as text nodes only. The HTML report is escaped, has no scripts, and is served with
  `default-src 'none'`.

## Network measurements

Each fetch records DNS, TCP connect, TLS handshake, time to response headers, response time
(final exchange) and total time (all hops), plus redirects, size and the categorized
failure. A step the transport cannot expose (for example a custom connection factory, an IP
literal, plain HTTP for TLS) is `not_measured` with a reason, never 0. The report
aggregates them (count measured / not measured, p50, p95, max).

## Report version 2 (scores, notices, gaps)

`report_version` 2 (additive; version-1 reports still load and render by the same rule):
every score group has `reported_score` (the score only if it is reportable, otherwise
`null`), `status` and `withheld_reason`; the HTML report, the UI and the comparison show
`reported_score` only, so a category below the coverage minimum reads "withheld (m/n
features measured)" with the reason. Each finding has `kind` (`defect`, or `notice` for an
owner-controlled setting to confirm) and `contributes_to_score`; each measurement row
carries the check's explanation. `measurement_gaps` lists checks that could not conclude
(truncated response, interstitial, unreachable canonical target, ...) with the reason;
these are limits of the measurement, not findings. `scores.excluded_features` lists
features kept out of the aggregate and why. Scores from reports of different
`catalog_version`/`scoring_version` cannot be compared. Rules: `docs/validation/VALIDATION_POLICY.md`.

## Before/after comparison

Two **completed** audits of the same normalized URL (earlier first, same catalog and
scoring versions). Reported: overall, pillar and category score changes, coverage changes,
changed features, new/resolved/persistent findings with affected-URL changes, and for each
earlier recommendation whether its features still fail in the later audit
(`no_longer_failing`, `still_failing`, `not_measured`). Caveats list differing pipeline
components, crawl limits or options, differing page sets, differing stop reasons and
coverage differences, and mark the comparison `reduced`. A measured difference is **not** a
causal claim: other things change between audits.

## Run

```bash
pip install -e '.[api]'            # add '.[agent]' for the optional agent, '.[semantic]' for embeddings
python -m geoptimiser.app serve --data-dir data      # UI at http://127.0.0.1:8000
python -m geoptimiser.app audit https://example.com --confirm-authorized
python -m geoptimiser.app list
python -m geoptimiser.app compare aud_... aud_...
```

## Limitations

Single machine, one worker by default, no authentication or user isolation, no retries or
resume of interrupted audits, crawling is bounded (default 10 pages) so scores describe the
pages reached, scores cover only implemented catalog features, timing is wall-clock on the
audit host, and the sandbox this was built in has no outbound DNS, so the real-network path
was verified with a local mock site only.
