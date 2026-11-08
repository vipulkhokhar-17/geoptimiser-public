# Security review

Date: 2026-11-01 · Reviewed commit: `fce9c1d` · Method: Cloudflare `security-audit` skill
(commit `c1c8a8c1471069fb0e188eeaff69b8e8db6564a8`), run 1, standard profile.

This page summarises the audit, what was changed because of it, and what is still open.
The full run artifacts (`REPORT.md`, `FINDINGS-DETAIL.md`, `NEEDS-VALIDATION.md`,
`findings.json`, `coverage-ledger.json`, `architecture.md`, `run-metadata.json`) were
written outside the repository, as the skill requires, and are not committed.

Related: [ARCHITECTURE.md §13](ARCHITECTURE.md#13-security-architecture) (trust
boundaries), [../SECURITY.md](../SECURITY.md) (operator-facing security notes).

## 1. How the audit ran

* **Scope:** `src/geoptimiser`, `configs`, `.github/workflows`, `pyproject.toml` and the UI.
* **Execution:** source review plus sandboxed local reproduction. Target code ran only in
  an OS sandbox (user, mount, network and PID namespaces with loopback only, an empty
  environment, a read-only target, resource limits and a wall-clock timeout). No deployed
  endpoint, production database, model provider or live website was contacted.
* **Budget:** 46 agent runs (reconnaissance, 21 hunter runs over 4 waves, critics, and
  independent verifiers in Phases 3 and 5). The budget was raised during the run, each
  time with a recorded reason.
* **Coverage:** 17 ledger units: 9 covered with no finding, 7 that produced candidates,
  and 1 deferred (chunking cost in `src/geoptimiser/chunking`) because the budget had to
  fund verification. **The run does not claim the repository is exhausted.**
* **Recorded deviation:** in waves 1–2 several hunters returned results wrapped in prose.
  The skill discards those unread, so their units were reassigned. From wave 3 on,
  results were returned as a file and parsed by trusted code.

## 2. Findings and what was done

All confirmed findings are **low** severity. Every new test was also run against the
unmodified code at `fce9c1d`. Each test named for findings 1–4 and 6–7 and for the
hardening items fails there and passes now. Two tests pass on both and are behaviour
guards, not proof of the fix: the robots-parse timing test (20,000 groups parse in well
under 2 s with the old parser too; the audit's memory amplification was never
independently reproduced, which is why it stayed "needs validation"), and the
end-to-end backslash-link crawl test (the mock site's loopback resolver does not show the
off-site host; the unit tests on `normalize_url` and the first-hop check do).

| # | Finding (status) | Fix | Regression test |
|---|---|---|---|
| 1 | A link with a backslash (`http://evil.test\.site.test/`) passed the scope check under `urlsplit`, but the fetcher's WHATWG parser read the host as `evil.test`, so the crawler fetched an unrelated public host (confirmed) | `normalize_url` refuses `\` and `%` in the authority, converts the host to IDNA ASCII and refuses any character outside `[a-z0-9.-]`; `SafeFetcher.fetch` checks `host_allowed` on the first hop, not only on redirects; `_discover` decides scope on the canonical URL | `tests/crawler/test_audit_regressions.py` (ambiguous hosts, IDNA, out-of-scope first hop) |
| 2 | One unparseable discovered link aborted the whole audit with `internal_error` (confirmed) | the crawler records such a URL as skipped with reason `invalid_url` and continues | `test_uncanonicalizable_url_is_skipped_not_fatal`, `test_backslash_link_is_not_followed_and_the_crawl_completes` |
| 3 | F070 compared every JSON-LD value with the visible text, so a page with many entities cost entities × text CPU (45 s measured on one page) with no deadline (confirmed) | F070 (version 2) compares distinct values only, at most 200; if more exist and none of the 200 is absent it reports `not_measured`, never `pass` | `test_f070_examines_a_bounded_number_of_values` |
| 4 | Text from the audited site (URLs like `/save-50%25`, quoted page text) reached the unsupported-claim screen, so valid recommendations were withheld (confirmed) | the screen runs on `authored_text()`, which removes URLs and quoted excerpts; the ungrounded-URL check still runs on the full text | `tests/recommendations/test_claims.py` (two new tests) |
| 5 | robots.txt parsing kept rule references for every group × agent line (needs validation) | `parse_rules` keeps only the groups for our token and `*`, in one linear pass; semantics unchanged | `test_many_user_agent_groups_parse_quickly_and_keep_only_relevant_rules`, existing robots tests |
| 6 | A rejected audit (queue full) still left a durable row (needs validation) | `submit` checks `JobRunner.has_room` before creating the row and deletes a still-queued row with `discard_queued` if the queue fills in between | `test_queue_overflow_is_a_503_and_the_audit_is_not_left_queued` (now asserts no row is listed) |
| 7 | Anyone who can reach the API could run unlimited agent audits on the operator's OpenRouter key (needs validation) | server-side limit `max_agent_audits_per_hour` (default 20, `0` forbids agent audits); excess requests get HTTP 429 `agent_rate_limited` | `test_agent_audits_are_rate_limited_server_side`, `test_agent_rate_limit_zero_forbids_agent_audits` |
| 8 | Unpinned Hugging Face model revision for optional semantic retrieval (needs validation) | **not changed**: it needs the semantic extra and a network to verify; see §4 | — |

