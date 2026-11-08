"""The model backend: a small protocol plus an OpenRouter implementation.

The agent talks to ``AgentModel.complete`` only. There is exactly one configured model;
failures are reported, never retried against a different model or provider.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, NamedTuple, Protocol

from geoptimiser.agent.config import ModelConfig

INSTALL_HINT = "install the optional extra with: pip install 'geoptimiser[agent]'"
_TRANSIENT_NAMES = {
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
    "Timeout",
    "TimeoutError",
    "ConnectionError",
}


class ChatMessage(NamedTuple):
    role: str  # "system" | "user" | "assistant"
    content: str


class ModelError(RuntimeError):
    """A model call failed; only ``transient`` failures may be retried (boundedly)."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class ModelUnavailable(ModelError):
    """The model cannot be used at all (missing key or optional dependency)."""


class AgentModel(Protocol):
    provider: str
    model_id: str

    def complete(self, messages: Sequence[ChatMessage]) -> str: ...


def classify_error(exc: BaseException) -> ModelError:
    """A safe ``ModelError`` for a client exception: class name and status only.

    The exception text is deliberately dropped; provider errors can echo request
    details.
    """
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    transient = (
        name in _TRANSIENT_NAMES
        or status in (408, 409, 429)
        or (isinstance(status, int) and status >= 500)
    )
    detail = f"{name}" + (f" (HTTP {status})" if isinstance(status, int) else "")
    return ModelError(f"model call failed: {detail}", transient=bool(transient))


ClientFactory = Callable[[ModelConfig, str], Any]


def _default_client(config: ModelConfig, api_key: str) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ModelUnavailable(
            f"langchain-openai is not installed; {INSTALL_HINT}"
        ) from exc
    headers = {
        k: v
        for k, v in (
            ("HTTP-Referer", config.http_referer),
            ("X-Title", config.app_title),
        )
        if v
    }
    return ChatOpenAI(
        model=config.model_id,
        base_url=config.base_url,
        api_key=api_key,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.timeout_seconds,
        max_retries=0,  # the agent owns the (bounded) retry policy
        default_headers=headers or None,
    )


class OpenRouterModel:
    """Chat completions through OpenRouter's OpenAI-compatible API (via LangChain)."""

    provider = "openrouter"

    def __init__(
        self,
        config: ModelConfig | None = None,
        *,
        env: Mapping[str, str] | None = None,
        client_factory: ClientFactory = _default_client,
    ) -> None:
        import os

        self.config = config or ModelConfig()
        self.model_id = self.config.model_id
        source = os.environ if env is None else env
        key = source.get(self.config.api_key_env, "").strip()
        if not key:
            raise ModelUnavailable(f"{self.config.api_key_env} is not set")
        self._key = key  # never logged, repr'd or serialised
        self._factory = client_factory
        self._client: Any = None

    def __repr__(self) -> str:
        return f"OpenRouterModel(model_id={self.model_id!r})"

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        try:
            if self._client is None:
                self._client = self._factory(self.config, self._key)
            reply = self._client.invoke([(m.role, m.content) for m in messages])
        except ModelError:
            raise
        except Exception as exc:
            raise classify_error(exc) from None
        content = getattr(reply, "content", reply)
        if isinstance(content, list):  # content blocks
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        if not isinstance(content, str) or not content.strip():
            raise ModelError("model returned an empty response", transient=True)
        return content
