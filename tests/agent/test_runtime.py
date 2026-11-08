import dataclasses
import json
import logging
import time

from geoptimiser.agent import (
    AgentConfig,
    AgentContext,
    ModelError,
    ToolError,
    ToolRegistry,
    ToolSpec,
    initial_state,
)
from geoptimiser.agent.runtime import (
    route_after_act,
    route_after_decide,
    route_after_inspect,
)
from geoptimiser.agent.tools import ListFindingsInput
from tests.agent.conftest import FINISH, HAPPY, call, drive, make_runtime, transient
from tests.diagnosis.conftest import INJECTION, clock


def tools_of(state):
    return [s["tool"] for s in state["steps"]]


# --- routing ----------------------------------------------------------------------------


def state(**changes):
    return initial_state("a1", "g", 5) | changes


def test_routing_table():
    assert route_after_inspect(state()) == "decide"
    assert route_after_inspect(state(status="failed")) == "finalize"
    assert route_after_inspect(state(finish_requested=True)) == "finalize"
    assert route_after_decide(state(pending={"tool": "t", "args": {}})) == "act"
    assert route_after_decide(state()) == "decide"  # invalid reply: ask again
    assert route_after_decide(state(finish_requested=True)) == "finalize"
    assert route_after_decide(state(status="incomplete")) == "finalize"
    assert (
        route_after_decide(state(status="failed", pending={"tool": "t"})) == "finalize"
    )
    assert route_after_act(state(iteration=2)) == "decide"
    assert route_after_act(state(iteration=5)) == "finalize"
    assert route_after_act(state(status="failed")) == "finalize"


def test_initial_state_carries_the_budget_and_identity():
    s = initial_state("aud_1", "goal", 7)
    assert (s["audit_id"], s["goal"], s["status"]) == ("aud_1", "goal", "running")
    assert (s["iteration"], s["max_iterations"], s["remaining_iterations"]) == (0, 7, 7)
    assert s["steps"] == [] and s["errors"] == [] and s["result"] is None


# --- success ------------------------------------------------------------------------------


def test_successful_run_completes_with_validated_output(ctx):
    runtime, model = make_runtime(ctx, HAPPY)
    final = drive(runtime)
    result = final["result"]
    assert final["status"] == "completed" and result["status"] == "completed"
    assert result["reason"] == "recommendations_validated"
    assert tools_of(final) == [
        "list_findings", "get_finding", "validate_evidence",
        "generate_recommendations", "validate_output", "finish",
    ]  # fmt: skip
    assert (result["evidence_valid"], result["output_valid"]) == (True, True)
    assert result["recommendations"]["recommendations"]
    assert len(model.calls) == 6 and final["iteration"] == 6
    assert result["model_summary"] == "done"


def test_nothing_is_retrieved_when_existing_evidence_suffices(ctx):
    final = drive(make_runtime(ctx, HAPPY)[0])
    assert "retrieve_passages" not in tools_of(final)


def test_no_findings_completes_without_calling_the_model(ctx):
    clean = dataclasses.replace(ctx.run, results=(), findings=(), evidence={})
    ctx = AgentContext.create(clean, ctx.chunks, clock=clock)
    assert ctx.diagnosis.findings == ()
    runtime, model = make_runtime(ctx, [])
    final = drive(runtime)
    assert final["status"] == "completed" and "no_findings" in final["reason"]
    assert model.calls == []


# --- invalid and unauthorized decisions ---------------------------------------------------------


def test_malformed_reply_is_recorded_then_the_agent_recovers(ctx):
    runtime, _ = make_runtime(ctx, ["I think we should look at findings", *HAPPY])
    final = drive(runtime)
    assert final["status"] == "completed"
    assert final["steps"][0]["status"] == "invalid"
    assert any(e.startswith("decision:") for e in final["errors"])


