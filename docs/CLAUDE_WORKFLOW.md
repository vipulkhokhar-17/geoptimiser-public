# Working with Claude Code

## First session prompt
Paste this after opening Claude Code in the repository:

> Read `CLAUDE.md`, `README.md`, `docs/ROADMAP.md`, `docs/project/ARCHITECTURE.md`, `docs/project/DEVELOPMENT_GUIDE.md`, and `docs/SECURITY.md`. Inspect the actual repository state and current branch before proposing work. Do not restart completed stages or reimplement existing functionality. Identify the specific user-requested stage or bounded task, explain the plan and trust boundaries, then wait for approval before making broad changes. Add regression tests, run the relevant quality gates, report exact commands/results, and explain the changed files. Never mark work complete unless the acceptance criteria have been verified.

## Project skills
Two project skills live in `.claude/skills/` and load when Claude Code is started
from the repository root. Both run only when you type the command; Claude does not
invoke them on its own.

| Command | File | What it does |
|---|---|---|
| `/implement-stage <NN> — <goal>` | `.claude/skills/implement-stage/SKILL.md` | Inspects, presents a plan and waits for approval, then implements one stage with tests and a verified report |
| `/review-stage <NN>` | `.claude/skills/review-stage/SKILL.md` | Runs the checks and reviews one stage against the roadmap's definition of done, without editing files |

Type `/` in Claude Code to confirm both appear in the command menu.

## Before each stage
Use `/implement-stage <NN> — <bounded goal>` for the stage that is actually requested. Read the current roadmap and generated feature register first. Do not assume the next stage number from an old conversation.

## After each stage
1. Inspect the diff.
2. Ask `/review-stage <NN>` for the relevant stage.
3. Run tests yourself or verify the reported test commands.
4. Check whether roadmap status accurately reflects the actual implementation.
5. Commit a working checkpoint before moving on.
6. Open a pull request; CI (`.github/workflows/ci.yml`) runs pytest, Ruff, and a dependency audit.

## Useful Claude Code commands
- `/help` — available commands
- `/doctor` — installation/configuration check
- `/memory` — inspect saved Claude Code memory
- `/compact` — summarize/reduce current session context when needed
- `/implement-stage 01 — <goal>` — project skill to plan and implement one stage
- `/review-stage 00` — project skill to review a stage

## How to work effectively
- Ask for one stage or one bounded feature per task.
- Ask Claude to explain trade-offs and then explain the core code back to you.
- Make it show and run tests; avoid accepting “looks correct” as verification.
- Do not approve installing large dependencies without a reason.
- Never paste API keys into the chat; store them in ignored `.env` and load them server-side.
