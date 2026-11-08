"""The LangGraph wiring. Skipped (not passed) unless the ``agent`` extra is installed."""

import json

import pytest

pytest.importorskip("langgraph")

from geoptimiser.agent import (  # noqa: E402
    AgentConfig,
    AgentRequest,
    AgentRuntime,
    build_graph,
    default_registry_tools,
    run_agent,
    write_trace,
)
from geoptimiser.schemas import AuditRequest  # noqa: E402
from tests.agent.conftest import (  # noqa: E402
    HAPPY,
    ScriptedModel,
    call,
    drive,
    make_runtime,
)
from tests.diagnosis.conftest import clock  # noqa: E402


def request_for(ctx, goal="Produce validated recommendations."):
    audit = AuditRequest(
        audit_id=ctx.audit_id,
        target_domain="example.com",
        brand_name="Example",
        business_context="A test company.",
        target_audience="Testers",
        authorization_confirmed=True,
    )
    return AgentRequest(audit=audit, goal=goal)


def run(ctx, replies, config=None, **kw):
    model = ScriptedModel(replies)
    config = config or AgentConfig(retry_delay_seconds=0, tool_timeout_seconds=5)
    result = run_agent(
        request_for(ctx), ctx, model, config, sleep=lambda s: None, clock=clock, **kw
    )
    return result, model


def test_graph_topology(ctx):
    runtime, _ = make_runtime(ctx, [])
    graph = build_graph(runtime).get_graph()
    nodes = set(graph.nodes)
    assert {"inspect", "decide", "act", "finalize"} <= nodes
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("__start__", "inspect") in edges and ("finalize", "__end__") in edges
    assert {
        ("act", "decide"),
        ("decide", "act"),
        ("decide", "finalize"),
        ("inspect", "decide"),
    } <= edges


def test_graph_run_completes_with_validated_output(ctx):
    result, model = run(ctx, HAPPY)
    assert result.status == "completed" and result.reason == "recommendations_validated"
    assert (result.evidence_valid, result.output_valid) == (True, True)
    assert result.recommendations is not None and result.recommendations.recommendations
    assert result.provider == "openrouter" and result.model_id == "fake/scripted"
    assert [s.tool for s in result.steps] == [
        "list_findings", "get_finding", "validate_evidence",
        "generate_recommendations", "validate_output", "finish",
    ]  # fmt: skip
    assert len(model.calls) == 6 and result.iterations_used == 6


def test_graph_and_plain_node_driver_agree(ctx, run_, chunks):
    from geoptimiser.agent import AgentContext

    result, _ = run(ctx, HAPPY)
    other = AgentContext.create(run_, chunks, clock=clock)
    final = drive(make_runtime(other, HAPPY)[0])["result"]
    assert result.model_dump(mode="json")["recommendations"] == final["recommendations"]
    assert [s.tool for s in result.steps] == [s["tool"] for s in final["steps"]]


def test_graph_enforces_the_iteration_limit(ctx):
    config = AgentConfig(max_iterations=2, retry_delay_seconds=0)
    result, model = run(ctx, HAPPY, config)
    assert (
        result.status == "incomplete" and result.reason == "iteration_budget_exhausted"
    )
    assert len(model.calls) == 2


def test_graph_failure_modes_are_explicit(ctx):
    result, _ = run(ctx, ["nope", "nope", "nope"])
    assert result.status == "failed" and result.reason == "model_protocol_violation"
    result, _ = run(ctx, [call("run_shell", command="id")] * 3)
    assert result.status == "failed" and all(
        s.status == "rejected" for s in result.steps
    )


def test_a_looping_model_cannot_exceed_the_budget(ctx):
    config = AgentConfig(
        max_iterations=5, max_invalid_decisions=10, retry_delay_seconds=0
    )
    result, model = run(ctx, [call("list_findings")] * 20, config)
    assert result.status == "incomplete" and len(model.calls) == 5


def test_request_and_context_must_describe_the_same_audit(ctx):
    request = request_for(ctx)
    other = request.model_copy(
        update={"audit": request.audit.model_copy(update={"audit_id": "someone_else"})}
    )
    with pytest.raises(ValueError, match="different audits"):
        run_agent(other, ctx, ScriptedModel([]), AgentConfig())


def test_goal_is_validated():
    with pytest.raises(ValueError):
        AgentRequest(audit=None, goal=" ")  # type: ignore[arg-type]


def test_optional_checkpointer_is_supported_but_not_required(ctx):
    memory = pytest.importorskip("langgraph.checkpoint.memory")
    result, _ = run(ctx, HAPPY, checkpointer=memory.InMemorySaver())
    assert result.status == "completed"


def test_trace_artifact(ctx, tmp_path):
    result, _ = run(ctx, HAPPY)
    path = tmp_path / "agent_trace.json"
    write_trace(path, result)
    data = json.loads(path.read_text())
    assert data["status"] == "completed" and data["schema_version"] == 1
    assert data["model_id"] == "fake/scripted" and len(data["steps"]) == 6
    with pytest.raises(FileExistsError):
        write_trace(path, result)
    text = path.read_text()
    assert "OPENROUTER_API_KEY" not in text and "sk-" not in text


def test_graph_without_the_extra_gives_an_install_hint(ctx, monkeypatch):
    import builtins

    real = builtins.__import__

    def deny(name, *a, **k):
        if name.startswith("langgraph"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", deny)
    runtime = AgentRuntime(
        context=ctx, registry=default_registry_tools(with_retrieval=False),
        model=ScriptedModel([]), config=AgentConfig(),
    )  # fmt: skip
    from geoptimiser.agent import ModelUnavailable

    with pytest.raises(ModelUnavailable, match=r"geoptimiser\[agent\]"):
        build_graph(runtime)
    runtime.close()
