from pathlib import Path

import pytest
from pydantic import ValidationError

from geoptimiser.agent import (
    DEFAULT_MODEL_ID,
    AgentConfig,
    AgentConfigError,
    ChatMessage,
    ModelConfig,
    ModelError,
    ModelUnavailable,
    OpenRouterModel,
    load_agent_config,
)
from geoptimiser.agent.models import classify_error

KEY = "FAKE_OPENROUTER_TEST_CREDENTIAL_DO_NOT_USE"


def test_default_model_is_the_requested_free_nemotron():
    assert DEFAULT_MODEL_ID == "nvidia/nemotron-3-ultra-550b-a55b:free"
    cfg = AgentConfig()
    assert cfg.model.model_id == DEFAULT_MODEL_ID
    assert cfg.model.base_url == "https://openrouter.ai/api/v1"
    assert cfg.model.api_key_env == "OPENROUTER_API_KEY"
    assert cfg.max_iterations == 8


def test_shipped_config_matches_defaults_and_holds_no_secret():
    path = Path("configs/agent.json")
    assert load_agent_config(path) == AgentConfig()
    assert "sk-" not in path.read_text()


@pytest.mark.parametrize(
    "bad",
    [
        {"max_iterations": 0},
        {"max_iterations": 500},
        {"max_tool_retries": 99},
        {"model": {"base_url": "http://openrouter.ai/api/v1"}},
        {"model": {"provider": "somewhere-else"}},
        {"model": {"model_id": " "}},
        {"unknown": 1},
    ],
)
def test_invalid_config_is_rejected(bad):
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(bad)


def test_the_model_id_is_configuration_not_code():
    cfg = AgentConfig(model=ModelConfig(model_id="other/model:free"))
    assert cfg.model.model_id == "other/model:free"


def test_config_errors_name_the_file(tmp_path):
    bad = tmp_path / "a.json"
    bad.write_text('{"max_iterations": 0}')
    with pytest.raises(AgentConfigError, match="a.json"):
        load_agent_config(bad)
    with pytest.raises(AgentConfigError, match="cannot read"):
        load_agent_config(tmp_path / "none.json")


# --- OpenRouterModel ------------------------------------------------------------------


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def invoke(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Reply:
    def __init__(self, content):
        self.content = content


def model_with(client, **env):
    seen = []

    def factory(config, key):
        seen.append((config, key))
        return client

    env = env or {"OPENROUTER_API_KEY": KEY}
    return OpenRouterModel(env=env, client_factory=factory), seen


def test_missing_key_is_reported_by_name_only():
    with pytest.raises(ModelUnavailable) as err:
        OpenRouterModel(env={})
    assert "OPENROUTER_API_KEY" in str(err.value)
    with pytest.raises(ModelUnavailable):
        OpenRouterModel(env={"OPENROUTER_API_KEY": "   "})


def test_the_key_never_appears_in_repr_or_errors():
    client = FakeClient([RuntimeError(f"bad {KEY}")])
    model, _ = model_with(client)
    assert KEY not in repr(model) and KEY not in str(model)
    with pytest.raises(ModelError) as err:
        model.complete([ChatMessage("user", "hi")])
    assert KEY not in str(err.value) and "RuntimeError" in str(err.value)


def test_key_env_var_name_is_configurable():
    cfg = ModelConfig(api_key_env="MY_KEY")
    OpenRouterModel(
        cfg, env={"MY_KEY": KEY}, client_factory=lambda c, k: FakeClient([])
    )
    with pytest.raises(ModelUnavailable, match="MY_KEY"):
        OpenRouterModel(cfg, env={"OPENROUTER_API_KEY": KEY})


def test_client_is_created_lazily_once_and_gets_the_configured_model():
    client = FakeClient([Reply("a"), Reply("b")])
    model, seen = model_with(client)
    assert seen == []
    assert model.complete([ChatMessage("system", "s"), ChatMessage("user", "u")]) == "a"
    assert model.complete([ChatMessage("user", "u")]) == "b"
    assert (
        len(seen) == 1 and seen[0][0].model_id == DEFAULT_MODEL_ID and seen[0][1] == KEY
    )
    assert client.calls[0] == [("system", "s"), ("user", "u")]


def test_content_blocks_are_flattened_and_empty_replies_are_transient():
    client = FakeClient(
        [Reply([{"type": "text", "text": "he"}, {"text": "llo"}]), Reply("  ")]
    )
    model, _ = model_with(client)
    assert model.complete([ChatMessage("user", "x")]) == "hello"
    with pytest.raises(ModelError) as err:
        model.complete([ChatMessage("user", "x")])
    assert err.value.transient


def Boom(name, status=None):
    """An exception whose class is called ``name``, like the OpenAI client's."""
    error = type(name, (Exception,), {})(f"{name} secret detail")
    error.status_code = status
    return error


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (Boom("RateLimitError", 429), True),
        (Boom("APITimeoutError"), True),
        (Boom("APIConnectionError"), True),
        (Boom("InternalServerError", 503), True),
        (Boom("AuthenticationError", 401), False),
        (Boom("NotFoundError", 404), False),
        (Boom("BadRequestError", 400), False),
        (ValueError("x"), False),
    ],
)
def test_error_classification(exc, transient):
    err = classify_error(exc)
    assert err.transient is transient
    assert "secret detail" not in str(err)


def test_a_failed_call_is_not_retried_or_redirected_by_the_model_class():
    client = FakeClient([Boom("RateLimitError", 429)])
    model, seen = model_with(client)
    with pytest.raises(ModelError):
        model.complete([ChatMessage("user", "x")])
    assert len(client.calls) == 1 and len(seen) == 1  # one call, one client, one model


def test_default_client_targets_openrouter_with_the_configured_model():
    pytest.importorskip("langchain_openai")
    from geoptimiser.agent.models import _default_client

    client = _default_client(ModelConfig(model_id="x/y:free", max_tokens=100), KEY)
    assert client.model_name == "x/y:free"
    assert "openrouter.ai" in str(client.openai_api_base)
    assert client.max_retries == 0
    assert KEY not in repr(client)  # SecretStr
