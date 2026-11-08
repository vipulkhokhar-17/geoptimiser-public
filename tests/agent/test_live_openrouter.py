"""Optional live smoke test against the real OpenRouter API.

Not part of the default run: it is skipped unless both OPENROUTER_API_KEY is set and
GEOPTIMISER_LIVE=1. It never prints the key. Run it with:

    pip install -e '.[agent]'
    export OPENROUTER_API_KEY=...        # keep it out of shell history and the repo
    GEOPTIMISER_LIVE=1 python -m pytest tests/agent/test_live_openrouter.py -m live -v -rs
"""

import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("GEOPTIMISER_LIVE") != "1"
        or not os.environ.get("OPENROUTER_API_KEY"),
        reason="live test: set GEOPTIMISER_LIVE=1 and OPENROUTER_API_KEY",
    ),
]


def test_the_configured_model_answers_with_a_valid_decision():
    pytest.importorskip("langchain_openai")
    from geoptimiser.agent import AgentConfig, ChatMessage, OpenRouterModel
    from geoptimiser.agent.prompt import parse_decision

    config = AgentConfig()
    model = OpenRouterModel(config.model)
    reply = model.complete(
        [
            ChatMessage(
                "system", 'Reply with one JSON object only: {"action": "finish"}.'
            ),
            ChatMessage("user", "Finish now."),
        ]
    )
    assert parse_decision(reply).action == "finish"


def test_a_short_agent_run_ends_in_an_explicit_status(run_, chunks):
    pytest.importorskip("langgraph")
    pytest.importorskip("langchain_openai")
    from geoptimiser.agent import (
        AgentConfig,
        AgentContext,
        AgentRequest,
        OpenRouterModel,
        run_agent,
    )
    from geoptimiser.schemas import AuditRequest

    config = AgentConfig(max_iterations=6)
    context = AgentContext.create(run_, chunks)
    request = AgentRequest(
        audit=AuditRequest(
            audit_id=run_.audit_id,
            target_domain="example.com",
            brand_name="Example",
            business_context="A test.",
            target_audience="Testers",
            authorization_confirmed=True,
        )  # fmt: skip
    )
    result = run_agent(request, context, OpenRouterModel(config.model), config)
    assert result.status in {"completed", "incomplete", "failed"}
    assert result.model_id == config.model.model_id
    assert os.environ["OPENROUTER_API_KEY"] not in result.model_dump_json()
