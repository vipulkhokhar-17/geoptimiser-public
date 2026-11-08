---
name: review-stage
description: Review one implemented Geoptimiser roadmap stage against its definition of done and report verified findings. Use only when the user runs /review-stage.
argument-hint: "<stage number>"
disable-model-invocation: true
---

# Review one roadmap stage

Stage to review: $ARGUMENTS

This is a review, not an implementation: do not modify files unless the user
asks for fixes after seeing the report. If no stage number was given, ask for
one and stop.

## 1. Gather context
- Read `CLAUDE.md`, the stage's row and the "Definition of done" in
  `docs/ROADMAP.md`, and the related entries in `docs/DECISIONS.md` and
  `docs/SCHEMAS.md`.
- Inspect the diff or files that implement the stage.

## 2. Verify by running, not by reading
```bash
python -m pytest
ruff check .
ruff format --check .
```
Report the exact commands and their real output.

## 3. Check against the definition of done
For each item, state met / not met / partially met, with evidence (a file and
line, a test name or command output):
- clear module contract; primary behaviour and edge cases tested;
- network and model calls mocked in unit tests;
- a reviewable artifact or verifiable API result;
- the complete prior test suite still passes;
- documentation explains how to run and inspect the stage;
- security and data-quality limitations recorded.

Also check the `CLAUDE.md` rules: evidence links, missing vs negative results,
untrusted web content, no secrets in artifacts, bounded loops and crawling, and
no work from later stages.

## 4. Report
List findings with the most severe first, each with its evidence and a suggested
fix. End with a recommendation: ready to mark complete, or the specific items
blocking completion. Only the user marks a stage complete or accepts an ADR.