def test_repeated_invalid_replies_fail_explicitly(ctx):
    runtime, model = make_runtime(ctx, ["nope"] * 5)
    final = drive(runtime)
    assert final["status"] == "failed" and final["reason"] == "model_protocol_violation"
    assert len(model.calls) == 3  # max_invalid_decisions
    assert final["result"]["recommendations"] is None


def test_an_unauthorized_tool_is_rejected_and_never_executed(ctx):
    executed = []
    spy = ToolSpec(
        "list_findings", "d", ListFindingsInput, lambda c, a: executed.append(1) or {}
    )
    runtime, _ = make_runtime(ctx, [call("run_shell", cmd="rm -rf /"), call("fetch_url", url="http://x"), call("list_findings"), FINISH],
                              registry=ToolRegistry([spy]))  # fmt: skip
    final = drive(runtime)
    rejected = [s for s in final["steps"] if s["status"] == "rejected"]
    assert [s["tool"] for s in rejected] == ["run_shell", "fetch_url"]
    assert all(s["error_code"] == "unauthorized_tool" for s in rejected)
    assert executed == [1]  # only the legitimately registered call ran, once


def test_invalid_arguments_are_rejected_without_running_the_tool(ctx):
    runtime, _ = make_runtime(
        ctx, [call("get_finding"), call("list_findings", limit=0), *HAPPY]
    )
    final = drive(runtime)
    bad = [s for s in final["steps"] if s["status"] == "rejected"]
    assert [s["error_code"] for s in bad] == ["invalid_arguments"] * 2
    assert final["status"] == "completed"


def test_repeating_a_successful_call_is_refused(ctx):
    runtime, _ = make_runtime(
        ctx, [call("list_findings"), call("list_findings"), *HAPPY[1:]]
    )
    final = drive(runtime)
    statuses = [(s["tool"], s["status"]) for s in final["steps"]][:3]
    assert statuses == [
        ("list_findings", "ok"),
        ("list_findings", "rejected"),
        ("get_finding", "ok"),
    ]
    assert any("duplicate_action" in e for e in final["errors"])


def test_repeating_forever_cannot_loop(ctx):
    runtime, model = make_runtime(ctx, [call("list_findings")] * 20)
    final = drive(runtime)
    assert final["status"] == "failed" and final["reason"] == "model_protocol_violation"
    assert len(model.calls) == 1 + 3


def test_failed_calls_may_be_retried_by_the_model_but_successes_may_not(ctx):
    runtime, _ = make_runtime(ctx, [call("get_finding", finding_id="fnd_NOPE"),
                                    call("get_finding", finding_id="fnd_NOPE"), FINISH])  # fmt: skip
    final = drive(runtime)
    assert [s["status"] for s in final["steps"]] == ["error", "error", "ok"]


# --- tool failures and retries -------------------------------------------------------------


def flaky_registry(failures, transient_flag=True):
    calls = []

    def handler(ctx, args):
        calls.append(1)
        if len(calls) <= failures:
            raise ToolError("flaky", "try again", transient=transient_flag)
        return {"total": 0, "returned": 0, "findings": []}

    return ToolRegistry(
        [ToolSpec("list_findings", "d", ListFindingsInput, handler)]
    ), calls


def test_transient_tool_failure_is_retried_within_the_bound(ctx):
    registry, calls = flaky_registry(1)
    sleeps = []
    runtime, _ = make_runtime(
        ctx, [call("list_findings"), FINISH], registry=registry, sleeps=sleeps
    )
    final = drive(runtime)
    assert len(calls) == 2 and final["steps"][0]["status"] == "ok"
    assert final["steps"][0]["attempts"] == 2 and len(sleeps) == 1


def test_transient_tool_failure_stops_retrying_at_the_limit(ctx):
    registry, calls = flaky_registry(99)
    config = AgentConfig(max_tool_retries=2, retry_delay_seconds=0)
    runtime, _ = make_runtime(ctx, [call("list_findings"), FINISH], config, registry)
    final = drive(runtime)
    assert len(calls) == 3  # first try + 2 retries
    assert final["steps"][0]["status"] == "error" and final["steps"][0]["attempts"] == 3


