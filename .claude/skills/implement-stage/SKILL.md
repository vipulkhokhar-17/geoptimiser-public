---
name: implement-stage
description: Plan and implement exactly one Geoptimiser roadmap stage, with tests and a verified report. Use only when the user runs /implement-stage.
argument-hint: "<stage number> — <goal>"
disable-model-invocation: true
---

# Implement one roadmap stage

Requested stage and goal: $ARGUMENTS

Follow `CLAUDE.md`. Implement only this stage; never start, stub or scaffold a
later stage. If no stage number was given, ask for one and stop.

## 1. Inspect before editing
- Read `CLAUDE.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`
  and `docs/SCHEMAS.md`.
- Confirm every earlier stage the requested stage depends on is complete. If one
  is not, say so and stop.
- Read the code, schemas and tests this stage will touch.

## 2. Present a plan and wait for approval
Before changing files, give the user a short plan:
- the stage's input/output contract and the artifact it produces;
- the files to add or change, and the tests to write;
- assumptions, open questions, and security or data-quality risks;
- any new dependency, with the reason it is needed.

Do not edit files until the user approves the plan.

## 3. Implement
- Small typed functions; Pydantic models for cross-module contracts.
- Mock all network and model calls in unit tests.
- Test normal cases, malformed input, edge cases and failure handling.
- Record material architecture decisions in `docs/DECISIONS.md` as **Proposed**.

## 4. Verify and report
Run and report the exact commands and their real output:

```bash
python -m pytest
ruff check .
ruff format --check .
```

Never claim a check passed unless it was run. Then explain the important code
and decisions, list the changed files, and state the remaining limitations.
Do not mark the stage complete in `docs/ROADMAP.md`: that happens after the
user's review (see `/review-stage`).
