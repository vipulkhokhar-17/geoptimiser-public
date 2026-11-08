# Development guide

How to set up, run, change and check Geoptimiser. For what the parts are, read
[ARCHITECTURE.md](ARCHITECTURE.md); for how an audit runs, [EXECUTION_FLOW.md](EXECUTION_FLOW.md);
for validating features, [FEATURE_VALIDATION_GUIDE.md](FEATURE_VALIDATION_GUIDE.md).
Project rules for AI-assisted work are in `CLAUDE.md` at the repository root.

## 1. Set up

Requirements: Python 3.11 or newer (CI runs 3.11–3.14) and Git.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'               # tests and lint; enough for the core
python -m pip install -e '.[dev,api,agent]'     # also the local app and the agent
```

| Extra | Adds | Needed for |
|---|---|---|
| `dev` | pytest, pytest-cov, ruff | every change |
| `api` | FastAPI, uvicorn | `python -m geoptimiser.app serve`, `tests/app` |
| `agent` | LangGraph, langchain-openai | the optional agent and its tests |
| `semantic` | sentence-transformers (pulls in PyTorch, large) | `retrieval: "semantic"` |
| `web` | httpx, beautifulsoup4, trafilatura, python-dotenv | declared but not imported by `src/` or `tests/` today; `httpx` is what FastAPI's test client needs |

Secrets: copy `.env.example` to `.env` only if you use the agent, and put
`OPENROUTER_API_KEY` there or in your shell. `.env` is git-ignored; never commit it, paste it
into issues or log it. Nothing else needs credentials, and every default test runs offline.

## 2. Run it

```bash
python -m geoptimiser.app serve                          # UI and API on http://127.0.0.1:8000
python -m geoptimiser.app audit https://example.com --confirm-authorized
python -m geoptimiser.app list
python -m geoptimiser.app compare <before_id> <after_id>
python -m geoptimiser.demo --out demo_output              # whole app on a bundled mock site
```

Useful `serve` options: `--no-agent`, `--max-agent-audits-per-hour N` (default 20, `0`
forbids agent audits), `--allowed-host` and `--cors-origin` (only for the documented tunnel
setup), `--allow-remote` (required for any non-loopback bind). The API has **no
authentication**: keep it on loopback. Data goes to `--data-dir` (default
`./data`, git-ignored).

Only audit sites you own or are authorised to audit. Tests and local experiments should use
the mock sites in `tests/` and `tests/validation/fixtures/`, never a real website.

Every stage also has its own command (crawler, extraction, features, chunking, retrieval,
diagnosis, recommendations); see the README.

## 3. Repository layout

```
src/geoptimiser/
  schemas.py          shared Pydantic contracts (FetchRecord, PageDocument, FeatureResult, …)
  crawler/            safe fetcher, URL rules, robots, crawl loop, body store
  extraction/         stdlib HTML parser -> PageDocument
  features/           catalog_data.py (the 120 features), registry, checks/, scoring, findings
  chunking/ retrieval/ diagnosis/ recommendations/ visibility/ benchmark/
  agent/              optional bounded LangGraph agent
  app/                service, store (SQLite), jobs, FastAPI api.py, report, ui/
  validation/         fixture harness, matrix, judgments, sources, corpus, levels
