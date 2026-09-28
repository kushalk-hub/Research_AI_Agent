"""LLM abstraction.

Only GEMINI_API_KEY is present on this machine, so Gemini is the shipped
implementation. The protocol is deliberately small: another provider needs one
class implementing `LLMClient` plus a key in config — no call sites change.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from rla.llm.usage import TokenUsage, usage_from_mapping
from rla.store.cache import CostTracker


class LLMError(RuntimeError):
    """Raised when a model call fails or returns unusable output.

    Deliberately the *parent* of the normalised `ProviderError` categories, so a
    backend can raise a precise category while every existing `except LLMError`
    handler keeps working unchanged. `llm.errors` imports this name, so the
    inheritance is completed there rather than here -- that keeps `base.py` free
    of the error-category module while still giving the required `isinstance`
    relationship.
    """


@runtime_checkable
class LLMClient(Protocol):
    """Structured-output contract shared by every provider."""

    @property
    def fast_model(self) -> str: ...

    @property
    def strong_model(self) -> str: ...

    async def generate_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> str:
        """Free-text completion."""
        ...

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> BaseModel:
        """Completion constrained to `schema`. Must raise LLMError if unparseable."""
        ...

    async def stream_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> Any:
        """Async iterator over answer chunks, for the streamed answer panel."""
        ...


def usage_from_response(response: Any) -> TokenUsage:
    """Extract token usage from a provider response, provider-neutrally.

    Reads whatever usage block the response carries -- `usage` (OpenAI/LiteLLM
    shape) or `usage_metadata` (Gemini SDK shape) -- by attribute or mapping key.

    Returns `TokenUsage.unknown()` rather than zeros when nothing is recognised.
    The distinction matters: an unknown token count reported as `0` renders as a
    confident `$0.00` and makes a provider change look like a cost *reduction*.
    """
    if response is None:
        return TokenUsage.unknown()

    # LiteLLM/OpenAI shape first, then the native Gemini SDK shape.
    for attr in ("usage", "usage_metadata"):
        block = getattr(response, attr, None)
        if block is None and isinstance(response, dict):
            block = response.get(attr)
        if block is not None:
            usage = usage_from_mapping(block)
            if usage.known:
                return usage

    # A bare mapping that *is* the usage block.
    if isinstance(response, dict):
        return usage_from_mapping(response)
    return usage_from_mapping(response)


def record_usage(tracker: CostTracker, stage: str, response: Any) -> None:
    """Record a call's token usage, including the streamed case.

    Streaming responses report usage on the final chunk rather than on the
    aggregate, so callers pass whichever object carries it. Unknown usage is
    recorded as unknown rather than skipped, so `unknown_usage_calls` reflects
    reality.
    """
    usage = usage_from_response(response)
    tracker.record(stage, usage.input_tokens, usage.output_tokens)


__all__ = [
    "LLMClient",
    "LLMError",
    "TokenUsage",
    "record_usage",
    "usage_from_response",
]
