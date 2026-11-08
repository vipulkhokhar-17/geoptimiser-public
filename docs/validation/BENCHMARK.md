# Running and extending the benchmarks

## Synthetic fixtures (offline, ~15 s)

    python -m geoptimiser.validation --fixtures tests/validation/fixtures \
        --out docs/validation/results/post_fix.json
    python -m pytest tests/validation          # the same fixtures as tests

`--only <text>` runs fixtures whose id contains the text. Exit status is non-zero if any
expectation is unmet. Output: per-fixture pass/fail with every unmet expectation, and
per-feature confusion counts, precision, recall and Wilson intervals (null = undefined).

### Writing a fixture

Add `tests/validation/fixtures/<id>/spec.json` (see `validation/spec.py`): the routes of
a mock site (`{{COMMENT:N}}` and `{{WORDS:N}}` expand to N bytes of filler; `behavior`
`drop`/`hang` simulates a dead server), crawl settings (a small `max_response_bytes`
makes a cheap truncation), and `expect`: per page and feature the status and wording,
findings present/absent with severity and text, score reportability/contribution,
recommendation text that must not appear. **Write the expectations from
`VALIDATION_POLICY.md` first, run it, and only then change code**; if the expectation
was wrong, fix it with a note in the work log.

### Baseline versus after

    git worktree add /tmp/base 220e9c7
    cp -r src/geoptimiser/validation /tmp/base/src/geoptimiser/
    (cd /tmp/base && PYTHONPATH=src python -m geoptimiser.validation \
        --fixtures <repo>/tests/validation/fixtures --out baseline.json)

Results recorded here: `results/baseline_main_220e9c7.json` (original code: 4 of 25
fixtures, 200 of 280 expectations met) and `results/post_fix.json` (25 of 25, 280 of
280). The summary also reports `state_confusion` (expected vs actual state for every
expectation), `false_failures_on_unmeasurable` (a defect reported where the evidence could
not support one: original 14, corrected 0) and `silent_passes_on_unmeasurable` (original 4,
corrected 0). Pass/fail precision and recall over the 144 pass/fail expectations: original
0.933 / 1.000 (TP 28, FP 2, TN 111, FN 0), corrected 1.000 / 1.000 (TP 28, TN 116); the
95% Wilson lower bound for the corrected precision is 0.879 because the sample is small.
These numbers cannot show the other defects, which are states other than pass/fail. The fixtures were written to describe the policy, so "after = all met" shows the
code now follows the policy, not that the policy is right.

## Labelled corpus

    python -m geoptimiser.validation.corpus \
        --manifest benchmarks/corpus/manifest.json \
        --out docs/validation/results/corpus_initial.json

The shipped manifest is repository-local and oracle-labelled (see
`VALIDATION_METHODOLOGY.md` section 5). To start a real corpus: put snapshots in
`benchmarks/corpus/snapshots/`, add `Snapshot` entries with `real_world: true`, labels
of `kind: human` (with `second_label` for a second reviewer and `uncertainty` for doubt),
and record the response conditions. Check each source's terms and robots rules before
collecting, store no credentials or personal data, and never claim a number of
validated pages that were not actually labelled.

## Matrix and audit document

    python -m geoptimiser.validation.matrix --write   # regenerate CSV + register
    python -m geoptimiser.validation.matrix --check   # fail if stale or incomplete
    python -m geoptimiser.features --export           # catalog JSON/Markdown/scoring

Judgments live in `src/geoptimiser/validation/judgments.py` and sources in `sources.py`;
facts (status, location, thresholds, tests) are derived and need no editing.

## CI

`pytest` already runs the fixtures, the matrix check, the overlap check and the corpus
evaluation, so the existing CI job covers them. The synthetic benchmark needs no extras
and no network.