tests/                mirrors src/; tests/validation/fixtures/*/spec.json; tests/e2e/
configs/              generated catalog and scoring exports, retrieval settings
docs/                 ADRs, catalog, validation reports; docs/project/ (this set)
benchmarks/corpus/    the repository-local labelled corpus
```

Generated files — edit the source, then regenerate; never edit them by hand:

| Generated file | Source | Command |
|---|---|---|
| `configs/feature_catalog.json`, `configs/scoring.json`, `docs/FEATURE_CATALOG.md` | `features/catalog_data.py`, scoring | `python -m geoptimiser.features --export` |
| `docs/validation/feature_validation_matrix.csv`, the register in `docs/validation/GEOPTIMISER_FEATURE_AUDIT.md`, `src/geoptimiser/validation/feature_levels.json` | catalog, code, tests, fixtures, `validation/judgments.py`, `validation/sources.py` | `python -m geoptimiser.validation.matrix --write` |

The matrix records test file locations, so run `--write` **after** your last test change;
`test_checked_in_matrix_and_audit_document_are_current` fails otherwise.

## 4. Quality gates

Run all of these before handing work over. CI runs the first three on every pull request,
plus the `tests/agent` and `tests/app` suites with the extras.

```bash
ruff check .
ruff format --check .
python -m pytest
python -m geoptimiser.validation --fixtures tests/validation/fixtures      # every expectation must hold
python -m geoptimiser.validation.matrix --check                             # matrix current and complete
python -m geoptimiser.validation.corpus --manifest benchmarks/corpus/manifest.json
```

Browser end-to-end check (needs Playwright for Python and Chromium; it starts the real
backend against local fixture sites and uses no external network):

```bash
python tests/e2e/browser_e2e.py --python .venv/bin/python --out /tmp/geo-e2e
```

Report exact commands and results. A test that was not run has not passed.

## 5. Making common changes

### Add or change a feature check

1. Edit the feature in `src/geoptimiser/features/catalog_data.py`: method, limits,
   `implementation_status`, severity, remediation text. The remediation text must pass the
   unsupported-claim screen (`test_every_catalog_remediation_is_clean`).
2. Write the check in `src/geoptimiser/features/checks/<area>.py` with
   `@check("Fnnn", requires=..., version=n)`. Bump `version` whenever results can change
   for the same input; the registry refuses a mismatch with the catalog.
3. Return `passed`, `failed`, `not_applicable` or `not_measured`. **Unknown is not a
   failure:** truncated input, a missing fetch or an answer that says nothing about the
   page is `not_measured` (ADR-0027).
4. Add unit tests in `tests/features/` (normal, malformed input, edge cases), and a
   fixture with expectations written **before** you run it (see the validation guide).
5. Update `src/geoptimiser/validation/judgments.py` (claim, sources, false
   positives/negatives, disposition). Cite sources in `validation/sources.py` only after
   reading the primary page.
6. If scores can change, bump `CATALOG_VERSION` (and `EXPECTED_CATALOG_VERSION` in
   `tests/validation/test_matrix.py`) so old and new audits are not compared.
7. Regenerate: `python -m geoptimiser.features --export`, then
   `python -m geoptimiser.validation.matrix --write`.
8. Record a material decision as an ADR in `docs/DECISIONS.md`.

### Change the API

Routes live in `src/geoptimiser/app/api.py`; logic belongs in `service.py`. Every route is
listed in the allowlist test (`test_the_api_has_no_fetch_proxy_or_file_endpoint`), so a new
route fails that test until it is added on purpose. Errors use the `ServiceError`
subclasses and never echo input. Update the API table in
[ARCHITECTURE.md §12](ARCHITECTURE.md#12-api) and `docs/APP.md`.

### Change the UI

The UI is three fixed files plus fonts in `src/geoptimiser/app/ui/` (vanilla JavaScript, no
build step). Rules enforced by tests:

* build DOM only with `el()` and text nodes; the source must not contain `innerHTML`;
* scores come only from `shownScore()`, which reads the backend's `reported_score`;
* no absolute `https://` URLs in `app.js` (the API base comes from `config.js`);
* the CSP is `default-src 'self'`: no inline styles or scripts, no CDNs; bar widths are set
  through the CSSOM;
* a new static file must be added to `_STATIC` in `api.py` and `FILES` in
  `static_export.py`.

Check four viewports (1440×900, 1280×800, 768×1024, 390×844) and run axe or an equivalent
for WCAG AA; then run the browser end-to-end check.

### Change the crawler

Every request goes through `SafeFetcher`. Do not add another HTTP client. Keep these
invariants, each covered by tests in `tests/crawler/`: resolve once and pin; check every
connected peer and redirect hop against the public-address policy and the crawl scope;
never trust `Content-Length`; budgets for bytes, pages, depth and time. A URL is canonical
only after `normalize_url`; anything it refuses is skipped, never guessed.

## 6. Conventions

* Typed, small functions; Pydantic for data crossing module boundaries.
* Raw observations, derived metrics, findings, recommendations and reports are separate
  artifacts with versions, timestamps and audit ids.
* Crawled pages and model output are untrusted data: escape them, do not follow them.
* Tests never touch the network; the live OpenRouter test is opt-in (`GEOPTIMISER_LIVE=1`).
* No secrets or customer data in the repository, logs or reports.
* Do not commit generated audit data (`runs/`, `bodies/`, data directories).
