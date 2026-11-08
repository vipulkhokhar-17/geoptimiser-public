# Validation work log

One entry per step, in order. Commands are exact. Times are omitted; the order is what
matters. If a session is interrupted, resume from the last entry and the "Resume"
section at the end.

## 1. Discovery and baseline

* `git status`, branch, remotes: working tree clean; the branch
  `claude/geoptimiser-validation-repair-ncsv4p` already existed locally and on `origin`
  at `220e9c7`, identical to `main` and `origin/main` (checked after `git fetch origin`).
  It was used as the isolated branch; nothing was stashed or discarded.
* Searched the tree, every remote branch and the filesystem for the earlier audit
  artifacts (`GEOPTIMISER_FEATURE_AUDIT.md`, `feature_validation_matrix.csv`,
  `diagnose_empty_pages.py`): **none exists**. The earlier findings were therefore
  treated as claims to re-verify.
* Authoritative catalog: `src/geoptimiser/features/catalog_data.py` (120 entries; the
  generated `configs/feature_catalog.json` and `docs/FEATURE_CATALOG.md` are checked by
  an existing test).
* Commands: `pip install -e '.[dev]'`; `python -m pytest -q`; `ruff check .`;
  `ruff format --check .`. Baseline: **1442 passed, 13 skipped**; ruff clean. After
  installing the optional extras (`fastapi uvicorn langgraph langchain-openai`): 1485
  passed, 4 skipped. No type checker is configured. Coverage was not measured (no
  coverage threshold exists in the repository).
* Network: outbound website access is denied by the session's egress policy (`curl`
  CONNECT 403); `WebFetch` fails at name resolution; `WebSearch` works and returns
  summaries. Consequences recorded in the audit document.

## 2. Reading the pipeline

Read crawler, extractor, engine, checks, scoring, findings, diagnosis, recommendations,
report, UI and comparison. Confirmed by reading before changing anything: no check
looked at truncation except F060/F102; F012 returned `pass` with a limitation for an
uncrawled target; the crawler's link parser (stdlib, anchors anywhere) and the
extractor's (state machine that skipped `<noscript>`, honoured `<base>`) differed;
scores for categories were rendered whether or not they were reportable; F004-F006 were
`fail`/`high`.

## 3. Reproduction before repair

Built the harness first (`src/geoptimiser/validation`, in-process mock site behind the
real `SafeFetcher`) and 25 fixtures with expectations written from the policy, then ran
them on the **unmodified** code from a clean `git worktree` of `220e9c7`:

    git worktree add --detach <tmp>/baseline_wt 220e9c7
    cp -r src/geoptimiser/validation <tmp>/baseline_wt/src/geoptimiser/
    PYTHONPATH=<tmp>/baseline_wt/src python -m geoptimiser.validation \
        --fixtures tests/validation/fixtures --out docs/validation/results/baseline_main_220e9c7.json

Result: 4 of 25 fixtures, 200 of 280 expectations met. Every group of unmet expectations
corresponds to a defect in the audit document.

## 4. Implementation, in order

1. Schema (additive): `PageDocument.head_complete`, `.structured_data_error_causes`,
   `.render_signals`; truncated field `title`; `html-extractor:3`.
2. Shared link rules in `crawler/urls.py`; extractor uses them. Parity test.
3. `features/evidence.py` (policies, interstitial, client-rendered signals) and engine
   hook; `Ctx.uncertain_link_sources`; F004/F009/F010/F012/F015/F017/F018/F030/F035/F059/
   F061/F072 changes and catalog entries (check versions 2, `intent_dependent`).
4. `features/contribution.py`, scoring v2 (`reported_score`, `status`,
   `withheld_reason`, exclusions), findings (notices, folding, result-level
   limitations), diagnosis (skip combined findings for client-rendered pages).
5. Report v2, HTML, UI, comparison.
6. Matrix, judgments, sources, threshold register, overlap decisions, corpus
   framework, docs, ADR-0027..0030.

Existing tests whose expectation encoded the old semantics were updated deliberately
(each is a documented policy change): F004/F005/F006/F030 `fail` -> `warning`; F012
uncrawled target `pass` -> `not_measured`; F015 unredirected `pass` -> `not_applicable`;
`warning` "no check emits it" -> only intent features emit it; catalog version 1 -> 2;
"html-extractor:2" -> ":3"; the closed set of truncated fields now contains `title`, so
the tests that used `title` as an *invalid* value use another word; the "empty document"
parser tests now expect only the structural fact that the head was closed. No test was
deleted, skipped or loosened.

## 5. Expectation corrections made during the work

Recorded because they were wrong in the fixtures, not in the implementation:

* `combined_realistic_mix`: the two "duplicate" pages differed in their `<h1>` text, so
  their body text was not identical; the H1 was made identical. The expectation that
  `fnd_F021` be absent was wrong because the client-rendered shell page legitimately has
  no title; the page-level expectation (`/big` F021 `not_measured`) was kept.
* `crawl_incomplete_max_pages`: an F017 expectation assumed the navigation links were
  healthy; they pointed at pages the fixture does not define, so a failure was correct.
  The expectation was removed; the reportability expectation stayed.
* F005 on a truncated head: the original policy treated a head `pass` as conclusive.
  "No noindex" cannot be concluded from an unread head, so `head_violation` was added.
* The F009/F072 test first claimed equality for `min_incoming_links=0`; at 0, F072
  cannot fail (a free pass), so the test now states that instead.

## 6. Verification

    python -m pytest -q                         # clean '.[dev]' venv: 1601 passed, 13 skipped
    python -m pytest -q                         # with extras:        1644 passed, 4 skipped
    ruff check . && ruff format --check .       # clean
    python -m geoptimiser.validation --fixtures tests/validation/fixtures \
        --out docs/validation/results/post_fix.json    # 25/25 fixtures, 280/280
    python -m geoptimiser.validation.corpus --manifest benchmarks/corpus/manifest.json \
        --out docs/validation/results/corpus_initial.json
    python -m geoptimiser.validation.matrix --check
    python -m geoptimiser.demo --out <dir> --force      # before/after on the demo site

## 7. Not done, and why

* A real-world benchmark: no data, no network. Framework and an honest initial corpus
  only.
* Primary-source verification of external claims: pages could not be fetched.
* Browser rendering / F108: out of scope by instruction; recommended as the next
  capability.
* Type checking: no checker is configured.
* Pushing, merging, deploying: not requested; commits are local only.

## Resume

If interrupted: `git status`; `python -m pytest -q`; `python -m geoptimiser.validation.matrix
--write` then `--check`; rerun the two benchmark commands above; finish by reviewing
`git diff 220e9c7 --stat` for unrelated changes.
