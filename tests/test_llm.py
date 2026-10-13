"""The Claude code path, exercised offline.

The SDK is pointed at an in-process transport, so these tests check the request the
real client would send and how real response bodies are handled, without a key or a
network call.
"""

import asyncio
import json

import anthropic
import httpx2
import pytest

from amongagents.agent.llm import (
    AnthropicLLM,
    FatalLLMError,
    LLMConfig,
    LLMError,
    Usage,
    check_connection,
    cost_usd,
    has_api_credentials,
    make_llm,
)


def message(text="[Action] SKIP VOTE", stop_reason="end_turn", content=None, **usage):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": content if content is not None else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 40, **usage},
    }


def llm_with(handler, config=None, max_retries=0):
    client = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=max_retries,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicLLM(config or LLMConfig(), client=client)


def test_the_request_is_what_haiku_5_5_accepts():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx2.Response(200, json=message())

    asyncio.run(llm_with(handler).complete("SYSTEM PROMPT", "USER PROMPT"))

    assert sent["model"] == "claude-haiku-5-5"
    assert sent["messages"] == [{"role": "user", "content": "USER PROMPT"}]  # ends on a user turn: no prefill
    assert sent["system"] == [
        {"type": "text", "text": "SYSTEM PROMPT", "cache_control": {"type": "ephemeral"}}
    ]
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["output_config"] == {"effort": "medium"}
    assert sent["max_tokens"] == 4096
    # Haiku 5.5 returns a 400 for sampling parameters and has no server-side fallback
    for rejected in ("temperature", "top_p", "top_k", "fallbacks"):
        assert rejected not in sent


def test_effort_and_thinking_follow_the_config():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx2.Response(200, json=message())

    config = LLMConfig(effort="low", thinking="adaptive", max_tokens=2000)
    asyncio.run(llm_with(handler, config).complete("s", "u"))
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": "low"}
    assert sent["max_tokens"] == 2000


def test_usage_is_read_including_cache_tokens():
    body = message(cache_read_input_tokens=900, cache_creation_input_tokens=30)
    response = asyncio.run(llm_with(lambda r: httpx2.Response(200, json=body)).complete("s", "u"))
    assert response.usage == Usage(
        calls=1, input_tokens=120, output_tokens=40, cache_read_tokens=900, cache_write_tokens=30
    )
    assert response.model == "claude-haiku-5-5"
    assert response.text == "[Action] SKIP VOTE"


def test_text_is_read_by_block_type_not_position():
    """With adaptive thinking a response can begin with a thinking block."""
    content = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "[Action] SKIP VOTE"},
    ]
    body = message(content=content)
    response = asyncio.run(llm_with(lambda r: httpx2.Response(200, json=body)).complete("s", "u"))
    assert response.text == "[Action] SKIP VOTE"


def test_a_refusal_is_reported_not_raised():
    body = message(content=[], stop_reason="refusal")
    response = asyncio.run(llm_with(lambda r: httpx2.Response(200, json=body)).complete("s", "u"))
    assert response.refused and response.text == ""


def error(status, error_type):
    body = {"type": "error", "error": {"type": error_type, "message": f"{error_type} happened"}}
    return lambda request: httpx2.Response(status, json=body)


@pytest.mark.parametrize(
    "status, error_type",
    [(401, "authentication_error"), (403, "permission_error"), (404, "not_found_error"), (400, "invalid_request_error")],
)
def test_errors_no_retry_can_fix_are_fatal(status, error_type):
    with pytest.raises(FatalLLMError, match=error_type):
        asyncio.run(llm_with(error(status, error_type)).complete("s", "u"))


@pytest.mark.parametrize("status, error_type", [(429, "rate_limit_error"), (529, "overloaded_error"), (500, "api_error")])
def test_transient_errors_fail_the_game_but_not_the_run(status, error_type):
    with pytest.raises(LLMError) as raised:
        asyncio.run(llm_with(error(status, error_type)).complete("s", "u"))
    assert not isinstance(raised.value, FatalLLMError)


def test_a_transient_error_is_retried_by_the_sdk():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
        return httpx2.Response(200, json=message())

    response = asyncio.run(llm_with(handler, max_retries=2).complete("s", "u"))
    assert len(attempts) == 2 and response.text


def test_missing_credentials_are_reported_before_any_game_starts(monkeypatch, tmp_path):
    """The state this repository is handed over in: everything in place except a key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "no-login-profile-here"))
    assert not has_api_credentials()
    with pytest.raises(FatalLLMError, match="ANTHROPIC_API_KEY"):
        make_llm(LLMConfig())
    result = asyncio.run(check_connection(LLMConfig()))
    assert result["ok"] is False and "ANTHROPIC_API_KEY" in result["error"]


def test_a_key_in_the_environment_is_enough(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert has_api_credentials()
    assert make_llm(LLMConfig()).config.model == "claude-haiku-5-5"


def test_cost_at_list_price():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)
    assert cost_usd(usage, "claude-haiku-5-5") == pytest.approx(0.10 + 0.50 + 0.01 + 0.125)
    assert cost_usd(usage, "mock-scripted") == 0.0
    assert cost_usd(usage, "some-future-model") is None


@pytest.mark.parametrize(
    "bad",
    [{"provider": "openrouter"}, {"effort": "max"}, {"thinking": "enabled"}, {"max_tokens": 50}],
)
def test_config_rejects_settings_the_model_would_reject(bad):
    with pytest.raises(ValueError):
        LLMConfig(**bad)


def test_the_mock_provider_needs_no_sdk_client():
    llm = make_llm(LLMConfig(provider="mock"))
    assert llm.config.provider == "mock"
