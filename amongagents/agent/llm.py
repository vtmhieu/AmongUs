"""Model access.

Agents talk to a model through one method, ``complete(system, user)``. Two providers
implement it: ``anthropic`` (the Claude API, used for the experiments) and ``mock``
(scripted offline players, used for tests and for trying the pipeline without a key).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol

DEFAULT_MODEL = "claude-haiku-5-5"

PROVIDERS = ("anthropic", "mock")
EFFORTS = ("low", "medium", "high")
THINKING_MODES = ("disabled", "adaptive")

# USD per million tokens: (input, output, cache read, 5-minute cache write).
# Haiku 5.5 rates are for prompts up to 100K tokens; a game prompt is ~2K.
PRICING = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
}


@dataclass(frozen=True)
class LLMConfig:
    """Model settings, held fixed across every condition of an experiment.

    Claude Haiku 5.5 does not accept temperature, top_p or top_k, so the decoding
    settings a study can pin are ``effort`` and ``thinking``. Thinking is off by
    default: the agent prompt already asks for a written [Thinking Process], and
    keeping that the only reasoning channel means all of an agent's reasoning is in
    the logs.
    """

    provider: str = "anthropic"
    model: str = DEFAULT_MODEL
    effort: str = "medium"
    thinking: str = "disabled"
    max_tokens: int = 4096
    # mock provider only
    mock_latency: float = 0.0  # seconds per call, so a mock game can be watched
    mock_malformed_rate: float = 0.0  # share of replies that are deliberately unparseable

    def __post_init__(self):
        if self.provider not in PROVIDERS:
            raise ValueError(f"provider must be one of {PROVIDERS}, got {self.provider!r}")
        if self.effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}, got {self.effort!r}")
        if self.thinking not in THINKING_MODES:
            raise ValueError(f"thinking must be one of {THINKING_MODES}, got {self.thinking!r}")
        if not 256 <= self.max_tokens <= 16000:
            raise ValueError("max_tokens must be between 256 and 16000")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> LLMConfig:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0  # uncached input tokens
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens

    def to_dict(self) -> dict:
        return asdict(self)


def cost_usd(usage: Usage | dict, model: str) -> float | None:
    """Cost of some usage at list price, or None for a model with no known price."""
    price = PRICING.get(model)
    if price is None:
        return 0.0 if model.startswith("mock") else None
    u = usage if isinstance(usage, dict) else usage.to_dict()
    per_token = [p / 1_000_000 for p in price]
    return (
        u.get("input_tokens", 0) * per_token[0]
        + u.get("output_tokens", 0) * per_token[1]
        + u.get("cache_read_tokens", 0) * per_token[2]
        + u.get("cache_write_tokens", 0) * per_token[3]
    )


@dataclass
class LLMResponse:
    text: str
    model: str
    stop_reason: str | None = None
    usage: Usage = field(default_factory=Usage)
    latency_s: float = 0.0
    request_id: str | None = None

    @property
    def refused(self) -> bool:
        return self.stop_reason == "refusal"

    @property
    def truncated(self) -> bool:
        return self.stop_reason == "max_tokens"


class LLMError(Exception):
    """A model call failed after retries. The game it belongs to cannot continue."""


class FatalLLMError(LLMError):
    """A model call failed in a way no retry will fix (bad key, unknown model, bad request)."""


class LLM(Protocol):
    config: LLMConfig

    async def complete(self, system: str, user: str, *, seed: int | None = None) -> LLMResponse: ...

    async def close(self) -> None: ...


NO_CREDENTIALS = (
    "No Claude API credentials found. Put ANTHROPIC_API_KEY=... in a .env file at the "
    "repository root (see .env.example), or run `ant auth login`."
)


class AnthropicLLM:
    """Claude through the official SDK.

    One instance is shared by every game of a run, so they share a connection pool
    and one cap on in-flight requests. Rate limits and transient errors are retried
    by the SDK with backoff; what still fails is raised as LLMError.
    """

    def __init__(self, config: LLMConfig, max_concurrency: int = 8, client=None):
        import anthropic

        self.config = config
        self._anthropic = anthropic
        if client is None:
            try:
                client = anthropic.AsyncAnthropic(max_retries=8, timeout=180.0)
            except anthropic.AnthropicError as e:
                raise FatalLLMError(f"{NO_CREDENTIALS} ({e})") from e
        # Without a key, a token or a login profile the SDK only fails at request
        # time, and with a bare TypeError. Say so now, in words.
        if not (client.api_key or client.auth_token or client.credentials):
            raise FatalLLMError(NO_CREDENTIALS)
        self._client = client
        self._gate = asyncio.Semaphore(max_concurrency)

    def _request(self, system: str, user: str) -> dict:
        return {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            # the system prompt is identical on every turn of an agent: cache it
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "thinking": {"type": self.config.thinking},
            "output_config": {"effort": self.config.effort},
        }

    async def complete(self, system: str, user: str, *, seed: int | None = None) -> LLMResponse:
        anthropic = self._anthropic
        async with self._gate:
            started = time.monotonic()
            try:
                message = await self._client.messages.create(**self._request(system, user))
            except (
                anthropic.AuthenticationError,
                anthropic.PermissionDeniedError,
                anthropic.NotFoundError,
                anthropic.BadRequestError,
            ) as e:
                raise FatalLLMError(f"{type(e).__name__}: {e.message}") from e
            except anthropic.RateLimitError as e:
                raise LLMError(f"rate limited after retries: {e.message}") from e
            except anthropic.APIStatusError as e:
                raise LLMError(f"API error {e.status_code}: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise LLMError(f"connection error: {e}") from e
            except anthropic.AnthropicError as e:  # e.g. no credentials configured
                raise FatalLLMError(f"{type(e).__name__}: {e}") from e
            latency = time.monotonic() - started

        usage = message.usage
        return LLMResponse(
            # a response can begin with thinking blocks: read content by type, not position
            text="".join(block.text for block in message.content if block.type == "text"),
            model=message.model,
            stop_reason=message.stop_reason,
            usage=Usage(
                calls=1,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=usage.cache_read_input_tokens or 0,
                cache_write_tokens=usage.cache_creation_input_tokens or 0,
            ),
            latency_s=round(latency, 3),
            request_id=getattr(message, "_request_id", None),
        )

    async def close(self) -> None:
        await self._client.close()


def has_api_credentials() -> bool:
    """Whether the SDK can find a Claude API credential (key, token or login profile)."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    import anthropic

    try:
        client = anthropic.AsyncAnthropic()
    except anthropic.AnthropicError:
        return False
    return bool(client.api_key or client.auth_token or client.credentials)


def make_llm(config: LLMConfig, max_concurrency: int = 8) -> LLM:
    if config.provider == "mock":
        from amongagents.agent.mock import MockLLM

        return MockLLM(config)
    return AnthropicLLM(config, max_concurrency=max_concurrency)


async def check_connection(config: LLMConfig) -> dict:
    """Send one tiny request to confirm the key, the model and the request shape are accepted."""
    try:
        llm = make_llm(config, max_concurrency=1)
    except LLMError as e:
        return {"ok": False, "error": str(e)}
    try:
        response = await llm.complete(
            "You are a connectivity check.", "Reply with the single word OK."
        )
        return {
            "ok": True,
            "model": response.model,
            "reply": response.text.strip()[:80],
            "latency_s": response.latency_s,
        }
    except LLMError as e:
        return {"ok": False, "error": str(e)}
    finally:
        await llm.close()
