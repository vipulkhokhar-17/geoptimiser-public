import json
from typing import Any

import pytest

from geoptimiser.agent import (
    AgentConfig,
    AgentContext,
    AgentRuntime,
    ModelError,
    default_registry_tools,
    initial_state,
)
from geoptimiser.agent.runtime import (
    route_after_act,
    route_after_decide,
    route_after_inspect,
)
from tests.diagnosis.conftest import chunks, clock, pages, run_  # noqa: F401


def call(tool: str, **args: Any) -> str:
    return json.dumps({"thought": f"use {tool}", "action": tool, "args": args})


FINISH = json.dumps({"action": "finish", "args": {}, "summary": "done"})
HAPPY = [
    call("list_findings"),
    call("get_finding", finding_id="fnd_F021"),
    call("validate_evidence"),
    call("generate_recommendations"),
    call("validate_output"),
    FINISH,
]


class ScriptedModel:
    """A fake model that replays prepared replies (or raises prepared errors)."""

    provider = "openrouter"
    model_id = "fake/scripted"

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = list(replies)
        self.calls: list[Any] = []

    def complete(self, messages):
        self.calls.append(messages)
        if not self.replies:
            raise AssertionError("the model was called more often than scripted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def transient(msg: str = "rate limited") -> ModelError:
    return ModelError(msg, transient=True)


@pytest.fixture
def ctx(run_, chunks) -> AgentContext:  # noqa: F811
    return AgentContext.create(run_, chunks, clock=clock)


@pytest.fixture
def fast() -> AgentConfig:
    return AgentConfig(retry_delay_seconds=0, tool_timeout_seconds=5)


def make_runtime(ctx, replies, config=None, registry=None, sleeps=None):
    model = ScriptedModel(replies)
    runtime = AgentRuntime(
        context=ctx,
        registry=registry
        or default_registry_tools(with_retrieval=ctx.retriever is not None),
        model=model,
        config=config or AgentConfig(retry_delay_seconds=0, tool_timeout_seconds=5),
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        clock=clock,
    )
    return runtime, model


def drive(runtime: AgentRuntime, max_it: int | None = None) -> dict[str, Any]:
    """Follow the graph's own routers over the nodes, without LangGraph."""
    state = initial_state(
        runtime.ctx.audit_id, "test goal", max_it or runtime.config.max_iterations
    )
    state |= runtime.inspect(state)
    node = route_after_inspect(state)
    for _ in range(200):  # hard stop for tests
        if node == "finalize":
            state |= runtime.finalize(state)
            return state
        update = getattr(runtime, node)(state)
        state |= update
        node = {
            "decide": route_after_decide,
            "act": route_after_act,
        }[node](state)
    raise AssertionError("the nodes did not terminate")
