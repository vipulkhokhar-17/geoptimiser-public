from pathlib import Path

import pytest

from geoptimiser.visibility import (
    AnswerProvider,
    FixtureProvider,
    ProviderAnswer,
    ProviderRateLimited,
    ProviderResponseError,
    ProviderTimeout,
    ProviderUnavailable,
    ScriptedProvider,
    require_env,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_require_env_reads_a_key_and_never_leaks_it() -> None:
    assert require_env("KEY", {"KEY": " s3cret "}) == "s3cret"
    for env in ({}, {"KEY": ""}, {"KEY": "   "}):
        with pytest.raises(ProviderUnavailable) as caught:
            require_env("KEY", env)
        assert "KEY is not set" in str(caught.value)


def test_scripted_provider_follows_its_script_and_is_a_mock() -> None:
    provider = ScriptedProvider({"q": ProviderAnswer(text="a")})
    assert isinstance(provider, AnswerProvider) and provider.origin == "mock"
    assert provider.answer("q", timeout_seconds=1).text == "a"
    assert provider.calls == ["q"]
    with pytest.raises(ProviderResponseError, match="no scripted answer"):
        provider.answer("other", timeout_seconds=1)


@pytest.mark.parametrize("error", [ProviderTimeout("slow"), ProviderRateLimited("429")])
def test_scripted_errors_are_raised(error: Exception) -> None:
    provider = ScriptedProvider({"q": error})  # type: ignore[dict-item]
    with pytest.raises(type(error)):
        provider.answer("q", timeout_seconds=1)


def test_credentials_gate_availability_without_touching_the_real_environment() -> None:
    gated = ScriptedProvider({}, credentials_env="SEARCH_KEY", env={})
    with pytest.raises(ProviderUnavailable, match="SEARCH_KEY"):
        gated.check_available()
    with pytest.raises(ProviderUnavailable):
        gated.answer("q", timeout_seconds=1)
    assert gated.calls == []  # an unavailable provider is never called
    ScriptedProvider(
        {}, credentials_env="SEARCH_KEY", env={"SEARCH_KEY": "x"}
    ).check_available()


def test_fixture_provider_replays_recordings_and_is_labelled_a_fixture() -> None:
    provider = FixtureProvider(FIXTURES / "answers.json")
    assert provider.origin == "fixture"
    answer = provider.answer("what is invoice automation", timeout_seconds=1)
    assert "Acme Billing" in answer.text and len(answer.citations) == 2
    assert answer.citations[1].title is None
