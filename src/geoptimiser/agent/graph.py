"""LangGraph wiring and the public ``run_agent`` entry point.

::

    START -> inspect -> decide <-> act
                 \\        |
                  +--> finalize -> END   (also reached on finish, failure or budget)

``inspect`` reads existing audit state, ``decide`` asks the model for one action,
``act`` runs one validated tool, ``finalize`` validates the outcome and sets the
explicit status. The nodes live in ``runtime.py``; this module only connects them.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from geoptimiser.agent.config import AgentConfig
from geoptimiser.agent.models import AgentModel, ModelUnavailable
from geoptimiser.agent.runtime import (
    AgentRuntime,
    initial_state,
    route_after_act,
    route_after_decide,
    route_after_inspect,
)
from geoptimiser.agent.state import AgentResult, AgentState
from geoptimiser.agent.tools import AgentContext, ToolRegistry, default_registry_tools
from geoptimiser.jsonl import write_json_atomic
from geoptimiser.schemas import AuditRequest, NonBlankStr, SchemaModel

INSTALL_HINT = "install the optional extra with: pip install 'geoptimiser[agent]'"


class AgentRequest(SchemaModel):
    """A validated audit request plus what the agent should achieve for it."""

    audit: AuditRequest
    goal: NonBlankStr = Field(
        default="Produce validated, evidence-linked recommendations for this audit.",
        max_length=500,
    )


def build_graph(runtime: AgentRuntime, checkpointer: Any | None = None) -> Any:
    """Compile the agent graph (requires the ``agent`` extra)."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise ModelUnavailable(f"langgraph is not installed; {INSTALL_HINT}") from exc
    graph = StateGraph(AgentState)
    graph.add_node("inspect", runtime.inspect)
    graph.add_node("decide", runtime.decide)
    graph.add_node("act", runtime.act)
    graph.add_node("finalize", runtime.finalize)
    graph.add_edge(START, "inspect")
    graph.add_conditional_edges(
        "inspect", route_after_inspect, {"decide": "decide", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "decide",
        route_after_decide,
        {"act": "act", "decide": "decide", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "act", route_after_act, {"decide": "decide", "finalize": "finalize"}
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def run_agent(
    request: AgentRequest,
    context: AgentContext,
    model: AgentModel,
    config: AgentConfig | None = None,
    *,
    registry: ToolRegistry | None = None,
    checkpointer: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AgentResult:
    """Run the bounded agent and return an explicit completed/incomplete/failed result.

    The deterministic audit and retrieval pipeline are unaffected and usable alone;
    this only coordinates them. Raises ``ValueError`` if the request and context
    describe different audits, and ``ModelUnavailable`` if LangGraph is missing.
    """
    config = config or AgentConfig()
    if request.audit.audit_id != context.audit_id:
        raise ValueError("the request and the audit context belong to different audits")
    registry = registry or default_registry_tools(
        with_retrieval=context.retriever is not None
    )
    runtime = AgentRuntime(
        context=context, registry=registry, model=model, config=config,
        sleep=sleep, clock=clock,
    )  # fmt: skip
    try:
        graph = build_graph(runtime, checkpointer)
        state = initial_state(context.audit_id, request.goal, config.max_iterations)
        settings: dict[str, Any] = {"recursion_limit": 4 * config.max_iterations + 12}
        if checkpointer is not None:
            settings["configurable"] = {"thread_id": context.audit_id}
        final = graph.invoke(state, settings)
        return AgentResult.model_validate(final["result"])
    finally:
        runtime.close()


def write_trace(path: Any, result: AgentResult) -> None:
    """Write ``agent_trace.json`` (atomic, never overwrites)."""
    write_json_atomic(path, result.model_dump(mode="json"))
