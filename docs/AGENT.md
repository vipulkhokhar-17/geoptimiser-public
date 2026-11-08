# Agent (Day 5 Task 1)

One bounded ReAct agent, built with LangGraph, coordinates the existing Geoptimiser
components. It adds no new analysis: every tool wraps code that already exists. See
ADR-0023 for the decisions.

## Graph

```
START -> inspect -> decide <-> act
              \        |
               +--> finalize -> END
```

| Node | Does | Model call |
|---|---|---|
| `inspect` | Reads the existing diagnosis: finding ids, cited evidence ids. | no |
| `decide` | Asks the model for **one** JSON action; parses and checks it. | yes (1 iteration) |
| `act` | Validates arguments, runs one allowlisted tool under a timeout, records the result. | no |
| `finalize` | Validates evidence and recommendations independently and sets the status. | no |

Routing (`runtime.py`, pure functions): after `inspect` go to `decide` unless the run has
already ended or there is nothing to investigate; after `decide` go to `act` for a valid
tool call, back to `decide` for an invalid reply, and to `finalize` on `finish`, failure
or an exhausted budget; after `act` go to `decide` while budget remains.

## State (`AgentState`, a `TypedDict`)

`audit_id`, `goal`, `status` (`running|completed|incomplete|failed`), `reason`, `iteration`,
`max_iterations`, `remaining_iterations`, `finding_ids`, `evidence_ids` (references only),
`pending` (the validated decision), `steps` (actions taken), `observations` (a bounded
window of tool results), `errors`, `invalid_streak`, `finish_requested`, `model_summary`,
`result`. Live objects (audit run, retriever, model) are held by `AgentRuntime`, not in the
state, so state stays serialisable and a checkpointer is optional (pass any LangGraph
checkpointer to `run_agent`; none is installed or required).

## Tools (the complete allowlist)

| Tool | Arguments | Wraps | Result |
|---|---|---|---|
| `list_findings` | `severity?`, `limit` (1-50) | `Diagnosis.findings` | id, title, severity, basis, evidence and passage counts |
| `get_finding` | `finding_id` | `Diagnosis` | finding detail, evidence refs with locators; page text under `untrusted_text` (<=200 chars) |
| `retrieve_passages` | `finding_id`, `query?` (3-200 chars), `top_k` (1-5) | `Retriever` (hybrid if available), `passage_evidence`, `grounding_problems` | passages from the pages the finding affects, with chunk id and char range; grounded passages are kept as supplementary evidence. Registered only when a retriever exists |
| `validate_evidence` | `finding_id?` | `validate_diagnosis`, `grounding_problems` | `valid`, problem count, first 10 problems |
| `generate_recommendations` | `finding_ids?` | `TemplateGenerator` | recommendation summaries and rejections. Refuses (`evidence_invalid`) if validation fails |
| `validate_output` | none | `validate_recommendations` | `valid`, problems |

`finish` is a protocol action, not a tool. There is no shell, Python execution, file or
network tool, and `retrieve_passages` only searches the already-built local chunk index.
Unknown tools (`unauthorized_tool`), unknown or extra arguments (`invalid_arguments`) and
repeats of a call that already succeeded (`duplicate_action`) are rejected without running
anything.

## Limits and outcomes

* `max_iterations` (default 8) counts **model calls**; the loop cannot exceed it, and
  LangGraph's recursion limit is a second guard.
* `max_invalid_decisions` (3) consecutive bad replies ends the run as `failed`.
* Only **transient** failures are retried: model errors up to `max_model_retries` (2),
  tool errors up to `max_tool_retries` (1). Permanent errors and timeouts are not.
* Each tool runs under `tool_timeout_seconds` (a timed-out call is abandoned, not retried).
* Observations are truncated to `max_observation_chars`; only the last `history_window`
  are shown to the model, so prompts stay bounded.

Outcome, decided by `finalize` from deterministic validation, never from the model's say-so:

| Status | When |
|---|---|
| `completed` | Evidence validates, recommendations exist, validate, and at least one was issued (or there were no findings at all). |
| `incomplete` | Budget exhausted; finished without generating recommendations; or none could be issued. Partial work is kept in the result. |
| `failed` | Model unavailable or erroring permanently; protocol violations; evidence or recommendations fail validation. |

## Untrusted content

Page text only ever appears inside `<tool_result>` blocks and `untrusted_text` fields. The
system prompt tells the model to treat it as data, but the guarantee does not rest on the
prompt: tools, arguments, budgets and status are enforced in code, so a model that obeys an
injected instruction still cannot call an unlisted tool or change the outcome.

## Model configuration

`configs/agent.json` (`AgentConfig`). Defaults: provider `openrouter`, model
`nvidia/nemotron-3-ultra-550b-a55b:free`, base URL `https://openrouter.ai/api/v1`, key read
from `OPENROUTER_API_KEY`. Change `model.model_id` (or pass a `ModelConfig`) to use another
OpenRouter model; nothing else in the code names a model. If a call fails the run reports
the failure; it never tries a different model or provider.

## Setup and the live smoke test

```bash
pip install -e '.[agent]'
export OPENROUTER_API_KEY=...     # shell or untracked .env; never commit, never paste in logs
GEOPTIMISER_LIVE=1 python -m pytest tests/agent/test_live_openrouter.py -m live -v -rs
```

The live tests skip unless both variables are set, and CI never sets them. Free models are
rate-limited and may be slow or unavailable; a failed live run is reported as such.

## Programmatic use

```python
from geoptimiser.agent import (
    AgentConfig,
    AgentContext,
    AgentRequest,
    OpenRouterModel,
    run_agent,
    write_trace,
)

context = AgentContext.create(
    audit_run, chunks, retriever=retriever
)  # retriever optional
config = AgentConfig()  # or load_agent_config(path)
result = run_agent(
    AgentRequest(audit=audit_request), context, OpenRouterModel(config.model), config
)
write_trace("agent_trace.json", result)
print(result.status, result.reason)
```

`audit_run`, `chunks` and `retriever` come from the existing pipeline (`run_audit`,
`chunk_documents`, `build_retriever`). The agent never replaces any of it.

## Data sent to OpenRouter

When the agent runs, its model requests are sent to the configured OpenRouter endpoint over HTTPS. The prompt includes the audit identifier, goal, finding counts, recent action history, errors, and bounded tool observations. Tool observations can include source URLs, finding metadata, short evidence snippets and retrieved passages from audited website content. The default observation cap is 3,000 characters per observation, with a bounded history window.

This means the crawler and most of the audit pipeline can run locally while agent-enabled analysis still transfers some audit context to an external provider. Review OpenRouter's current privacy and data-use terms before using the agent with non-public, confidential or customer data. The OpenRouter key is read from the environment and is not included in prompts or logs.

## Logging

The `geoptimiser.agent` logger emits one JSON object per event (`inspect`, `model_reply`,
`model_failed`, `invalid_decision`, `tool`, `finish`) with codes, counts and durations.
Page text, model replies, prompts and the API key are never logged.