def test_permanent_tool_failure_is_not_retried(ctx):
    registry, calls = flaky_registry(99, transient_flag=False)
    runtime, _ = make_runtime(ctx, [call("list_findings"), FINISH], registry=registry)
    drive(runtime)
    assert len(calls) == 1


def test_a_crashing_tool_does_not_end_the_run(ctx):
    def crash(c, a):
        raise ZeroDivisionError("secret detail")

    registry = ToolRegistry([ToolSpec("list_findings", "d", ListFindingsInput, crash)])
    runtime, _ = make_runtime(ctx, [call("list_findings"), FINISH], registry=registry)
    final = drive(runtime)
    assert final["steps"][0]["error_code"] == "tool_crashed"
    assert "secret detail" not in json.dumps(final["observations"])


def test_a_tool_that_hangs_is_cut_off(ctx):
    def hang(c, a):
        time.sleep(0.5)
        return {}

    registry = ToolRegistry([ToolSpec("list_findings", "d", ListFindingsInput, hang)])
    config = AgentConfig(tool_timeout_seconds=0.1, retry_delay_seconds=0)
    runtime, _ = make_runtime(ctx, [call("list_findings"), FINISH], config, registry)
    final = drive(runtime)
    assert (
        final["steps"][0]["status"] == "timeout" and final["steps"][0]["attempts"] == 1
    )


def test_oversized_observations_are_truncated(ctx):
    config = AgentConfig(max_observation_chars=200, retry_delay_seconds=0)
    runtime, _ = make_runtime(ctx, [call("list_findings"), FINISH], config)
    final = drive(runtime)
    assert len(final["observations"][0]["content"]) <= 200


# --- limits --------------------------------------------------------------------------------


def test_iteration_limit_ends_incomplete_with_partial_work_kept(ctx):
    config = AgentConfig(max_iterations=3, retry_delay_seconds=0)
    runtime, model = make_runtime(ctx, HAPPY, config)
    final = drive(runtime)
    assert (
        final["status"] == "incomplete"
        and final["reason"] == "iteration_budget_exhausted"
    )
    assert len(model.calls) == 3 and final["iteration"] == 3
    assert final["result"]["recommendations"] is None  # never reached generation


def test_budget_exhausted_after_generation_is_still_not_completed(ctx):
    config = AgentConfig(max_iterations=4, retry_delay_seconds=0)
    runtime, _ = make_runtime(ctx, HAPPY, config)
    final = drive(runtime)
    assert final["status"] == "incomplete"
    assert final["result"]["recommendations"] is not None  # partial work is reported
    assert final["result"]["output_valid"] is True


def test_transient_model_errors_are_retried_a_bounded_number_of_times(ctx):
    sleeps = []
    runtime, model = make_runtime(
        ctx, [transient(), transient(), *HAPPY], sleeps=sleeps
    )
    final = drive(runtime)
    assert final["status"] == "completed" and len(sleeps) == 2
    config = AgentConfig(max_model_retries=1, retry_delay_seconds=0)
    runtime, model = make_runtime(ctx, [transient()] * 5, config)
    final = drive(runtime)
    assert final["status"] == "failed" and "retries exhausted" in final["reason"]
    assert len(model.calls) == 2


def test_permanent_model_error_fails_at_once_with_no_fallback(ctx):
    runtime, model = make_runtime(ctx, [ModelError("auth", transient=False), *HAPPY])
    final = drive(runtime)
    assert final["status"] == "failed" and final["reason"].startswith(
        "model_error: permanent"
    )
    assert len(model.calls) == 1  # nothing else was tried
    assert final["result"]["model_id"] == "fake/scripted"


# --- the outcome is validated, not claimed ----------------------------------------------------------


def test_finishing_without_recommendations_is_incomplete(ctx):
    runtime, _ = make_runtime(ctx, [call("list_findings"), FINISH])
    final = drive(runtime)
    assert final["status"] == "incomplete"
    assert final["reason"] == "finished_without_recommendations"