Hardening items from the audit's notes that were also done, each with a test:

| Item | Change | Test |
|---|---|---|
| Audit and comparison ids were checked with `re.match` and `$`, which accepts a trailing newline | `fullmatch` | `test_unknown_malformed_and_traversal_ids` |
| A bare `Host: [::1]` was parsed as `[::1]]` and refused | `_host_without_port` | `test_host_header_must_be_local` |
| `write_json_atomic_overwrite` used a fixed temporary name and `exists/unlink`, so concurrent comparisons could fail | unique `mkstemp` file and one `os.replace` | `test_comparison_files_are_replaced_atomically` |
| A downloaded `report.html` had no CSP when opened from disk | the same script-free policy is repeated in a `<meta>` tag | `test_the_whole_flow_from_url_to_persisted_report`, `test_downloaded_report_keeps_a_script_free_policy` |
| Page text could contain `</tool_result>` and close the agent's data block | `<` in tool output is escaped as `<` (still the same JSON) | `test_crawled_text_cannot_close_its_tool_result_block` |
| `generate_recommendations` accepted `finding_ids=[]` and replaced earlier results with nothing | `min_length=1` | `test_generate_recommendations_refuses_an_empty_finding_list` |
| `split_sections` rescanned every remaining line for each unmatched heading (headings × lines) | lookup by line position with bisection; same output | `test_split_sections_is_not_headings_times_lines`, `test_split_sections_keeps_document_order_for_repeated_lines` |

## 3. What held up

The audit found no way past these controls (source review plus sandboxed checks):
resolve-then-pin egress with a peer re-check, covering redirects, IPv4-mapped, NAT64 and
6to4 forms and metadata ranges; TLS verification; streaming byte caps that never trust
`Content-Length`; HTML escaping in the report and text-node-only rendering in the UI;
strict CSPs; artifact-path containment; parameterised SQL; the `Host` allow-list against
DNS rebinding; rejection of cross-site simple requests (JSON-only bodies); the agent's
tool allowlist with validated arguments and a deterministic final status.

## 4. Remaining risk register

| Risk | Why it is open | What reduces it today | Next step |
|---|---|---|---|
| **No authentication on the API** (main structural risk) | design decision for a local-first tool (ADR-0024) | CLI is hard-bound to `127.0.0.1`; no host/remote-bind option; loopback-only CORS; `Host` allow-list; agent rate limit | add authentication before any exposure beyond loopback; do not expose the API as it is |
| Unpinned semantic model revision; pickle weights not excluded | semantic extra not installed in the review environment; needs a network to verify | optional extra, off by default | pin a 40-hex revision in `configs/retrieval.json`, require `model.safetensors`, cache the model per process |
| GitHub Actions not pinned to commit SHAs | would need looking up current SHAs from GitHub, which this session must not contact | workflows only run on the repository's own events | pin `actions/*` to full SHAs |
| No time budget for the features stage or for retrieval | larger design change | per-check caps (F070, `split_sections`), extraction caps and deadlines | add a stage deadline and per-check timing |
| No aggregate disk quota, retention or pruning | accepted in ADR-0007 | per-audit byte budget (50 MB) | data-dir quota, free-space check in readiness, a `prune` command |
| `normalize_target` accepts public suffixes such as `github.io` | needs a public-suffix list | crawl is still bounded and IP-vetted | add a PSL check |
| Repository-host settings (branch protection, Pages environment) | not visible in source | — | owner checks them |
| Chunking unit (`src/geoptimiser/chunking`) not audited | budget | extraction caps bound its input | audit it in run 2 |

