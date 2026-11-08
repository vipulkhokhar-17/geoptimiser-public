"""AI-search provider contract, credential gating and deterministic test doubles.

No live provider adapter exists yet (ADR-0016): the contract, the error taxonomy and
the doubles below are what the collector and its tests depend on. A future adapter
implements :class:`AnswerProvider`, declares ``origin="live"``, and reads its key with
:func:`require_env`.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from geoptimiser.schemas import Citation, SchemaModel

ProviderOrigin = Literal["live", "mock", "fixture"]


class ProviderError(Exception):
    """A provider call failed. ``str(error)`` is safe to store: adapters must never
    put credentials, request headers or response bodies in it."""


class ProviderUnavailable(ProviderError):
    """The provider cannot be used at all (credentials or configuration missing)."""


class ProviderTimeout(ProviderError):
    """The provider did not answer within the allowed time."""


class ProviderRateLimited(ProviderError):
    """The provider refused the call because of rate or quota limits."""


class ProviderResponseError(ProviderError):
    """The provider answered, but not with a usable response."""


class ProviderAnswer(SchemaModel):
    """What a provider returned for one query."""

    text: str
    citations: tuple[Citation, ...] = ()


@runtime_checkable
class AnswerProvider(Protocol):
    name: str
    model: str
    origin: ProviderOrigin

    def check_available(self) -> None:
        """Raise :class:`ProviderUnavailable` if the provider cannot be used."""

    def answer(self, query: str, *, timeout_seconds: float) -> ProviderAnswer:
        """Answer ``query`` or raise a :class:`ProviderError`."""


def require_env(variable: str, env: Mapping[str, str]) -> str:
    """Read a credential from ``env`` or raise :class:`ProviderUnavailable`.

    The error names the variable, never its value. ``env`` is injected (normally
    ``os.environ``) so tests never depend on the real environment.
    """
    value = env.get(variable, "").strip()
    if not value:
        raise ProviderUnavailable(f"credentials unavailable: {variable} is not set")
    return value


class ScriptedProvider:
    """Deterministic test double: answers come from a script, errors can be scripted.

    Its ``origin`` is ``"mock"``; observations from it are never real measurements.
    A query missing from the script raises :class:`ProviderResponseError`.
    """

    origin: ProviderOrigin = "mock"

    def __init__(
        self,
        script: Mapping[str, ProviderAnswer | ProviderError],
        *,
        name: str = "mock-provider",
        model: str = "mock-model-1",
        credentials_env: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.name, self.model = name, model
        self._script = dict(script)
        self._credentials_env = credentials_env
        self._env = env if env is not None else {}
        self.calls: list[str] = []

    def check_available(self) -> None:
        if self._credentials_env:
            require_env(self._credentials_env, self._env)

    def answer(self, query: str, *, timeout_seconds: float) -> ProviderAnswer:
        self.check_available()
        self.calls.append(query)
        outcome = self._script.get(query)
        if outcome is None:
            raise ProviderResponseError("no scripted answer for this query")
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome


class FixtureProvider(ScriptedProvider):
    """Replays recorded answers from a JSON file; ``origin`` is ``"fixture"``.

    File format: ``{"answers": {"<query text>": {"text": "...", "citations": [...]}}}``.
    """

    origin: ProviderOrigin = "fixture"

    def __init__(
        self, path: Path, *, name: str = "fixture-provider", model: str = "recorded-1"
    ) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        script = {
            q: ProviderAnswer.model_validate(a) for q, a in data["answers"].items()
        }
        super().__init__(script, name=name, model=model)
