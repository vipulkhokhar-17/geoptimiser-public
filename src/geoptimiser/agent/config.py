"""Agent and model-provider configuration (kept apart from the business logic)."""

import json
from pathlib import Path

from pydantic import Field, ValidationError, field_validator

from geoptimiser.schemas import NonBlankStr, SchemaModel

DEFAULT_MODEL_ID = "nvidia/nemotron-3-ultra-550b-a55b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class ModelConfig(SchemaModel):
    """Which model to call and how. The key is read from the environment at runtime;
    only the *name* of the variable is configuration."""

    provider: str = "openrouter"
    model_id: NonBlankStr = DEFAULT_MODEL_ID
    base_url: NonBlankStr = OPENROUTER_BASE_URL
    api_key_env: NonBlankStr = "OPENROUTER_API_KEY"
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=64, le=8192)
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)
    # Optional OpenRouter attribution headers (not secrets).
    http_referer: str | None = None
    app_title: str | None = None

    @field_validator("provider")
    @classmethod
    def _only_openrouter(cls, value: str) -> str:
        if value != "openrouter":
            raise ValueError("only the 'openrouter' provider is supported")
        return value

    @field_validator("base_url")
    @classmethod
    def _https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("base_url must use https")
        return value.rstrip("/")


class AgentConfig(SchemaModel):
    model: ModelConfig = ModelConfig()
    max_iterations: int = Field(default=8, ge=1, le=50)  # model calls, not tool calls
    max_invalid_decisions: int = Field(default=3, ge=1, le=10)  # consecutive
    max_model_retries: int = Field(default=2, ge=0, le=5)  # transient errors only
    max_tool_retries: int = Field(default=1, ge=0, le=3)  # transient errors only
    retry_delay_seconds: float = Field(default=1.0, ge=0, le=30)
    tool_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300)
    max_observation_chars: int = Field(default=3000, ge=200, le=20000)
    history_window: int = Field(
        default=6, ge=1, le=20
    )  # observations shown to the model


class AgentConfigError(ValueError):
    """The agent configuration file is unreadable or invalid."""


def load_agent_config(path: Path) -> AgentConfig:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return AgentConfig.model_validate(data)
    except (OSError, UnicodeDecodeError) as exc:
        raise AgentConfigError(f"{path}: cannot read ({type(exc).__name__})") from exc
    except json.JSONDecodeError as exc:
        raise AgentConfigError(f"{path}: invalid JSON at line {exc.lineno}") from exc
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise AgentConfigError(f"{path}: {where}: {first['msg']}") from exc