The remaining hardening notes in the run's `REPORT.md` §6 (for example verifying artifact
hashes on read, the claims percentage pattern on long digit runs, robots bytes across many
origins) are low value or depend on the items above, and are left for run 2.


## 5. Follow-up release-preparation review (2026-11-08)

This follow-up is a source/configuration review of the repository branch `portfolio/public-release-prep`, not a new penetration test. It addresses selected supply-chain and model-loading items from the initial risk register.

| Item | Change in release-prep branch | Verification still required |
|---|---|---|
| Semantic model revision | Default `all-MiniLM-L6-v2` revision pinned to Hugging Face commit `c9745ed1d9f207416be6d2e6f8de32d1f16199bf`; default config uses the same pin. | Run the optional semantic tests with the actual dependency/model download on the target Mac. |
| Model weight formats | Snapshot download ignores pickle-oriented weight formats; loader requires at least one `.safetensors` file and passes `use_safetensors=True` to the Transformers loader. Remote code remains disabled. | Verify the pinned snapshot's safetensors file is present and loadable in a clean environment. |
| GitHub Actions | Checkout, setup-python, configure-pages, upload-pages-artifact and deploy-pages references are pinned to full commit SHAs. | Review pins periodically and update only after checking upstream releases. |
| Dependency vulnerability audit | CI now audits installed core, dev, agent and API Python dependencies with `pip-audit`. | Review any findings; optional semantic dependencies are not installed by this job. |
| Static frontend publishing | GitHub Pages deployment is opt-in via `GEOPTIMISER_PAGES_ENABLED=true` and requires an explicit HTTPS `GEOPTIMISER_API_BASE`. No default backend URL is injected. | Keep disabled until a secured backend exists; verify the repository variables before enabling. |
| Repository maintenance | Added weekly Dependabot updates for pip and GitHub Actions; improved ignores for local private keys and certificate bundles. | Configure Dependabot alerts and branch protection in repository settings. |
| Release documentation | Reworked README using generated feature-level counts; added root security policy and a public-release checklist. | Choose a license; review branch/tag contents, history metadata and session URLs before publication. |

### Updated residual risks

- The supported CLI is **hard-bound to `127.0.0.1`**; `--host`, `--allow-remote` and `--allowed-host` are not exposed. Configured CORS origins are restricted to localhost/loopback.
- The local API still has **no authentication or multi-user isolation**. Loopback binding is appropriate for this demo; it is not a public deployment control.
- No aggregate data-directory quota, body reference accounting/automatic pruning, full feature/retrieval stage deadline, or public-suffix-list validation has been added in this pass.
- The previous audit did not cover the entire repository/history and left the chunking unit deferred. This follow-up is not proof those areas are clean.
- The full-history Gitleaks workflow now passes on the prep head, scanning 56 reachable commits and reporting no findings after the one exact fingerprint exception for the fake test fixture. Native GitHub secret-scanning, Dependabot-alert and code-scanning-alert states were not available through the repository connector; inspect them in repository settings.
- CI at the earlier head passed the default Python matrix but the agent/API-extra job found an outdated public-CORS expectation. That test has been updated to use loopback origins and the current CI rerun is pending; do not mark CI green until all jobs complete.
- Existing commit metadata includes author email addresses. Preserving history means those metadata remain in the public history; use GitHub's noreply address for future commits if preferred.