def test_an_immediate_finish_cannot_fabricate_success(ctx):
    final = drive(make_runtime(ctx, [FINISH])[0])
    assert final["status"] == "incomplete"


def test_broken_evidence_fails_even_if_the_model_says_done(ctx):
    runtime, _ = make_runtime(ctx, [call("list_findings"), FINISH])
    ctx.chunks = ctx.chunks[:0]  # passages in the findings can no longer be located
    final = drive(runtime)
    assert (
        final["status"] == "failed" and final["reason"] == "evidence_validation_failed"
    )
    assert final["result"]["evidence_valid"] is False


def test_evidence_that_breaks_after_generation_is_caught_at_the_end(ctx):
    runtime, _ = make_runtime(ctx, [call("generate_recommendations"), FINISH])
    runtime_state = drive(runtime) | {}
    assert runtime_state["status"] == "completed"
    ctx2 = ctx  # same object: break it and finalize again
    ctx2.chunks = ctx2.chunks[:0]
    again = runtime.finalize(
        initial_state(ctx.audit_id, "g", 8)
        | {"finding_ids": ["x"], "finish_requested": True}
    )
    assert again["status"] == "failed"


def test_recommendations_that_fail_validation_fail_the_run(ctx):
    runtime, _ = make_runtime(ctx, [call("generate_recommendations"), FINISH])
    first = runtime.ctx
    original = first.generator.generate

    def tampered(diagnosis, clock):
        result = original(diagnosis, clock)
        rec = result.recommendations[0].model_copy(
            update={"proposed_change": "Guaranteed #1 ranking."}
        )
        return result.model_copy(
            update={"recommendations": (rec, *result.recommendations[1:])}
        )

    first.generator.generate = tampered
    final = drive(runtime)
    assert (
        final["status"] == "failed"
        and final["reason"] == "recommendation_validation_failed"
    )
    assert final["result"]["output_valid"] is False


# --- untrusted content ---------------------------------------------------------------------------


def test_website_text_cannot_widen_permissions_or_change_control(ctx):
    # The page text contains an injection; the "model" obeys it and asks for a shell.
    assert any(INJECTION in e.snippet for e in ctx.diagnosis.evidence.values())
    script = [
        call("get_finding", finding_id="fnd_F021"),
        call("run_shell", command="id"),
        FINISH,
    ]
    runtime, model = make_runtime(ctx, script)
    final = drive(runtime)
    assert [s["status"] for s in final["steps"]] == ["ok", "rejected", "ok"]
    assert "run_shell" not in runtime.registry
    assert all(f.severity for f in ctx.diagnosis.findings)  # nothing re-ranked by text
    prompt = model.calls[1][1].content
    assert prompt.count("<tool_result") >= 1  # the page text arrived as wrapped data


# --- logging --------------------------------------------------------------------------------------


def test_logs_are_structured_and_exclude_content_and_secrets(ctx, caplog):
    caplog.set_level(logging.INFO, logger="geoptimiser.agent")
    drive(make_runtime(ctx, HAPPY)[0])
    events = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "geoptimiser.agent"
    ]
    kinds = {e["event"] for e in events}
    assert {"inspect", "model_reply", "tool", "finish"} <= kinds
    tool_events = [e for e in events if e["event"] == "tool"]
    assert all({"tool", "status", "duration_ms", "step"} <= set(e) for e in tool_events)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert INJECTION not in text and "Second line about widgets" not in text
    assert "OPENROUTER" not in text and "sk-" not in text


def test_trace_steps_store_bounded_arguments(ctx):
    big = {"finding_id": "x" * 100, "pad": "y" * 1000}
    runtime, _ = make_runtime(ctx, [call("get_finding", **big), FINISH])
    final = drive(runtime)
    assert final["steps"][0]["args"] in ({"_truncated": True},)
